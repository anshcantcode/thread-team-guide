"""Paired evaluator-side text / actual-ASR-text / paced WebRTC diagnostics.

Requires existing local services/assets. Never starts services or downloads.
Faithful transcript input is not an answer summary. Metadata is evaluator-only.
Replay uses the whole recorded wording as one turn: timing/fragmentation differ.
"""
import argparse
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.fdb3_evaluate import checkpoint_json
from scripts.fdb3_run import campaign_lock, evaluate_snapshot
from thread_agent.fdb3_evidence import audio_duration_seconds, file_hash, upstream_window, verify_tool_trace

MODES = ("live_audio", "text", "asr_text")
LAYERS = ("recognition", "fragment_admission", "planner_schema", "authorization_false_rejection",
          "binding", "transport", "synthesis_output", "evaluator_failure")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def actual_asr_text(result):
    """Raw successful decodes, including stale-dropped speech; no quote repair."""
    rows = result.get("input_transcripts", [])
    if not result.get("input_finished_at") or not rows:
        raise ValueError("Complete input and actual recognition records required for ASR replay")
    decoded = [row for row in result.get("voice_events", []) if row.get("event") == "speech_segment_recognition"]
    if (not decoded or len(decoded) != len(rows) or any(row.get("outcome") != "success" for row in decoded)
            or any(not isinstance(row.get("text"), str) for row in rows)
            or [row.get("text") for row in decoded] != [row["text"] for row in rows]):
        raise ValueError("Missing, failed, or unmatched ASR segment receipts; partial replay refused")
    onsets = [row for row in result.get("voice_events", []) if row.get("event") == "speech_segment_started"]
    if onsets:
        order = {row.get("segment_id"): index for index, row in enumerate(onsets)}
        ids = [row.get("segment_id") for row in decoded]
        if len(order) != len(onsets) or len(set(ids)) != len(ids) or set(ids) != set(order):
            raise ValueError("Missing or repeated onset identity; partial ASR replay refused")
        decoded = sorted(decoded, key=lambda row: order[row["segment_id"]])
    text = " ".join(row["text"] for row in decoded)
    if not text.strip():
        raise ValueError("All actual ASR decodes were empty; no substitute transcript")
    return text


def mode_candidates(layers):
    """Within-mode candidate layers from recorded evidence; never a verdict."""
    candidates = []
    if layers.get("errors") or layers.get("judge_errors"):
        candidates.append(("evaluator_failure" if layers.get("judge_errors") else "transport",
                           "recorded infrastructure/judge error"))
    if any(row.get("proposed_calls") is None and row.get("outcome") == "success" for row in layers.get("proposals", [])) or any(
            row.get("outcome") == "error" for row in layers.get("proposals", [])):
        candidates.append(("planner_schema", "malformed or failed model proposal"))
    for row in layers.get("rejections_and_clarifications", []):
        text = str(row.get("payload", {}).get("text", ""))
        # Spoken validation questions carry the validator's problems as evidence;
        # older runs spoke them after "I need valid details before acting".
        validation = row.get("payload", {}).get("validation")
        if "confirm the action" in text or "confirm the proposed values" in text:
            candidates.append(("authorization_false_rejection", "write gate refused: " + text[:120] + " (review whether refusal was correct)"))
        elif isinstance(validation, dict):
            problems = validation.get("problems")
            problems = "; ".join(str(problem) for problem in problems) if isinstance(problems, list) else ""
            candidates.append(("planner_schema", "declared argument/tool shape refused: " + (problems or text)[:120]))
        elif "valid details" in text or "valid tool" in text:
            candidates.append(("planner_schema", "declared argument/tool shape refused: " + text[:120]))
        elif "needs a successful result" in text or "does not match" in text or "cannot invent" in text:
            candidates.append(("binding", "argument/binding check refused: " + text[:120]))
        else:
            candidates.append(("planner_schema", "clarification without tool progress: " + text[:120]))
    if any(row.get("event") in {"speech_admission_rejected", "speech_message_unbound"}
           or row.get("delivery") == "stale_dropped" for row in layers.get("voice_admission_events", [])):
        candidates.append(("fragment_admission", "decoded speech was not admitted"))
    return [{"layer": layer, "evidence": evidence} for layer, evidence in candidates]


