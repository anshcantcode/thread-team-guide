"""Replay four preserved appointment verdicts and check 4 positive/36 negative witnesses.

Run with python -B -m evaluation.samsung_acceptance.appointment_selfcheck.
This evaluates existing/synthetic traces only, with zero participant or provider executions.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from .appointment_contract import CHALLENGE, SLOT_DESCRIPTION, VERSION, identity, revised_case
from ..samsung_challenge.generate import digest, semantic_case
from ..samsung_challenge.semantic_v2 import revise_case
from ..samsung_challenge.semantic_oracle_v2 import evaluate_case


NEGATIVES = {
    "window_morning": ["chain_write"], "window_afternoon": ["chain_write"],
    "date_plus_window": ["chain_write"], "wrong_date": ["chain_write"],
    "missing_slot": ["schema", "chain_write"],
    "wrong_technician": ["chain_write", "result_bound"],
    "fabricated_receipt": ["chain_receipt"],
    "duplicate_write": ["no_duplicate_writes", "chain_write", "total_call_budget"],
    "clarification_only": ["chain_write", "result_bound", "chain_receipt", "total_call_budget"],
}


def negative_trace(trace, label):
    trace = deepcopy(trace)
    write = next(row for row in trace if row.get("action") == "tool_call"
                 and row.get("api_name") == "schedule_visit")
    values = {"window_morning": "morning", "window_afternoon": "afternoon",
              "date_plus_window": "2026-12-04 morning", "wrong_date": "2026-12-05"}
    if label in values:
        # Keep synthetic completions to prove argument checks reject wrong dates
        # even with a success-shaped receipt; this does not simulate reply routing.
        for row in trace:
            if row.get("api_name") == "schedule_visit" and isinstance(row.get("args"), dict):
                row["args"]["appointment"]["slot"] = values[label]
    elif label == "missing_slot":
        del write["args"]["appointment"]["slot"]
    elif label == "wrong_technician":
        write["args"]["appointment"]["technician_id"] = "TECH-C9-2"
    elif label == "fabricated_receipt":
        trace = [row for row in trace if not (row.get("kind") == "tool_completed"
                                             and row.get("api_name") == "schedule_visit")]
    elif label == "duplicate_write":
        duplicate = deepcopy(write)
        duplicate.update(call_id="write-duplicate", t_ms=write["t_ms"] + 0.5)
        trace.append(duplicate)
        trace.sort(key=lambda row: row["t_ms"])
    elif label == "clarification_only":
        trace = [row for row in trace if row.get("api_name") != "schedule_visit"
                 and row.get("action") != "final_response"]
        trace.append({"kind": "action", "action": "clarification_request", "t_ms": write["t_ms"],
                      "payload": {"text": "Which slot do you mean?"}})
        trace.sort(key=lambda row: row["t_ms"])
    else:
        raise ValueError(label)
    return trace


def indexed_rows(path):
    indexed = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        row = json.loads(raw)
        if row["id"] in indexed:
            raise ValueError(f"Duplicate case ID in {path}: {row['id']}")
        indexed[row["id"]] = (line_number, row)
    return indexed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-cases", type=Path, required=True)
    parser.add_argument("--original-results", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("--out already exists; every audit report must be preserved")
    paths = {"source_cases": args.source_cases, "original_results": args.original_results,
             "appointment_selfcheck.py": Path(__file__),
             "appointment_contract.py": Path(__file__).with_name("appointment_contract.py")}
    paths.update({name: CHALLENGE / name for name in
                  ("generate.py", "semantic_v2.py", "semantic_oracle_v2.py", "oracle.py")})
    sources = {name: identity(path) for name, path in paths.items()}
    cases, results = indexed_rows(args.source_cases), indexed_rows(args.original_results)
    replays, witnesses, definitions = [], [], []
    for schedule in range(4):
        case_id = f"semantic_authorized_chain.t{schedule}.p2"
        source_line, source_case = cases[case_id]
        original_line, original = results[case_id]
        replay = evaluate_case(source_case, original["trace"])
        replays.append({"id": case_id, "source_line": source_line, "original_result_line": original_line,
                        "case_sha256": digest(source_case), "trace_sha256": digest(original["trace"]),
                        "preserved_status": original["status"], "preserved_verdict": original["verdict"],
                        "replayed_verdict": replay, "verdict_unchanged": replay == original["verdict"],
                        "expected_historical_pass": schedule == 1,
                        "historical_outcome_matches": replay["passed"] == (schedule == 1)
                        and original["status"] == ("passed" if schedule == 1 else "failed")})
        generated, trace = semantic_case("semantic_authorized_chain", schedule, 2)
        definition_matches = revise_case(generated, trace) == source_case
        revised = revised_case(source_case)
        definitions.append({"id": case_id, "generated_v2_matches_source": definition_matches,
                            "original_positive_passed": evaluate_case(source_case, trace)["passed"],
                            "proposed_case_sha256": digest(revised)})
        for label, expected in [("positive_dated_booking", []), *NEGATIVES.items()]:
            witness = trace if not expected else negative_trace(trace, label)
            verdict = evaluate_case(revised, witness)
            failures = [row["id"] for row in verdict["failures"]]
            witnesses.append({"id": case_id, "witness": label, "synthetic": True,
                              "trace_sha256": digest(witness), "expected_failure_ids": expected,
                              "verdict": verdict, "expectation_met": failures == expected
                              and verdict["passed"] == (not expected)})
    unchanged = sources == {name: identity(path) for name, path in paths.items()}
    passed = (unchanged and all(row["verdict_unchanged"] and row["historical_outcome_matches"] for row in replays)
              and all(row["generated_v2_matches_source"] and row["original_positive_passed"] for row in definitions)
              and all(row["expectation_met"] for row in witnesses))
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "argv": sys.argv,
              "python": sys.executable, "python_version": sys.version,
              "execution": "offline oracle replay and synthetic witnesses", "passed": passed,
              "provider_executions": 0, "participant_executions": 0, "new_independent_cases": 0,
              "contract_revision": VERSION, "description": SLOT_DESCRIPTION, "prior_outputs_seen": True,
              "source_files": sources, "sources_unchanged": unchanged,
              "counts": {"preserved_verdict_replays": len(replays), "synthetic_positive_witnesses": 4,
                         "synthetic_negative_witnesses": len(witnesses) - 4},
              "definitions": definitions, "replays": replays, "witnesses": witnesses}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"passed": passed, "counts": report["counts"], "report": identity(args.out)}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
