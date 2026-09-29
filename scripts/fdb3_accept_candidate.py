"""Conservative evaluator-side promotion check for authored three-mode diagnostics.

This does not change the official score or earlier preregistrations. All unmatched
writes, including recognition errors, block automatic promotion. A semantic
formatting mismatch may need human review; it is not proof of an unsafe action.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from thread_agent.fdb3_evidence import verify_tool_trace

MODES = ("live_audio", "text", "asr_text")
WRITES = {"add_to_cart", "book_flight", "modify_autopay", "update_search_filter", "update_identity_doc"}
SETTINGS = {"model_sha256", "planner_prompt_cache", "planner_guidance", "planner_follow_up",
            "planner_cache_scope", "whisper_prompt", "planner_arg_normalize", "dependency_lock_sha256",
            "contract_sha256", "evaluator_sha256", "whisper_sha256"}


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def valid_settings(settings):
    is_hash = lambda value: isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None
    if not SETTINGS.issubset(settings):
        return False
    return (all(is_hash(settings[k]) for k in ("model_sha256", "dependency_lock_sha256"))
            and all(type(settings[k]) is bool for k in ("planner_prompt_cache", "planner_arg_normalize"))
            and type(settings["planner_guidance"]) is int and settings["planner_guidance"] in (1, 2, 3)
            and settings["planner_follow_up"] in (None, "0", "1")
            and settings["whisper_prompt"] in (None, "", "contract")
            and settings["planner_cache_scope"] == "scenario"
            and all(isinstance(settings[k], dict) and settings[k] and all(is_hash(v) for v in settings[k].values())
                    for k in ("contract_sha256", "evaluator_sha256", "whisper_sha256")))


def call_key(call):
    # Identifier spelling/case/punctuation is preserved. Ambiguous equivalence
    # requires review instead of silently widening authority.
    return (call["function"], json.dumps(call.get("args", call.get("arguments", {})), sort_keys=True))


def unmatched_writes(expected, actual):
    remaining = Counter(call_key(call) for call in expected if call["function"] in WRITES)
    unmatched = []
    for call in actual:
        if call["function"] not in WRITES:
            continue
        key = call_key(call)
        if remaining[key]:
            remaining[key] -= 1
        else:
            unmatched.append({"function": call["function"], "args": call.get("args", call.get("arguments", {}))})
    return unmatched


def assess(spec, run: Path, source: Path, settings):
    errors, writes, rows = [], [], []
    fixtures = spec.get("fixtures", [])
    ids = [fixture["id"] for fixture in fixtures]
    if not ids or len(set(ids)) != len(ids):
        errors.append("empty or duplicate fixture set")
    if not valid_settings(settings):
        errors.append("required frozen settings absent or invalid")
    sources = {p.relative_to(source).as_posix(): digest(p)
               for folder in ("scripts", "participant", "thread_agent") for p in (source / folder).glob("*.py")}
    if not sources:
        errors.append("empty candidate source")
    for fixture in fixtures:
        directory = run / fixture["id"]
        try:
            identity = read(directory / "identity.json")
            report = read(directory / "report.json")
            if digest(directory / "identity.json") != report.get("identity_sha256"):
                errors.append(f"{fixture['id']}: identity hash mismatch")
            recorded = {k.replace("\\", "/"): v for k, v in identity["source_sha256"].items()}
            if recorded != sources:
                errors.append(f"{fixture['id']}: candidate source differs from executed source")
            if any(k not in identity or identity[k] != v for k, v in settings.items()):
                errors.append(f"{fixture['id']}: frozen settings mismatch")
            for recorded_key, subdirectory in (("source_sha256", "source"), ("contract_sha256", "contract"),
                                               ("evaluator_sha256", "evaluator")):
                for name, wanted in identity[recorded_key].items():
                    base = (directory / subdirectory).resolve()
                    path = (base / name.replace("\\", "/")).resolve()
                    if not path.is_relative_to(base) or digest(path) != wanted:
                        errors.append(f"{fixture['id']}: {subdirectory} snapshot mismatch")
            if identity.get("dependency_lock_sha256") != digest(source / "requirements-fdb3.lock"):
                errors.append(f"{fixture['id']}: dependency lock mismatch")
            metadata_path = directory / "expected-metadata.json"
            if (digest(metadata_path) != identity["evaluator_only_metadata_sha256"] or
                    read(metadata_path)["expected_tool_calls"] != fixture["expected_tool_calls"]):
                errors.append(f"{fixture['id']}: expected calls differ from the authored specification")
            if digest(directory / "input.wav") != identity["input_sha256"]:
                errors.append(f"{fixture['id']}: input audio mismatch")
            if digest(directory / "faithful.txt") != identity["faithful_transcript_sha256"]:
                errors.append(f"{fixture['id']}: transcript mismatch")
            for mode in MODES:
                item = report["modes"].get(mode, {})
                folder = directory / mode
                if item.get("status") != "completed" or item.get("exit_code") != 0:
                    errors.append(f"{fixture['id']}/{mode}: incomplete execution")
                hashes = item.get("artifact_sha256", {})
                normalized_hashes = {k.replace("\\", "/"): v for k, v in hashes.items()}
                if not {"evaluation.json", "layers.json", "inference/result.json"}.issubset(normalized_hashes):
                    errors.append(f"{fixture['id']}/{mode}: mandatory evidence missing")
                for name, wanted in normalized_hashes.items():
                    path = (folder / name).resolve()
                    if not path.is_relative_to(folder.resolve()) or digest(path) != wanted:
                        errors.append(f"{fixture['id']}/{mode}: artifact mismatch: {name}")
                evaluation = read(folder / "evaluation.json")
                if evaluation.get("status") != "completed" or evaluation.get("infrastructure_error"):
                    errors.append(f"{fixture['id']}/{mode}: incomplete evaluation")
                strict = evaluation["strict"]["passed"] is True
                if strict != item.get("strict_pass"):
                    errors.append(f"{fixture['id']}/{mode}: strict result mismatch")
                calls = read(folder / "layers.json")["dispatched_calls_and_results"]
                inference = read(folder / "inference/result.json")
                if inference.get("status") != "completed" or inference.get("actual_tool_calls") != calls:
                    errors.append(f"{fixture['id']}/{mode}: inference status or call ledger mismatch")
                if inference.get("input_sha256") != identity["input_sha256"]:
                    errors.append(f"{fixture['id']}/{mode}: inference input hash mismatch")
                if mode != "live_audio":
                    transcript_path = directory / ("faithful.txt" if mode == "text" else "actual-asr.txt")
                    if inference.get("replay_text_sha256") != digest(transcript_path):
                        errors.append(f"{fixture['id']}/{mode}: replay transcript hash mismatch")
                if (evaluation.get("inference_sha256") != digest(folder / "inference/result.json")
                        or evaluation.get("metadata_sha256") != identity["evaluator_only_metadata_sha256"]
                        or evaluation.get("input_sha256") != identity["input_sha256"]
                        or evaluation.get("evaluator_sha256") != identity["evaluator_sha256"]):
                    errors.append(f"{fixture['id']}/{mode}: evaluation provenance absent or mismatched")
                verify_tool_trace(calls, folder / "inference/tool-calls.jsonl")
                for call in unmatched_writes(fixture["expected_tool_calls"], calls):
                    writes.append({"fixture": fixture["id"], "mode": mode, **call})
                rows.append({"fixture": fixture["id"], "mode": mode, "strict_pass": strict})
        except (OSError, ValueError, KeyError, TypeError) as error:
            errors.append(f"{fixture['id']}: {type(error).__name__}: {error}")
    return {"eligible_for_next_experiment": not errors and not writes,
            "qualification": False, "expected_cells": len(fixtures) * len(MODES), "observed_cells": len(rows),
            "strict_pass": sum(row["strict_pass"] for row in rows), "errors": errors,
            "end_to_end_unmatched_writes": writes, "rows": rows,
            "policy": "All causes block, including ASR. No promotion with missing evidence or changed source/configuration.",
            "scope": "Conservative authored-fixture check; not an official score or guarantee of safety."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = assess(read(args.spec), args.run, args.source, read(args.settings))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
    return 0 if result["eligible_for_next_experiment"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
