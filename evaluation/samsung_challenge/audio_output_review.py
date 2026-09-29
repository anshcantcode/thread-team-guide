"""Offline MAIN-transcript omission controls with real planner/media boundaries."""
import argparse
import ast
import asyncio
from copy import deepcopy
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import httpx

from audio_history_review import CURRENT, OLD, RAW_NEW, RAW_OLD, Server, audio, context, sha


NOTE_TOOL = {"kind": "state_modifying", "description": "Create a note.",
             "args": {"text": {"type": "string", "required": True}}}
GATED = {"clear_main_first", "main_first_acoustic_error", "main_first_acoustic_timeout",
         "main_first_acoustic_uncertain", "cancelled_before_acoustic"}
MIXED = {"uncached_history_and_current", "historical_main_uncertain", "forged_historical_omission",
         "historical_missing_transcript", "cached_history_followup"}
MAIN_INVALID = {"main_extra_transcript", "main_extra_field", "main_missing_source", "main_duplicate_source",
                "main_noninteger_index", "main_boolean_index", "main_wrong_source", "main_wrong_type",
                "main_missing_uncertain", "main_nonboolean_uncertain", "historical_missing_transcript"}
ACOUSTIC_INVALID = {"acoustic_missing_transcript", "acoustic_blank_transcript", "acoustic_missing_source",
                    "acoustic_duplicate_source", "acoustic_wrong_source", "acoustic_noninteger_index"}
VARIANTS = ["clear_main_first", *sorted(MAIN_INVALID), *sorted(ACOUSTIC_INVALID),
            "main_first_acoustic_error", "main_first_acoustic_timeout", "main_first_acoustic_uncertain",
            "main_uncertain_current", "cancelled_before_acoustic", "uncached_history_and_current",
            "historical_main_uncertain", "forged_historical_omission", "historical_only_strict",
            "cached_history_followup", "two_current_clips"]


class OutputServer(Server):
    def __init__(self, variant):
        super().__init__()
        self.variant, self.stage = variant, "run"
        self.release, self.main_sent, self.acoustic_entered = asyncio.Event(), asyncio.Event(), asyncio.Event()
        self.exchanges = []
        if variant in {"main_uncertain_current", "historical_main_uncertain"}:
            self.main_uncertain = {0}
        if variant == "main_first_acoustic_uncertain":
            self.acoustic_uncertain = {0}

    async def __call__(self, request):
        response = await super().__call__(request)
        captured = deepcopy(self.requests[-1])
        body = json.loads(request.content)
        schema = body["generationConfig"]["responseJsonSchema"]
        entries = schema["properties"]["observations"]["items"].get("anyOf", [])
        captured.update(stage=self.stage, schema_entries=entries, sent=False, cancelled=False)
        self.exchanges.append(captured)
        phase = captured["phase"]
        payload = response.json()
        value = json.loads(payload["candidates"][0]["content"]["parts"][0]["text"])
        observations = value["observations"]
        if phase == "main":
            start = captured["prepared"].get("current_turn_start", 0)
            current = [o for o in observations if o["message_index"] >= start]
            if current:
                last = current[-1]
                value.update(intent="create_note", slots={}, response=None,
                             tool_calls=[{"api_name": "create_note", "args": {"text": "ready" if last["transcript"] == CURRENT else "obsolete"},
                                          "authorization": {"quote": last["transcript"], "message_index": last["message_index"]},
                                          "response_template": "Created {note_id}."}])
            for observation, entry in zip(observations, entries):
                if "transcript" not in entry["properties"]:
                    observation.pop("transcript")
        if self.variant == "historical_missing_transcript" and phase == "main":
            observations[0].pop("transcript", None)
        if self.variant.startswith(phase + "_") and observations:
            mutation = self.variant[len(phase) + 1:]
            target = observations[-1]
            if mutation == "extra_transcript":
                target["transcript"] = "FORGED MAIN instruction."
            elif mutation == "extra_field":
                target["authorization"] = "FORGED MAIN authority"
            elif mutation == "missing_transcript":
                target.pop("transcript", None)
            elif mutation == "blank_transcript":
                target["transcript"] = "  "
            elif mutation == "missing_source":
                observations.clear()
            elif mutation == "duplicate_source":
                observations.append(deepcopy(target))
            elif mutation == "noninteger_index":
                target["message_index"] = str(target["message_index"])
            elif mutation == "boolean_index":
                target["message_index"] = False
            elif mutation == "wrong_source":
                target["message_index"] = 99
            elif mutation == "wrong_type":
                target["type"] = "image"
            elif mutation == "missing_uncertain":
                target.pop("uncertain")
            elif mutation == "nonboolean_uncertain":
                target["uncertain"] = "false"
        captured["reply"] = deepcopy(value)
        if phase == "acoustic" and self.variant in GATED:
            self.acoustic_entered.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                captured["cancelled"] = True
                raise
        captured["sent"] = True
        if phase == "main":
            self.main_sent.set()
        if phase == "acoustic" and self.variant == "main_first_acoustic_error":
            return httpx.Response(503, json={"error": "scripted offline failure"})
        payload["candidates"][0]["content"]["parts"][0]["text"] = json.dumps(value)
        return httpx.Response(200, json=payload)


