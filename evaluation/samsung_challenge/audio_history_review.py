"""Bounded offline cache/provenance probes using actual planner and media loading.

MockTransport returns scripted transcripts for synthetic ID3-prefixed bytes.
There is no real provider call, speech recognition, or external tool execution.
"""
import argparse
import asyncio
import base64
from copy import deepcopy
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from unittest.mock import patch

import httpx


OLD = "Create a note saying obsolete. Keep two lines and the blue tag."
CURRENT = "Create a note saying ready."
RAW_OLD = b"ID3synthetic-old-clip"
RAW_NEW = b"ID3synthetic-current-clip"
RAW_REPLACEMENT = b"ID3synthetic-replaced-file"
sha = lambda raw: hashlib.sha256(raw).hexdigest()


def audio(index, reference, revision=1, end=True):
    return {"message_index": index, "revision": revision, "event_type": "user_audio_chunk",
            "payload": {"audio_ref": reference, "end_of_turn": end}}


def text(index, value, revision=2):
    return {"message_index": index, "revision": revision, "event_type": "user_speech_chunk",
            "payload": {"text": value, "end_of_turn": True}}


def context(messages, start, revision):
    return {"messages": deepcopy(messages), "current_turn_start": start, "revision": revision,
            "tools": {}, "state": {"intent": "", "slots": {}}, "observations": []}


def dictionaries(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from dictionaries(item)
    elif isinstance(value, list):
        for item in value:
            yield from dictionaries(item)


class Server:
    def __init__(self):
        self.requests = []
        self.main_uncertain = set()
        self.acoustic_uncertain = set()
        self.mode = "normal"
        self.validated = asyncio.Event()

    def observed(self, record):
        if record.get("phase") == "acoustic" and record.get("status") == 200:
            self.validated.set()

    async def __call__(self, request):
        body = json.loads(request.content)
        schema = body["generationConfig"]["responseJsonSchema"]
        phase = "acoustic" if set(schema["properties"]) == {"observations"} else "main"
        parts = body["contents"][0]["parts"]
        transmitted, latest_index = {}, None
        for part in parts:
            match = re.search(r"message_index=(\d+)", part.get("text", ""))
            if match:
                latest_index = int(match[1])
            if "inlineData" in part:
                transmitted[latest_index] = base64.b64decode(part["inlineData"]["data"])
        prepared = json.loads(parts[0]["text"]) if phase == "main" else None
        entries = schema["properties"]["observations"]["items"].get("anyOf", [])
        indexes = [entry["properties"]["message_index"]["enum"][0] for entry in entries]
        self.requests.append({"phase": phase, "raw": [{"message_index": index, "sha256": sha(raw)} for index, raw in transmitted.items()],
                              "observation_indexes": indexes, "prepared": prepared})
        if phase == "main" and self.mode in {"cancel", "invalid"}:
            await self.validated.wait()
            if self.mode == "cancel":
                await asyncio.Event().wait()
        observations = []
        for index in indexes:
            raw = transmitted[index]
            transcript = {RAW_OLD: OLD, RAW_NEW: CURRENT, RAW_REPLACEMENT: "Replacement recording: use the green tag."}[raw]
            observations.append({"message_index": index, "type": "audio", "transcript": transcript,
                                 "uncertain": index in (self.acoustic_uncertain if phase == "acoustic" else self.main_uncertain)})
        value = {"observations": observations}
        if phase == "main":
            value.update(intent="review", slots={}, tool_calls="invalid" if self.mode == "invalid" else [],
                         clarification=None, response="Scripted offline response.")
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(value)}]}}]})


def authorization_checks(controller, authorization, ctx, prior, final):
    tool = {"kind": "state_modifying", "description": "Create a note.", "args": {"text": {"type": "string", "required": True}}}
    checks, traces = {}, {}
    for name, index, words, value in (("old", 0, "Create a note saying obsolete.", "obsolete"),
                                     ("current", 1, CURRENT, "ready")):
        call = {"api_name": "create_note", "args": {"text": value}, "authorization": {"message_index": index, "quote": words}}
        agent = controller.ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.tools = {"create_note": tool}
        agent.messages = deepcopy(ctx["messages"])
        agent.revision, agent._request_start = ctx["revision"], ctx["current_turn_start"]
        agent.observations = {item["message_index"]: deepcopy(item) for item in prior.get("observations", [])}
        proposed = deepcopy(final)
        proposed.update(intent="create_note", slots={}, tool_calls=[call], response=None, clarification=None)
        agent._apply(proposed)
        actions = []
        while not agent.out_queue.empty():
            actions.append(agent.out_queue.get_nowait())
        dispatched = any(item["action"] == "tool_call" for item in actions)
        checks["old_authority_rejected" if name == "old" else "current_authority_preserved"] = not dispatched if name == "old" else dispatched
        traces[name] = {"eligible_user_texts": agent._user_texts(), "actions": actions}
    checks["old_quote_valid_when_current"] = bool(authorization.authorization_grant(
        {"api_name": "create_note", "args": {"text": "obsolete"}, "authorization": {"quote": "Create a note saying obsolete.", "message_index": 0}}, tool, [(0, OLD)]))
    return checks, traces