def paired_candidates(modes, layers):
    """Cross-mode localization: where the same request stops succeeding.

    text pass -> asr_text fail points at recognition; asr_text pass -> live fail
    points at fragment admission/transport/output. Candidates need human review.
    """
    passed = {mode: modes.get(mode, {}).get("status") == "completed" and modes[mode].get("strict_pass") is True
              for mode in MODES}
    rows = []
    if passed["text"] and not passed["asr_text"]:
        rows.append({"layer": "recognition", "evidence": "faithful text passes; actual ASR text fails"})
    if passed["asr_text"] and not passed["live_audio"]:
        rows.append({"layer": "fragment_admission|transport|synthesis_output",
                     "evidence": "whole ASR text passes; streamed segments fail"})
    return {"strict_pass": passed, "cross_mode": rows,
            "within_mode": {mode: mode_candidates(layers.get(mode, {})) for mode in MODES if not passed[mode]},
            "status": "automatic candidates; review required, not established causes"}


def window_scoring(result, audio, result_path, directory, snapshot, evaluator, metadata, args, strict_pass):
    """Re-score live runs on only the calls the pinned upstream window would read."""
    window = upstream_window(result, audio_duration_seconds(audio))
    if window is None:
        return {"window_strict_pass": None, "upstream_window": "not applicable: no stream clock"}
    summary = {key: window[key] for key in ("window_end", "duration_seconds", "late_call_seconds",
                                               "first_output_signal_in_window", "basis")}
    summary["late_calls"] = len(window["late_calls"])
    if not window["late_calls"]:
        return {"window_strict_pass": strict_pass, "upstream_window": summary}
    windowed = dict(result, actual_tool_calls=window["calls_in_window"], window_filtered=True)
    windowed_path = directory / "inference/result-window.json"
    checkpoint_json(windowed_path, windowed)
    evaluation = evaluate_snapshot(snapshot, evaluator, metadata, windowed_path, directory / "evaluation-window.json",
                                   args.judge_endpoint, args.judge_identity)
    return {"window_strict_pass": evaluation.get("strict", {}).get("passed") is True
            and evaluation.get("status") == "completed", "upstream_window": summary}


def stage_evidence(result, evaluation):
    events = result.get("controller_events", [])
    proposals = []
    for request in result.get("model_requests", []):
        row = {key: deepcopy(request.get(key)) for key in ("request_id", "outcome", "content", "error_type", "started_at", "finished_at")}
        try:
            row["proposed_calls"] = json.loads(request.get("content", "")).get("tool_calls", [])
        except (ValueError, TypeError, AttributeError):
            row["proposed_calls"] = None
        proposals.append(row)
    # No automatic assertion that a safety refusal is false: retain evidence for review.
    return {"raw_transcript": result.get("raw_transcript", result.get("input_transcripts", [])),
        "admitted_transcripts": result.get("admitted_transcripts", []),
        "admitted_transcript_observation": "controller message ledger" if "admitted_transcripts" in result else "unavailable; SDK delivery is not admission",
        "voice_admission_events": [row for row in result.get("voice_events", []) if row.get("event") in
            {"speech_segment_recognition", "speech_admission_rejected", "speech_message_unbound", "empty_speech_resolved",
             "speech_context_retained", "speech_context_refused"}],
        "proposals": proposals,
        "controller_tool_calls": [row for row in events if row.get("action") == "tool_call"],
        "dispatched_calls_and_results": result.get("actual_tool_calls", []),
        "operations": result.get("operations", []),
        "rejections_and_clarifications": [row for row in events if row.get("action") == "clarification_request"],
        "output_text": result.get("transcript"), "output_audio": "inference/spoken.wav" if result.get("transport") == "local LiveKit WebRTC room" else None,
        "model_stage_timings": [{key: row.get(key) for key in ("request_id", "started_at", "finished_at", "timings")} for row in result.get("model_requests", [])],
        "asr_stage_timings": result.get("stt_attempts", []), "synthesis_stage_timings": result.get("tts_requests", []),
        "errors": result.get("errors", []) + ([result["error"]] if result.get("error") else []),
        "metric_labels": evaluation.get("strict"),
        "judge_identity": evaluation.get("judge_identity"), "judge_errors": evaluation.get("infrastructure_error"),
        "root_cause_review": {layer: {"status": "unassessed", "reason": "Metric labels alone do not establish a cause"} for layer in LAYERS}}