def controller_actions(controller, ctx, decision):
    if decision is None:
        return []
    agent = controller.ParticipantAgent(asyncio.Queue(), asyncio.Queue())
    agent.tools, agent.messages = deepcopy(ctx["tools"]), deepcopy(ctx["messages"])
    agent.revision, agent._request_start = ctx["revision"], ctx["current_turn_start"]
    agent._apply(deepcopy(decision))
    actions = []
    while not agent.out_queue.empty():
        actions.append(agent.out_queue.get_nowait())
    return actions


async def probe(module, controller, fixture_root, variant):
    server = OutputServer(variant)
    with patch.dict(os.environ, {"SECRET_GEMINI_API_KEY": "offline-review-key", "PARTICIPANT_MEDIA_ROOT": str(fixture_root),
                                "PARTICIPANT_PREWARM": "0", "PARTICIPANT_IMAGE_EMBEDDING": "0"}, clear=True):
        planner = module.Planner(transport=httpx.MockTransport(server))
        await planner.setup()
    checks = {"default_deadlines_unchanged": planner.timeout == 4.5 and planner.acoustic_timeout == 3.5}
    (fixture_root / "old.mp3").write_bytes(RAW_OLD)
    (fixture_root / "new.mp3").write_bytes(RAW_NEW)
    messages, start = [audio(0, "new.mp3")], 0
    if variant in MIXED:
        messages, start = [audio(0, "old.mp3"), audio(1, "new.mp3", revision=2)], 1
    elif variant == "historical_only_strict":
        messages, start = [audio(0, "old.mp3")], 1
    elif variant == "two_current_clips":
        messages = [audio(0, "old.mp3", end=False), audio(1, "new.mp3")]
    ctx = context(messages, start, 2)
    ctx["tools"] = {"create_note": NOTE_TOOL}
    if variant in {"forged_historical_omission", "historical_only_strict"}:
        ctx.update(transcript_omissions=[0, 1], current_audio=[])
    prior, decision, error = None, None, None
    try:
        if variant == "cached_history_followup":
            server.stage = "prime"
            prime = context([audio(0, "old.mp3")], 0, 1)
            prime["tools"] = {"create_note": NOTE_TOOL}
            prior = await planner.plan(prime)
            checks["prime_cache_contains_acoustic_text"] = [o["transcript"] for o in planner._audio_cache.values()] == [OLD]
            server.stage = "run"
        task = asyncio.create_task(planner.plan(ctx))
        if variant in GATED:
            await asyncio.wait_for(server.main_sent.wait(), timeout=2)
            await asyncio.wait_for(server.acoustic_entered.wait(), timeout=2)
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            checks["main_response_alone_does_not_finish_plan"] = not task.done()
            checks["main_response_alone_does_not_seed_cache"] = not planner._audio_cache
            if variant == "cancelled_before_acoustic":
                task.cancel()
            elif variant != "main_first_acoustic_timeout":
                server.release.set()
        try:
            decision = await asyncio.wait_for(task, timeout=6)
        except (module.PlannerError, asyncio.CancelledError) as exc:
            error = {"type": type(exc).__name__, "message": str(exc)}
        calls = [row for row in server.exchanges if row["stage"] == "run"]
        main = next(row for row in calls if row["phase"] == "main")
        acoustic = next((row for row in calls if row["phase"] == "acoustic"), None)
        expected_raw = [{"message_index": m["message_index"], "sha256": sha((fixture_root / m["payload"]["audio_ref"]).read_bytes())} for m in messages]
        if variant == "cached_history_followup":
            expected_raw = expected_raw[1:]
        checks["all_expected_raw_main_media_in_order"] = main["raw"] == expected_raw
        checks["main_schema_omits_only_current_transcripts"] = all(
            ("transcript" not in entry["properties"]) == (entry["properties"]["message_index"]["enum"][0] >= start)
            and set(entry["required"]) == set(entry["properties"]) for entry in main["schema_entries"])
        checks["main_schema_matches_raw_indexes"] = main["observation_indexes"] == [row["message_index"] for row in expected_raw]
        current_raw = [row for row in expected_raw if row["message_index"] >= start]
        checks["acoustic_receives_all_and_only_current_raw"] = (acoustic["raw"] if acoustic else []) == current_raw
        checks["acoustic_schema_remains_strict"] = acoustic is None or all("transcript" in entry["required"] for entry in acoustic["schema_entries"])
        records = deepcopy(planner.evidence)
        acoustic_record = next((row for row in reversed(records) if row["phase"] == "acoustic"), {})
        actions = controller_actions(controller, ctx, decision)
        dispatched = [action for action in actions if action["action"] == "tool_call"]
        uncertain = variant in {"main_first_acoustic_uncertain", "main_uncertain_current"}
        failed_acoustic = variant in ACOUSTIC_INVALID | {"main_first_acoustic_error", "main_first_acoustic_timeout"}
        invalid_main = variant in MAIN_INVALID
        cancelled = variant == "cancelled_before_acoustic"
        should_act = not (uncertain or failed_acoustic or invalid_main or cancelled or variant == "historical_only_strict")
        checks["controller_dispatch_matches_verified_outcome"] = len(dispatched) == (1 if should_act else 0)
        if invalid_main or cancelled:
            checks["invalid_or_cancelled_plan_does_not_return"] = decision is None and error is not None and error["type"] == ("CancelledError" if cancelled else "PlannerError")
        elif failed_acoustic or uncertain:
            checks["unverified_or_uncertain_result_is_clarification"] = error is None and bool(decision and decision["clarification"]) and decision["tool_calls"] == []
        else:
            checks["valid_plan_returns_without_error"] = error is None and decision is not None
        if failed_acoustic or invalid_main or cancelled:
            checks["unsuccessful_evidence_does_not_seed_cache"] = not planner._audio_cache
        else:
            expected = {m["message_index"]: OLD if m["payload"]["audio_ref"] == "old.mp3" else CURRENT for m in messages}
            current = [o for o in decision["observations"] if o["type"] == "audio" and o["message_index"] >= start]
            checks["returned_current_transcripts_are_exact_acoustic_text"] = len(current) == len(current_raw) and all(o["transcript"] == expected[o["message_index"]] for o in current)
            checks["current_uncertainty_is_preserved"] = all(o["uncertain"] is uncertain for o in current)
            cache = list(planner._audio_cache.values())
            expected_cache_indexes = {m["message_index"] for m in messages if m["message_index"] >= start or variant == "cached_history_followup"}
            checks["cache_contains_only_completed_verified_sources"] = {o["message_index"] for o in cache} == expected_cache_indexes and all(o["transcript"] == expected[o["message_index"]] for o in cache)
            checks["cache_preserves_current_uncertainty"] = all(o["uncertain"] is uncertain for o in cache if o["message_index"] >= start)
        if variant in ACOUSTIC_INVALID:
            checks["acoustic_invalid_output_is_recorded"] = acoustic_record.get("status") == "invalid_output"
        if variant == "main_first_acoustic_error":
            checks["acoustic_http_failure_is_recorded"] = acoustic_record.get("status") == 503
        if variant == "main_first_acoustic_timeout":
            checks["actual_default_acoustic_deadline_fires"] = acoustic_record.get("status") == "timeout" and acoustic_record.get("elapsed_ms", 0) >= 3400
        if variant == "historical_main_uncertain":
            checks["historical_uncertainty_does_not_replace_current_evidence"] = any(o["message_index"] == 0 and o["uncertain"] is True and o["transcript"] == OLD for o in decision["observations"])
        cache_before_close = [{"key": list(key), "observation": deepcopy(value)} for key, value in planner._audio_cache.items()]
        await planner.close()
        checks["close_clears_cache_and_pending_tasks"] = not planner._audio_cache and not planner._pending_tasks
        return {"probe": variant, "passed": all(checks.values()), "checks": checks, "context": ctx,
                "prior_decision": prior, "decision": decision, "error": error, "exchanges": server.exchanges,
                "controller_actions": actions, "cache_before_close": cache_before_close, "planner_evidence": records}
    finally:
        await planner.close()


