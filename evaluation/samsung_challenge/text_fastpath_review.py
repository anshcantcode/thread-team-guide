"""Bounded literal-boundary review of the complete flight-search shortcut.

Pure decision probes only: no provider, model, or external tool is called.
"""
import argparse
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import sys


def probes():
    positive = [
        ("novel_single_literal", "Find flights to Veloria", "Veloria"),
        ("literal_case_preserved", "Please find me a flight to NeRaVeL.", "NeRaVeL"),
        ("quoted_multiword_literal", 'Search for flights to "North Veloria" please.', "North Veloria"),
        ("unicode_literal", "Find flights to Rašnova.", "Rašnova"),
        ("internal_apostrophe_literal", "Find flights to D'Avora.", "D'Avora"),
        ("internal_hyphen_literal", "Find flights to Norra-Sel.", "Norra-Sel"),
        ("temporal_prefix_is_not_a_temporal_word", "Find flights to Maybrook.", "Maybrook"),
        ("lowercase_literal", "find flights to veloria", "veloria"),
    ]
    negative = [
        ("relative_date", "Find flights to Veloria tomorrow"),
        ("calendar_date", "Find flights to Veloria on 2027-04-12"),
        ("departure_time", "Find flights to Veloria before noon"),
        ("budget", "Find flights to Veloria under 300"),
        ("cheap_modifier", "Find cheap flights to Veloria"),
        ("nonstop_modifier", "Find nonstop flights to Veloria"),
        ("return_modifier", "Find return flights to Veloria"),
        ("passenger_constraint", "Find flights to Veloria for two adults"),
        ("origin_is_not_destination", "Find flights from Veloria"),
        ("unquoted_multiword", "Find flights to North Veloria"),
        ("explicit_booking_chain", "Find flights to Veloria and book one"),
        ("condition", "Find flights to Veloria if refundable"),
        ("negation", "Do not find flights to Veloria"),
        ("correction", "Find flights to Veloria, not Neravel"),
        ("whole_request_quoted", '"Find flights to Veloria"'),
        ("quoted_destination_with_extra_meaning", 'Find flights to "North Veloria" tomorrow'),
        ("reserved_word_inside_quoted_candidate", 'Find flights to "North Tomorrow"'),
        ("second_line_constraint", "Find flights to Veloria.\nKeep my existing budget."),
        ("reported_request", "They said find flights to Veloria"),
        ("hyphenated_deictic_reference", "Find flights to you-know-where"),
        ("possessive_deictic_reference", "Find flights to mom's"),
    ]
    rows = [{"probe": name, "text": text, "expected_destination": destination} for name, text, destination in positive]
    rows.extend({"probe": name, "text": text, "expected_destination": None} for name, text in negative)
    rows.extend({"probe": "deictic_" + word, "text": "Find flights to " + word, "expected_destination": None}
                for word in ("home", "there", "anywhere", "elsewhere", "abroad", "somewhere", "wherever", "anyplace"))
    return rows


def context(text):
    return {"revision": 1, "current_turn_start": 0, "state": {"intent": "", "slots": {}},
            "actions": [], "tool_results": [], "observations": [],
            "messages": [{"message_index": 0, "revision": 1, "event_type": "user_speech_chunk",
                          "payload": {"text": text, "end_of_turn": True}}],
            "tools": {"flight_search": {"kind": "read_only", "description": "Search available flights by destination.",
                                        "args": {"destination": {"type": "string", "required": True},
                                                 "date": {"type": "string", "required": False}}}}}


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
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    sys.path.insert(0, str(root))
    package = importlib.import_module("participant")
    package.__path__.append(str(args.controller.resolve() / "participant"))
    module = importlib.import_module("participant.planner")
    assert Path(module.__file__).resolve().is_relative_to(root)
    results = []
    for row in probes():
        ctx = context(row["text"])
        original = deepcopy(ctx)
        error = None
        try:
            decision = module._simple_flight_search(ctx)
        except Exception as exc:
            decision = None
            error = {"type": type(exc).__name__, "message": str(exc)}
        checks = {"context_not_mutated": ctx == original, "no_exception": error is None}
        if row["expected_destination"] is None:
            checks["whole_request_deferred"] = decision is None
        else:
            calls = decision.get("tool_calls", []) if isinstance(decision, dict) else []
            checks["literal_only_read"] = len(calls) == 1 and calls[0].get("api_name") == "flight_search" and calls[0].get("args") == {"destination": row["expected_destination"]}
            checks["literal_slot_retained"] = isinstance(decision, dict) and decision.get("slots") == {"destination": row["expected_destination"]}
            checks["no_write_or_continuation_grant"] = all(not call.get("authorization") and not call.get("after_result") for call in calls)
            checks["no_pre_result_final"] = isinstance(decision, dict) and decision.get("response") is None
        results.append({**row, "checks": checks, "passed": all(checks.values()), "decision": decision, "error": error})
    after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    shared_schema = sys.modules.get("participant.schema")
    report = {"scope": "Thirty-seven bounded pure-decision grammar probes: eight novel literal positives and twenty-nine meaningful near misses. Not new frozen cases or semantic/model-accuracy evidence.",
              "candidate": str(root), "source_sha256": before, "sources_unchanged": before == after,
              "shared_schema_path": shared_schema.__file__ if shared_schema else None,
              "shared_schema_sha256": hashlib.sha256(Path(shared_schema.__file__).read_bytes()).hexdigest() if shared_schema else None,
              "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "provider_calls": 0,
              "external_service_calls": 0, "passed": sum(row["passed"] for row in results), "total": len(results), "results": results}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes((json.dumps(report, indent=2) + "\n").encode("utf-8"))
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, indent=2))
    for row in results:
        if not row["passed"]:
            print(json.dumps(row))
    raise SystemExit(0 if before == after and report["passed"] == report["total"] else 1)


if __name__ == "__main__":
    main()
