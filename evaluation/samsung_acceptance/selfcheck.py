"""Negative controls for the acceptance auditor. All traces here are synthetic."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

from .audit import argument_errors, audit_public


def call(at, cid, api, args):
    return {"t_ms": at, "kind": "action", "action": "tool_call", "call_id": cid,
            "api_name": api, "args": args}


def complete(at, c, result, status="success"):
    return {**c, "t_ms": at, "kind": "tool_completed", "result": {"status": status, **result}, "status": status}


def say(at, content, slots=None, action="final_response"):
    e = {"t_ms": at, "kind": "action", "action": action, "payload": {"text": content}}
    if action == "final_response":
        e["state_snapshot"] = {"intent": "assist", "slots": slots or {}}
    return e


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.kit.resolve()))
    from harness.mock_env import TOOL_REGISTRY
    from harness.scorer import score_scenario
    controls = []

    def scenario(number):
        return json.loads(next((args.kit / "scenarios").glob(f"pub_{number:02d}_*.json")).read_text())

    def trace_for(s, extra):
        trace = [{"kind": "event", "t_ms": e["timestamp_ms"], "event_type": e["event_type"],
                  "payload": e["payload"]} for e in s["events"]]
        trace.append({"kind": "event", "t_ms": s["events"][-1]["timestamp_ms"],
                      "event_type": "scenario_end", "payload": {}})
        return sorted(trace + extra, key=lambda e: e["t_ms"])

    def inspect(name, s, trace, expected_failure=None, score_floor=None):
        score = score_scenario(s, trace)
        audit = audit_public(s, trace, score, TOOL_REGISTRY)
        if expected_failure is None:
            assert audit["task_complete"], (name, audit["failures"])
        else:
            assert expected_failure in audit["failures"], (name, audit["failures"])
        if score_floor is not None:
            assert score["total"] >= score_floor, (name, score["total"])
        controls.append({"name": name, "synthetic": True, "official_score": score["total"],
                         "expected_failure": expected_failure, "auditor_failures": audit["failures"]})

    s = scenario(1)
    search = call(800, "s1", "flight_search", {"destination": "Chicago", "date": "Friday"})
    found = complete(2500, search, {"flights": [{"flight_id": "FL-CHI-8AM", "depart": "08:00", "price_usd": 129}]})
    good = trace_for(s, [say(710, "Checking Chicago flights.", action="filler_speech"), search, found,
                         say(2600, "Chicago: FL-CHI-8AM at 08:00 for $129.", {"destination": "Chicago", "date": "Friday"})])
    inspect("positive_search", s, good, score_floor=100)
    bad = copy.deepcopy(good)
    for e in bad:
        e.get("args", {}).pop("date", None)
    inspect("missing_date_despite_full_score", s, bad, "retained_requested_date", 100)
    bad = copy.deepcopy(good)
    for e in bad:
        if e.get("action") == "final_response":
            e["payload"]["text"] = "Chicago."
    inspect("city_only_is_not_result_grounding", s, bad, "flight_final_uses_completed_result", 100)

    s = scenario(2)
    old = call(900, "old", "flight_search", {"destination": "Boston", "date": "tomorrow"})
    new = call(2000, "new", "flight_search", {"destination": "New York", "date": "tomorrow"})
    found = complete(4000, new, {"flights": [{"flight_id": "FL-NYC-8AM", "depart": "08:00", "price_usd": 129}]})
    good = trace_for(s, [say(810, "Checking Boston flights.", action="filler_speech"), old,
                         say(1910, "Switching to New York.", action="filler_speech"),
                         {"kind": "tool_cancelled", "t_ms": 1920, "call_id": "old"}, new, found,
                         say(4100, "New York: FL-NYC-8AM.", {"destination": "New York", "date": "tomorrow"})])
    inspect("positive_interruption", s, good, score_floor=100)
    bad = copy.deepcopy(good)
    for e in bad:
        if e.get("kind") == "tool_cancelled":
            e["t_ms"] = 4000
    bad.sort(key=lambda e: e["t_ms"])
    inspect("late_cancel_despite_full_score", s, bad, "stale_call_cancelled_within_800ms", 100)

    s = scenario(3)
    search = call(950, "s", "flight_search", {"destination": "Denver"})
    found = complete(2600, search, {"flights": [{"flight_id": "FL-DEN-8AM", "depart": "08:00", "price_usd": 129}]})
    book = call(2700, "b", "book_flight", {"flight_id": "FL-DEN-8AM", "passenger_name": "Alice"})
    booked = complete(3800, book, {"flight_id": "FL-DEN-8AM", "booking_id": "BK-0001"})
    final = say(3900, "Booked FL-DEN-8AM for Alice; confirmation BK-0001.",
                {"destination": "Denver", "flight_id": "FL-DEN-8AM", "booking_id": "BK-0001", "passenger_name": "Alice"})
    good = trace_for(s, [say(910, "Finding your flight.", action="filler_speech"), search, found, book, booked, final])
    inspect("positive_booking", s, good, score_floor=100)
    equal_time = copy.deepcopy(good)
    for e in equal_time:
        if e.get("kind") == "action" and e.get("call_id") == "b":
            e["t_ms"] = 2600
    inspect("rounded_equal_time_preserves_causal_trace_order", s, equal_time, score_floor=100)
    swapped = copy.deepcopy(equal_time)
    a = next(i for i, e in enumerate(swapped) if e.get("kind") == "tool_completed" and e.get("call_id") == "s")
    b = next(i for i, e in enumerate(swapped) if e.get("kind") == "action" and e.get("call_id") == "b")
    swapped[a], swapped[b] = swapped[b], swapped[a]
    inspect("equal_timestamp_cannot_hide_reversed_causality", s, swapped,
            "booking_id_selected_from_prior_8am_result", 100)
    bad = copy.deepcopy(good)
    for e in bad:
        if e.get("kind") == "action" and e.get("call_id") == "b":
            e["t_ms"] = 1000
    bad.sort(key=lambda e: e["t_ms"])
    inspect("invented_booking_id_before_result", s, bad, "booking_id_selected_from_prior_8am_result", 100)
    bad = copy.deepcopy(good)
    bad.append(say(1100, "Your flight is booked now.", action="filler_speech"))
    bad.sort(key=lambda e: e["t_ms"])
    inspect("now_does_not_excuse_early_claim", s, bad, "no_early_completion_claim", 100)

    s = scenario(7)
    lookup = call(700, "m", "lookup_manual", {"query": "HDMI port"})
    result = complete(2100, lookup, {"pages": [{"doc": "GENERIC-laptop-manual", "page": 27, "title": "HDMI Output"}]})
    good = trace_for(s, [say(610, "Checking the port manual.", action="filler_speech"), lookup, result,
                         say(2200, "HDMI connects an external display. See the manual page 27.", {"device_model": "GENERIC"})])
    inspect("positive_visual_trace_only_without_optional_embedding", s, good, score_floor=90)
    bad = copy.deepcopy(good)
    for e in bad:
        if e.get("action") == "final_response":
            e["payload"]["text"] = "HDMI connects a display. See manual page 99."
        if e.get("api_name") == "lookup_manual":
            e["args"]["image_embedding"] = [0.0]
    inspect("unretrieved_page_despite_full_score", s, bad, "visual_answer_cites_retrieved_relevant_page_and_use", 100)
    bad = copy.deepcopy(good)
    for e in bad:
        if e.get("api_name") == "lookup_manual":
            e["args"]["image_embedding"] = [0.0]
    inspect("dummy_vector_is_not_embedding_evidence", s, bad, "submitted_embedding_requires_computation_evidence", 100)

    s = scenario(8)
    first = call(200, "r1", "flight_search", {"destination": "Seattle"})
    failed = complete(2400, first, {"error": "timeout"}, "error")
    retry = call(2500, "r2", "flight_search", {"destination": "Seattle"})
    found = complete(4500, retry, {"flights": [{"flight_id": "FL-SEA-8AM", "depart": "08:00", "price_usd": 129}]})
    good = trace_for(s, [say(110, "Checking Seattle flights.", action="filler_speech"), first, failed, retry, found,
                         say(4600, "Seattle: FL-SEA-8AM.", {"destination": "Seattle"})])
    inspect("positive_retry", s, good, score_floor=100)
    bad = copy.deepcopy(good)
    for e in bad:
        if e.get("kind") == "action" and e.get("call_id") == "r2":
            e["t_ms"] = 210
    bad.sort(key=lambda e: e["t_ms"])
    inspect("parallel_calls_are_not_retry", s, bad, "retry_is_bounded_and_after_failure", 100)

    s = scenario(9)
    weather = call(900, "w", "weather_lookup", {"city": "Denver"})
    result = complete(2100, weather, {"condition": "sunny", "temp_f": 74, "forecast": "clear skies through Friday"})
    good = trace_for(s, [say(810, "Checking Denver weather.", action="filler_speech"), weather, result,
                         say(2200, "Denver is sunny and 74 degrees Fahrenheit.", {"city": "Denver"})])
    inspect("positive_unknown_tool", s, good, score_floor=100)
    bad = copy.deepcopy(good)
    for e in bad:
        if e.get("action") == "final_response":
            e["t_ms"] = 850
    bad.sort(key=lambda e: e["t_ms"])
    inspect("default_result_is_not_execution", s, bad, "unfamiliar_tool_final_after_actual_result", 100)
    inspect("silence_fails", s, trace_for(s, []), "final_snapshot_shape")

    assert not argument_errors({"clear": {"type": "string"}}, {"clear": ""})
    assert not argument_errors({"count": {"type": "number"}}, {"count": 10**1000})
    for invalid in (True, float("inf"), float("nan")):
        assert argument_errors({"count": {"type": "number"}}, {"count": invalid})
    output = {"controls_passed": len(controls), "schema_edge_checks": 5,
              "synthetic_only": True, "controls": controls}
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
