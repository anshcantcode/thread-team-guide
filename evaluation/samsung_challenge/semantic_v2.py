"""Freeze corrected semantic revisions; does not add independent case counts."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from .generate import ROOT, canon, digest, semantic_case
from .semantic_oracle_v2 import evaluate_case, expanded

FAMILIES = ("semantic_novel_schema", "semantic_quoted_write", "semantic_multicorrection", "semantic_authorized_chain", "semantic_result_injection")
VERSION = "2026-09-21.semantic-v2"


def revise_case(original, witness):
    case = deepcopy(original)
    case["version"] = VERSION
    case["supersedes"] = {"version": original["version"], "case_sha256": digest(original), "same_case_id": original["id"]}
    calls = [row for row in witness if row.get("kind") == "action" and row.get("action") == "tool_call"]
    # Reply data/delays remain the same. Route by actual arguments, not an
    # injected planner's assumed global call ordering.
    for reply in case["replies"]:
        same_api = [call for call in calls if call["api_name"] == reply["api_name"]]
        reply["match_args"] = deepcopy(same_api[reply["call_index"]]["args"])
        reply.pop("call_index")
    if any(rule["id"] == "grounded_read" for rule in case["oracle"]):
        grounded = next(rule for rule in case["oracle"] if rule["id"] == "grounded_read")
        parts = grounded.pop("path").split(".")
        parts[-2] = "*"
        grounded.update(op="grounded_any_option", paths=[".".join(parts)])
    if case["family"] == "semantic_multicorrection":
        invalid = {"prompt_cancel", "second_cancel", "no_abandoned_target", "no_middle_target", "no_stale_final", "total_call_budget"}
        case["oracle"] = [rule for rule in case["oracle"] if rule["id"] not in invalid]
        corrections = [step["event"] for step in case["steps"] if step["event"]["event_type"] == "interruption"]
        for index, (call, event) in enumerate(zip(calls[:-1], corrections)):
            selector = {"kind": "action", "action": "tool_call", "api_name": call["api_name"], "args": deepcopy(call["args"])}
            anchor = {"kind": "event", "event_type": event["event_type"], "payload": deepcopy(event["payload"])}
            case["oracle"].extend([
                {"id": f"obsolete_{index}_optional_once", "op": "count", "select": selector, "min": 0, "max": 1},
                {"id": f"obsolete_{index}_cancel_if_pending", "op": "cancel_if_pending", "call": selector, "anchor": anchor, "within_ms": 800},
                {"id": f"obsolete_{index}_never_reissued", "op": "no_calls_after_event", "call": selector, "anchor": anchor},
            ])
        last = corrections[-1]
        anchor = {"kind": "event", "event_type": last["event_type"], "payload": deepcopy(last["payload"])}
        grounding = next(rule for rule in case["oracle"] if rule["id"] == "grounded_read")
        forbidden = [value for reply in case["replies"][:-1] for delivery in reply["deliveries"]
                     for path in grounding["paths"] for value in expanded(delivery["result"], path) if isinstance(value, str)]
        case["oracle"].extend([
            {"id": "total_call_budget", "op": "count", "select": {"kind": "action", "action": "tool_call"}, "min": 1, "max": 3},
            {"id": "only_stated_constraints", "op": "allowed_calls", "allowed": [{"api_name": c["api_name"], "args": deepcopy(c["args"])} for c in calls]},
            {"id": "latest_only_evidence", "op": "no_stale_option_after_event", "anchor": anchor, "forbidden_values": forbidden},
        ])
    return case


def cases():
    for family in FAMILIES:
        for schedule in range(4):
            for profile in range(4):
                original, witness = semantic_case(family, schedule, profile)
                yield revise_case(original, witness), witness


def freeze(out):
    rows = []
    for case, witness in cases():
        verdict = evaluate_case(case, witness)
        if not verdict["passed"]:
            raise ValueError((case["id"], verdict["failures"]))
        rows.append(case)
    files = {partition + ".jsonl": "".join(canon(c) + "\n" for c in rows if c["partition"] == partition).encode("utf-8") for partition in ("development", "holdout")}
    existing = json.loads((out / "FREEZE.json").read_text()) if (out / "FREEZE.json").exists() else {}
    manifest = {"version": VERSION, "frozen_at_utc": existing.get("frozen_at_utc", datetime.now(timezone.utc).isoformat()),
                "revisions_not_new_cases": True, "development_rows": 60, "holdout_rows": 20, "new_independent_cases": 0,
                "prior_freeze_sha256": hashlib.sha256((ROOT / "frozen/FREEZE.json").read_bytes()).hexdigest(),
                "user_stimuli_changed": False, "provider_model_outputs_seen_before_revision": False,
                "changes": ["Arguments route reply records instead of a required global call sequence.",
                            "Unconstrained read answers may identify any actual returned option.",
                            "Obsolete calls are optional and require cancellation only if actually pending.",
                            "Actual event anchors protect correction order and latest-result evidence.",
                            "Explicitly selected write chains retain their original exact-selection obligations."],
                "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in ("semantic_v2.py", "semantic_oracle_v2.py", "semantic_preflight.py", "oracle.py", "generate.py")},
                "files": {name: {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)} for name, raw in files.items()}}
    files["FREEZE.json"] = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    out.mkdir(parents=True, exist_ok=True)
    for name, raw in files.items():
        if (out / name).exists() and (out / name).read_bytes() != raw:
            raise ValueError("Refusing to overwrite existing semantic revision: " + str(out / name))
    for name, raw in files.items():
        (out / name).write_bytes(raw)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "semantic-v2")
    freeze(parser.parse_args().out)