async def replay(args):
    """Child receives only literal text and public contract, never expected data."""
    from thread_agent.fdb3 import ControllerBridge, LocalPlanner, load_contract, load_registry
    args.output.mkdir(parents=True, exist_ok=False)
    text = args.replay_text.read_text(encoding="utf-8")
    result = {"status": "running", "mode": args.mode, "qualification": False, "paid_requests": 0,
        "input_sha256": file_hash(args.audio), "replay_text_sha256": file_hash(args.replay_text),
        "raw_transcript": text, "transport": "whole-recording transcript replay; no RTC or TTS",
        "started_at": time.time(), "errors": []}
    planner = bridge = None
    try:
        checkpoint_json(args.output / "result.json", result)
        if not text.strip():
            raise ValueError("Empty transcript cannot be replaced with a guessed instruction")
        planner = LocalPlanner(args.endpoint, args.model, model_journal=args.output / "model-requests.jsonl")
        bridge = ControllerBridge(load_contract(args.contract), load_registry(args.contract), planner)
        bridge.tool_journal = args.output / "tool-calls.jsonl"
        await bridge.start()
        result["transcript"] = await bridge.response(text, timeout=250)
        await bridge.synchronize()
        if any(row.get("outcome") == "error" for row in planner.requests):
            raise RuntimeError("Planner infrastructure/protocol error")
        result["status"] = "completed"
    except BaseException as exc:
        result.update(status="infrastructure_error", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        for component in (bridge, planner):
            if component is not None:
                try:
                    await component.close()
                except BaseException as exc:
                    result["errors"].append("Cleanup " + type(exc).__name__ + ": " + str(exc))
                    result["status"] = "infrastructure_error"
        result.update(finished_at=time.time(), actual_tool_calls=bridge.calls if bridge else [],
            controller_events=bridge.events if bridge else [], voice_events=bridge.voice_events if bridge else [],
            operations=list(bridge.controller.operations.values()) if bridge else [],
            model_requests=planner.requests if planner else [],
            admitted_transcripts=[deepcopy(row) for row in bridge.controller.messages
                                  if row.get("event_type") == "user_speech_chunk"] if bridge else [])
        if bridge and bridge.evidence_errors:
            result["errors"].extend(bridge.evidence_errors)
            result["status"] = "infrastructure_error"
        checkpoint_json(args.output / "result.json", result)


def worker_command(snapshot, mode, args, pair, contract):
    common = ["--audio", str(pair / "input.wav"), "--output", str(pair / mode / "inference"),
              "--contract", str(contract), "--endpoint", args.endpoint, "--model", args.model]
    if mode == "live_audio":
        return [sys.executable, str(snapshot / "scripts/fdb3_audio_worker.py"), *common,
                "--whisper", str(args.whisper.resolve()), "--room"]
    return [sys.executable, str(snapshot / "scripts/fdb3_diagnose_layers.py"), *common,
            "--replay-text", str(pair / ("faithful.txt" if mode == "text" else "actual-asr.txt")), "--mode", mode]


def run_child(command, cwd, log):
    with log.open("w", encoding="utf-8") as handle:
        try:
            return subprocess.run(command, cwd=cwd, stdout=handle, stderr=subprocess.STDOUT, timeout=450).returncode
        except subprocess.TimeoutExpired:
            return 124


def diagnose(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "in_progress", "qualification": False, "paid_requests": 0,
        "exposure": args.exposure, "scenario_group": args.scenario_group,
        "split_claim": "No held-out claim; all three modes are one scenario group",
        "limitations": ["Text replay uses a faithful supplied transcript; fidelity is an author attestation",
            "ASR-text replays all actual live decoded words, including dropped segments, as one final turn",
            "Replay removes transport, interruption timing and synthesis; paired differences are not single-variable causal proof",
            "Local judge and loopback WebRTC do not qualify as organizer/cloud evidence"], "modes": {}}
    checkpoint_json(output / "report.json", report)
    try:
        snapshot, contract, evaluator = output / "source", output / "contract", output / "evaluator"
        sources = {}
        for directory in ("scripts", "participant", "thread_agent"):
            for source in (ROOT / directory).glob("*.py"):
                relative = source.relative_to(ROOT)
                destination = snapshot / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                sources[str(relative)] = file_hash(source)
                shutil.copyfile(source, destination)
                if file_hash(destination) != sources[str(relative)]:
                    raise ValueError("Source changed while freezing diagnostic")
        contract.mkdir()
        for name in ("cascaded_agent.py", "mock_apis.py", "latency_injector.py"):
            shutil.copyfile(args.contract / name, contract / name)
        evaluator.mkdir()
        for name in ("evaluate_pass_rate.py", "evaluate_tool_calls.py", "analyze_tool_latency.py"):
            shutil.copyfile(args.upstream / "v3" / name, evaluator / name)
        shutil.copyfile(args.audio, output / "input.wav")
        shutil.copyfile(args.transcript, output / "faithful.txt")
        shutil.copyfile(args.metadata, output / "expected-metadata.json")
        identity = {"source_sha256": sources, "python": sys.version,
            "planner_prompt_cache": os.environ.get("THREAD_FDB3_PROMPT_CACHE", "0") == "1",
            "planner_guidance": int(os.environ.get("THREAD_FDB3_PLANNER_GUIDANCE", "1")),
            "planner_follow_up": os.environ.get("THREAD_FDB3_FOLLOW_UP"),
            "planner_cache_scope": "scenario", "whisper_prompt": os.environ.get("THREAD_FDB3_WHISPER_PROMPT"), "planner_arg_normalize": os.environ.get("THREAD_FDB3_ARG_NORMALIZE","0")=="1",
            "config": {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()},
            "input_sha256": file_hash(output / "input.wav"), "faithful_transcript_sha256": file_hash(output / "faithful.txt"),
            "evaluator_only_metadata_sha256": file_hash(output / "expected-metadata.json"),
            "model_sha256": file_hash(args.model_file),
            "whisper_sha256": {str(path.relative_to(args.whisper)): file_hash(path) for path in args.whisper.rglob("*") if path.is_file()},
            "contract_sha256": {path.name: file_hash(path) for path in contract.iterdir()},
            "evaluator_sha256": {path.name: file_hash(path) for path in evaluator.iterdir()},
            "dependency_lock_sha256": file_hash(ROOT / "requirements-fdb3.lock")}
        checkpoint_json(output / "identity.json", identity)
        report["identity_sha256"] = file_hash(output / "identity.json")
        for mode in MODES:
            directory = output / mode
            directory.mkdir()
            entry = {"status": "in_progress", "started_at": time.time(), "strict_pass": False}
            report["modes"][mode] = entry
            checkpoint_json(output / "report.json", report)
            result, evaluation = {}, {}
            try:
                if mode == "asr_text":
                    text = actual_asr_text(read_json(output / "live_audio/inference/result.json"))
                    (output / "actual-asr.txt").write_text(text, encoding="utf-8")
                command = worker_command(snapshot, mode, args, output, contract)
                entry.update(command=command, exit_code=run_child(command, contract, directory / "worker.log"))
                result_path = directory / "inference/result.json"
                if result_path.exists():
                    result = read_json(result_path)
                if entry["exit_code"] or result.get("status") != "completed":
                    raise ValueError("Incomplete inference; retain raw journals and failure")
                if result.get("input_sha256") != identity["input_sha256"]:
                    raise ValueError("Wrong input hash")
                verify_tool_trace(result.get("actual_tool_calls"), directory / "inference/tool-calls.jsonl")
                evaluation = evaluate_snapshot(snapshot, evaluator, output / "expected-metadata.json", result_path,
                    directory / "evaluation.json", args.judge_endpoint, args.judge_identity)
                if evaluation.get("status") != "completed":
                    raise ValueError("Incomplete evaluator/judge evidence")
                entry.update(status="completed", strict_pass=evaluation.get("strict", {}).get("passed") is True)
                entry.update(window_scoring(result, output / "input.wav", result_path, directory, snapshot, evaluator,
                                            output / "expected-metadata.json", args, entry["strict_pass"]))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                entry.update(status="infrastructure_error", error_type=type(exc).__name__, error=str(exc))
                if (directory / "evaluation.json").exists():
                    evaluation = read_json(directory / "evaluation.json")
            finally:
                entry["finished_at"] = time.time()
                checkpoint_json(directory / "layers.json", stage_evidence(result, evaluation))
                entry["artifact_sha256"] = {str(path.relative_to(directory)): file_hash(path)
                    for path in directory.rglob("*") if path.is_file()}
                checkpoint_json(output / "report.json", report)
        report["paired_candidates"] = paired_candidates(report["modes"], {
            mode: read_json(output / mode / "layers.json") for mode in MODES if (output / mode / "layers.json").exists()})
        report["status"] = "complete_diagnostic" if all(row["status"] == "completed" for row in report["modes"].values()) else "incomplete_diagnostic"
    except BaseException as exc:
        report.update(status="aborted", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        report["finished_at"] = time.time()
        checkpoint_json(output / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("audio", "output", "contract"):
        parser.add_argument("--" + name, required=True, type=Path)
    for name in ("transcript", "metadata", "upstream", "whisper", "model-file", "replay-text"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8097/v1")
    parser.add_argument("--model", default="local-qwen")
    parser.add_argument("--judge-endpoint")
    parser.add_argument("--judge-identity")
    parser.add_argument("--exposure", choices=("independently_authored", "public_exposed"))
    parser.add_argument("--scenario-group")
    parser.add_argument("--mode", choices=("text", "asr_text"))
    args = parser.parse_args()
    for endpoint in (args.endpoint, args.judge_endpoint):
        if endpoint and (urlparse(endpoint).scheme != "http" or urlparse(endpoint).hostname not in {"localhost", "127.0.0.1", "::1"}):
            parser.error("Only existing loopback services are allowed")
    if args.replay_text:
        if args.mode is None or any((args.metadata, args.transcript, args.upstream, args.judge_endpoint)):
            parser.error("Replay child accepts transcript only, not evaluator inputs")
        asyncio.run(replay(args))
        return 0
    if any(getattr(args, name) is None for name in ("transcript", "metadata", "upstream", "whisper", "model_file", "exposure", "scenario_group")):
        parser.error("Pair requires faithful transcript, evaluator metadata, upstream, Whisper/model assets, exposure and scenario group")
    if bool(args.judge_endpoint) != bool(args.judge_identity):
        parser.error("Judge endpoint and actual identity must be supplied together")
    with campaign_lock(ROOT / ".thread-run"):
        report = diagnose(args)
    return 0 if report["status"] == "complete_diagnostic" else 1


if __name__ == "__main__":
    raise SystemExit(main())