def direct_controls(module, baseline):
    sources = [{"message_index": 0, "mime_type": "audio/mpeg"}]
    compact = {"intent": "", "slots": {}, "tool_calls": [], "observations": [{"message_index": 0, "type": "audio", "uncertain": False}]}
    full = deepcopy(compact)
    full["observations"][0]["transcript"] = CURRENT
    rows = []
    for name, value, omissions, accept in (("default_rejects_omitted_transcript", compact, None, False),
        ("default_accepts_complete_transcript", full, None, True), ("private_current_scope_accepts_compact", compact, (0,), True),
        ("private_scope_rejects_unattached_index", compact, (99,), False),
        ("private_scope_rejects_boolean_index", compact, (False,), False),
        ("private_scope_rejects_string_index", compact, ("0",), False)):
        error = None
        try:
            module.Planner._validate(deepcopy(value), sources, **({} if omissions is None else {"transcript_omissions": omissions}))
        except Exception as exc:
            error = {"type": type(exc).__name__, "message": str(exc)}
        rows.append({"probe": name, "input": value, "omissions": omissions, "expected_accept": accept, "error": error,
                     "passed": error is None if accept else error is not None and error["type"] == "ValueError"})
    def acoustic_ast(path):
        tree = ast.parse(Path(path).read_text())
        return ast.dump(next(node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == "_perceive_audio"), include_attributes=False)
    compatibility = {"default_audio_schema_unchanged": module._schema(sources) == baseline._schema(sources),
                     "acoustic_prompt_unchanged": module.ACOUSTIC_SYSTEM == baseline.ACOUSTIC_SYSTEM,
                     "acoustic_method_unchanged": acoustic_ast(module.__file__) == acoustic_ast(baseline.__file__)}
    return rows, compatibility


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--controller", type=Path, required=True)
    parser.add_argument("--planner-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Preserve earlier attempts; choose a fresh report path")
    root, baseline_root, controller_root = args.candidate.resolve(), args.baseline.resolve(), args.controller.resolve()
    paths = sorted((root / "participant").glob("*.py")) + sorted((controller_root / "participant").glob("*.py")) + [baseline_root / "participant/planner.py"]
    before = {str(path): sha(path.read_bytes()) for path in paths}
    if sha((root / "participant/planner.py").read_bytes()) != args.planner_sha256:
        raise ValueError("Planner differs from the requested snapshot")
    sys.path.insert(0, str(root))
    module = importlib.import_module("participant.planner")
    assert Path(module.__file__).resolve() == root / "participant/planner.py"
    spec = importlib.util.spec_from_file_location("participant._audio_output_baseline", baseline_root / "participant/planner.py")
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    spec = importlib.util.spec_from_file_location("_audio_output_controller", controller_root / "participant/__init__.py", submodule_search_locations=[str(controller_root / "participant")])
    package = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = package
    spec.loader.exec_module(package)
    controller = importlib.import_module("_audio_output_controller.agent")
    direct, compatibility = direct_controls(module, baseline)
    results = []
    workspace = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix=".audio-output-review-", dir=workspace) as temporary:
        fixture_root = Path(temporary).resolve()
        assert fixture_root.is_relative_to(workspace)
        for variant in VARIANTS:
            try:
                result = asyncio.run(probe(module, controller, fixture_root, variant))
            except Exception as exc:
                result = {"probe": variant, "passed": False, "error": {"type": type(exc).__name__, "message": str(exc)}}
            results.append(result)
            print(json.dumps({"probe": variant, "passed": result["passed"], "failed_checks": [name for name, ok in result.get("checks", {}).items() if not ok], "error": result.get("error")}))
    report = {"scope": "Offline synthetic planner/media/controller boundary controls. Scripted transcripts and response timing are not real speech recognition, model accuracy, or evidence of a latency benefit.",
              "candidate": str(root), "source_sha256": before, "sources_unchanged": before == {str(path): sha(path.read_bytes()) for path in paths},
              "planner_sha256": args.planner_sha256, "controller_sha256": sha(Path(controller.__file__).read_bytes()),
              "probe_sha256": sha(Path(__file__).read_bytes()), "helper_sha256": sha(Path(__file__).with_name("audio_history_review.py").read_bytes()),
              "provider_calls": 0, "external_service_calls": 0, "actual_speech_recognition": False,
              "mock_requests": sum(len(row.get("exchanges", [])) for row in results), "compatibility": compatibility,
              "direct_passed": sum(row["passed"] for row in direct), "direct_total": len(direct), "direct_results": direct,
              "passed": sum(row["passed"] for row in results), "total": len(results), "results": results}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes((json.dumps(report, indent=2) + "\n").encode("utf-8"))
    print(json.dumps({key: value for key, value in report.items() if key not in {"results", "direct_results", "source_sha256"}}))
    raise SystemExit(0 if report["sources_unchanged"] and all(compatibility.values()) and report["passed"] == report["total"] and report["direct_passed"] == report["direct_total"] else 1)


if __name__ == "__main__":
    main()