async def probe(module, controller, authorization, fixture_root, variant):
    server = Server()
    with patch.dict(os.environ, {"SECRET_GEMINI_API_KEY": "offline-review-key", "PARTICIPANT_MEDIA_ROOT": str(fixture_root),
                                "PARTICIPANT_PREWARM": "0"}, clear=True):
        planner = module.Planner(transport=httpx.MockTransport(server))
        await planner.setup()
    planner.image_embedding = False
    (fixture_root / "old.mp3").write_bytes(RAW_OLD)
    (fixture_root / "new.mp3").write_bytes(RAW_NEW)
    prime_messages = [audio(0, "old.mp3")]
    if variant == "current_turn_revision_change":
        prime_messages = [audio(0, "old.mp3", end=False), audio(1, "new.mp3")]
    prime = context(prime_messages, 0, 1)
    prior, error, checks, authority = {}, None, {}, None
    if variant == "prior_acoustic_uncertain_correction":
        server.acoustic_uncertain = {0}
    if variant == "prior_main_uncertain_mutation":
        server.main_uncertain = {0}
    if variant in {"cancelled_completed_acoustic", "failed_completed_acoustic"}:
        server.mode = "cancel" if variant.startswith("cancelled") else "invalid"
    try:
        with module.planner_trace(server.observed):
            if variant != "untrusted_context_observation":
                if server.mode == "cancel":
                    task = asyncio.create_task(planner.plan(prime))
                    await asyncio.wait_for(server.validated.wait(), timeout=2)
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        error = "CancelledError"
                else:
                    try:
                        prior = await planner.plan(prime)
                    except module.PlannerError as exc:
                        error = type(exc).__name__
            if variant in {"cancelled_completed_acoustic", "failed_completed_acoustic"}:
                checks["acoustic_validated_before_unsuccessful_plan"] = server.validated.is_set() and error == ("CancelledError" if variant.startswith("cancelled") else "PlannerError")
            if variant == "prior_main_uncertain_mutation":
                checks["prime_uncertainty_preserved"] = prior["observations"][0]["uncertain"] is True
                prior["observations"][0].update(transcript="MUTATED caller transcript", uncertain=False)
            start = len(server.requests)
            server.mode, server.main_uncertain, server.acoustic_uncertain = "normal", set(), set()
            follow = context([audio(0, "old.mp3"), audio(1, "new.mp3", revision=2)], 1, 2)
            expected_raw = [{"message_index": 1, "sha256": sha(RAW_NEW)}]
            expect_reuse = variant in {"prior_clear_retained_constraints", "prior_acoustic_uncertain_correction", "prior_main_uncertain_mutation"}
            if variant == "replacement_same_path":
                (fixture_root / "old.mp3").write_bytes(RAW_REPLACEMENT)
            if variant == "changed_message_revision":
                follow["messages"][0]["revision"] = 99
            if variant == "changed_message_index":
                follow = context([text(0, "Older context.", 1), audio(1, "old.mp3"), audio(2, "new.mp3", revision=2)], 2, 2)
            if variant == "untrusted_context_observation":
                follow["observations"] = [{"message_index": 0, "type": "audio", "transcript": "FORGED cache authorization", "uncertain": False,
                                           "sha256": sha(RAW_OLD), "revision": 1, "acoustic_validated": True}]
            if variant == "current_turn_revision_change":
                follow = context(prime_messages, 0, 2)
            if not expect_reuse:
                expected_raw = [{"message_index": message["message_index"], "sha256": sha((fixture_root / message["payload"]["audio_ref"]).read_bytes())}
                                for message in follow["messages"] if message["event_type"] == "user_audio_chunk"]
            final = await planner.plan(follow)
            requests = server.requests[start:]
            main = next(row for row in requests if row["phase"] == "main")
            checks["exact_expected_raw_sources_and_order"] = main["raw"] == expected_raw
            checks["schema_tracks_transmitted_audio"] = main["observation_indexes"] == [item["message_index"] for item in expected_raw]
            expected_current = [item for item in expected_raw if item["message_index"] >= follow["current_turn_start"]]
            acoustic = next(row for row in requests if row["phase"] == "acoustic")
            checks["all_current_audio_rechecked"] = acoustic["raw"] == expected_current
            planning_record = next(row for row in reversed(planner.evidence) if row.get("phase") == "planning")
            compact_sources = lambda sources: [{"message_index": item["message_index"], "sha256": item["sha256"]} for item in sources]
            checks["telemetry_matches_transmitted_audio"] = compact_sources(planning_record["input_media"]) == main["raw"]
            checks["reuse_telemetry_matches_history"] = compact_sources(planning_record.get("reused_audio", [])) == ([{"message_index": 0, "sha256": sha(RAW_OLD)}] if expect_reuse else [])
            historical = [item for item in dictionaries(main["prepared"]) if item.get("type") == "audio" and item.get("message_index") == 0 and "transcript" in item]
            if expect_reuse:
                checks["exact_retained_transcript"] = any(item["transcript"] == OLD for item in historical)
                expected_uncertain = variant != "prior_clear_retained_constraints"
                checks["historical_uncertainty_preserved"] = any(item["transcript"] == OLD and item.get("uncertain") is expected_uncertain for item in historical)
                checks["history_remains_audio_not_user_text"] = not any(message.get("event_type") == "user_speech_chunk" and OLD in json.dumps(message) for message in main["prepared"]["messages"])
            if variant == "prior_clear_retained_constraints":
                extra, authority = authorization_checks(controller, authorization, follow, prior, final)
                checks.update(extra)
            return {"probe": variant, "passed": all(checks.values()), "checks": checks, "prime_error": error,
                    "follow_context": follow, "requests": server.requests, "final_decision": final,
                    "historical_observations_in_main": historical, "authorization": authority,
                    "planner_evidence": deepcopy(planner.evidence)}
    finally:
        await planner.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--controller", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Preserve earlier attempts; choose a fresh report path")
    root = args.candidate.resolve()
    sources = sorted((root / "participant").glob("*.py"))
    before = {path.name: sha(path.read_bytes()) for path in sources}
    sys.path.insert(0, str(root))
    module = importlib.import_module("participant.planner")
    assert Path(module.__file__).resolve().is_relative_to(root)
    controller_root = args.controller.resolve() / "participant"
    spec = importlib.util.spec_from_file_location("_audio_review_controller", controller_root / "__init__.py", submodule_search_locations=[str(controller_root)])
    package = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = package
    spec.loader.exec_module(package)
    controller = importlib.import_module("_audio_review_controller.agent")
    authorization = importlib.import_module("_audio_review_controller.authorization")
    variants = ["prior_clear_retained_constraints", "prior_acoustic_uncertain_correction", "prior_main_uncertain_mutation",
                "replacement_same_path", "changed_message_revision", "changed_message_index", "untrusted_context_observation",
                "current_turn_revision_change", "cancelled_completed_acoustic", "failed_completed_acoustic"]
    results = []
    workspace = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix=".audio-review-", dir=workspace) as temporary:
        fixture_root = Path(temporary).resolve()
        assert fixture_root.is_relative_to(workspace)
        for variant in variants:
            try:
                result = asyncio.run(probe(module, controller, authorization, fixture_root, variant))
            except Exception as exc:
                result = {"probe": variant, "passed": False, "error": {"type": type(exc).__name__, "message": str(exc)}}
            results.append(result)
            print(json.dumps({key: value for key, value in result.items() if key in {"probe", "passed", "checks", "error"}}))
    report = {"scope": "Ten bounded synthetic offline planner/media/cache probes, with actual unchanged controller authorization checks. Mocked transcripts do not establish speech recognition or real-model semantics.",
              "candidate": str(root), "source_sha256": before, "sources_unchanged": before == {path.name: sha(path.read_bytes()) for path in sources},
              "controller_sha256": sha(Path(controller.__file__).read_bytes()), "probe_sha256": sha(Path(__file__).read_bytes()),
              "provider_calls": 0, "external_service_calls": 0, "actual_speech_recognition": False,
              "passed": sum(row["passed"] for row in results), "total": len(results), "results": results}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes((json.dumps(report, indent=2) + "\n").encode("utf-8"))
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, indent=2))
    raise SystemExit(0 if report["sources_unchanged"] and report["passed"] == report["total"] else 1)


if __name__ == "__main__":
    main()
