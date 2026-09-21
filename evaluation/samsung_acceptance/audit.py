"""Audit *public evaluation traces*, not participant decisions.

The unchanged official score is retained separately. Public expectations below
are deliberately confined to evaluation; this module must never be packaged as
participant code. An automated text check is evidence of a bounded obligation,
not a general semantic judge or proof that a model understood the input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

SPOKEN = {"filler_speech", "clarification_request", "final_response"}


def text(entry: dict) -> str:
    return str(entry.get("payload", {}).get("text", "")).strip().lower()


def normalized(value: Any) -> str:
    return str(value).strip().lower()


def argument_errors(spec: dict, args: Any, path: str = "args") -> list[str]:
    """Stricter than the kit's deliberately shallow mock argument validator."""
    errors = []
    if not isinstance(args, dict):
        return [f"{path} is not an object"]
    for name in args.keys() - spec.keys():
        errors.append(f"{path}.{name} is undeclared")
    for name, rule in spec.items():
        key = f"{path}.{name}"
        if name not in args:
            if rule.get("required"):
                errors.append(f"{key} is required")
            continue
        value = args[name]
        expected = rule.get("type")
        valid = {
            "string": isinstance(value, str),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool)
                      and (not isinstance(value, float) or math.isfinite(value)),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
        }.get(expected, True)
        if not valid:
            errors.append(f"{key} is not a valid {expected}")
            continue
        if "enum" in rule and value not in rule["enum"]:
            errors.append(f"{key} is outside enum")
        if expected == "object":
            errors.extend(argument_errors(rule.get("properties", {}), value, key))
        if expected == "array" and rule.get("items"):
            item_rule = rule["items"]
            item_rule = {"type": item_rule} if isinstance(item_rule, str) else item_rule
            for index, item in enumerate(value):
                errors.extend(argument_errors({str(index): item_rule}, {str(index): item}, key))
    return errors


def audit_public(scenario: dict, trace: list[dict], score: dict,
                 registry: dict, media_evidence: list[dict] | None = None,
                 media_root: Path | None = None) -> dict:
    """Return check-level evidence; no official scores or trace entries are changed."""
    sid = scenario["scenario_id"]
    checks = []
    positions = {id(entry): index for index, entry in enumerate(trace)}

    def before(source, target):
        # The official clock rounds timestamps; two distinct ordered entries can
        # share a timestamp. Trace order is necessary to establish causality.
        return positions[id(source)] < positions[id(target)] and source["t_ms"] <= target["t_ms"]

    def check(name, passed, detail, group="mandatory"):
        checks.append({"id": name, "status": "unverified" if passed is None else
                       "pass" if passed else "fail", "group": group, "detail": detail})

    actions = [e for e in trace if e.get("kind") == "action"]
    calls = [e for e in actions if e.get("action") == "tool_call"]
    finals = [e for e in actions if e.get("action") == "final_response"]
    speech = [e for e in actions if e.get("action") in SPOKEN]
    completions = [e for e in trace if e.get("kind") == "tool_completed"]
    successes = [e for e in completions if e.get("status") == "success"]
    schemas = {**registry, **scenario.get("tool_manifest", {})}
    issues = [e for e in trace if e.get("kind") in {"protocol_error", "agent_crash"}
              or (e.get("kind") == "agent_setup" and e.get("error"))]
    check("runtime_and_protocol", bool(trace) and not issues, issues)
    ids = [c.get("call_id") for c in calls]
    check("unique_explicit_call_ids", all(isinstance(cid, str) and cid and
          not cid.startswith("auto_") for cid in ids) and len(ids) == len(set(ids)), ids)
    invalid = []
    for c in calls:
        api = c.get("api_name")
        errs = ["tool absent from manifest"] if api not in schemas else argument_errors(
            schemas[api].get("args", {}), c.get("args"))
        if errs:
            invalid.append({"call_id": c.get("call_id"), "errors": errs})
    check("declared_tools_and_exact_argument_types", not invalid, invalid)
    check("final_snapshot_shape", bool(finals) and all(
        isinstance(e.get("state_snapshot"), dict)
        and isinstance(e["state_snapshot"].get("intent"), str)
        and bool(e["state_snapshot"]["intent"].strip())
        and isinstance(e["state_snapshot"].get("slots"), dict) for e in finals),
        [e.get("state_snapshot") for e in finals])
    check("no_abandoned_calls", not any(e.get("kind") == "tool_abandoned" for e in trace),
          [e for e in trace if e.get("kind") == "tool_abandoned"])
    for cp in score.get("breakdown", {}).get("task", {}).get("detail", {}).get("checkpoints", []):
        group = "bonus" if cp["id"] == "hybrid_bonus_embedding_passed" else "mandatory"
        check("official:" + cp["id"], cp["passed"], cp["note"], group)
    safety = score.get("breakdown", {}).get("safety", {}).get("detail", {})
    check("official_safety_clean", safety.get("fraction") == 1.0, safety)
    for req in scenario.get("ground_truth", {}).get("latency", {}).get("respond_to", []):
        event = scenario["events"][req["event_index"]]
        start = event["timestamp_ms"]
        eligible = [e for e in speech if e["t_ms"] >= start and len(text(e)) >= 3
                    and sum(ch.isalpha() for ch in text(e)) / len(text(e)) >= .5]
        delta = eligible[0]["t_ms"] - start if eligible else None
        check(f"response_latency_event_{req['event_index']}",
              delta is not None and delta <= req.get("full_credit_ms", 800),
              {"delta_ms": delta, "limit_ms": req.get("full_credit_ms", 800)}, "timing")
    deliveries = [e for e in trace if e.get("kind") == "event" and
                  e.get("event_type") not in {"tool_manifest", "scenario_end"}]
    lateness = [round(actual["t_ms"] - planned["timestamp_ms"], 1)
                for planned, actual in zip(scenario["events"], deliveries)]
    check("event_loop_delivery", len(deliveries) == len(scenario["events"])
          and all(abs(delta) <= 100 for delta in lateness),
          {"delivery_lateness_ms": lateness, "diagnostic_limit_ms": 100}, "timing")

    expected_tools = {
        "pub_01_text_simple": {"flight_search"},
        "pub_02_text_interrupt": {"flight_search"},
        "pub_03_text_chained_booking": {"flight_search", "book_flight"},
        "pub_04_text_no_tool": set(),
        "pub_05_audio_asr_ambiguity": {"flight_search"},
        "pub_06_audio_disfluency": {"flight_search"},
        "pub_07_visual_port_lookup": {"lookup_manual"},
        "pub_08_text_tool_failure": {"flight_search"},
        "pub_09_text_unseen_tool": {"weather_lookup"},
    }
    check("known_public_case", sid in expected_tools, sid)
    check("only_justified_tools", all(c.get("api_name") in expected_tools.get(sid, set())
          for c in calls), [{"api": c.get("api_name"), "args": c.get("args")} for c in calls])
    writes = [c for c in calls if schemas.get(c.get("api_name"), {}).get("kind") == "state_modifying"]
    check("authorized_write_count", len(writes) == (1 if sid == "pub_03_text_chained_booking" else 0),
          {"writes": len(writes), "successful_writes": sum(c.get("api_name") in
           {w.get("api_name") for w in writes} for c in successes)})

    destinations = {
        "pub_01_text_simple": ("chicago", "chi"),
        "pub_02_text_interrupt": ("new york", "nyc"),
        "pub_03_text_chained_booking": ("denver", "den"),
        "pub_05_audio_asr_ambiguity": ("boston", "bos"),
        "pub_06_audio_disfluency": ("new york", "nyc"),
        "pub_08_text_tool_failure": ("seattle", "sea"),
    }
    if sid in destinations:
        aliases = destinations[sid]
        matching = [c for c in successes if c.get("api_name") == "flight_search" and
                    normalized(c.get("args", {}).get("destination")) in aliases]
        useful = []
        for complete in matching:
            for f in finals:
                if not before(complete, f):
                    continue
                for row in complete.get("result", {}).get("flights", []):
                    fid = normalized(row.get("flight_id", ""))
                    departure = str(row.get("depart", ""))
                    time_aliases = {"08:00": ("08:00", "8 am", "8am"),
                                    "14:00": ("14:00", "2 pm", "2pm")}.get(departure, (departure,))
                    facts = any(t and t in text(f) for t in time_aliases) and str(row.get("price_usd")) in text(f)
                    booked_snapshot = sid == "pub_03_text_chained_booking" and normalized(
                        f.get("state_snapshot", {}).get("slots", {}).get("flight_id")) == fid
                    if (fid and fid in text(f)) or facts or booked_snapshot:
                        useful.append({"call_id": complete["call_id"], "final_ms": f["t_ms"]})
        check("flight_final_uses_completed_result", bool(useful), useful)
        snapshot = finals[-1].get("state_snapshot", {}).get("slots", {}) if finals else {}
        check("final_destination_snapshot", normalized(snapshot.get("destination")) in aliases, snapshot)
        wrong = [c for c in calls if c.get("api_name") == "flight_search" and
                 normalized(c.get("args", {}).get("destination")) not in aliases and not (
                     sid == "pub_02_text_interrupt" and c["t_ms"] < 1900 and
                     normalized(c.get("args", {}).get("destination")) in {"boston", "bos"})]
        check("no_unrequested_destination_search", not wrong, wrong)
        for complete in matching:
            if sid in {"pub_01_text_simple", "pub_02_text_interrupt"}:
                expected = "friday" if sid == "pub_01_text_simple" else "tomorrow"
                check("retained_requested_date", normalized(complete.get("args", {}).get("date")) == expected,
                      {"expected": expected, "args": complete.get("args")})
                check("snapshot_retains_requested_date", normalized(snapshot.get("date")) == expected, snapshot)
        current_ids = {normalized(r["flight_id"]) for c in matching
                       for r in c.get("result", {}).get("flights", []) if r.get("flight_id")}
        bad_ids = [fid for f in finals for fid in re.findall(r"fl-[a-z0-9]+-[a-z0-9]+", text(f))
                   if fid not in current_ids]
        check("no_stale_or_fabricated_flight_ids", not bad_ids, bad_ids)
        check("snapshot_flight_id_is_grounded", "flight_id" not in snapshot
              or normalized(snapshot["flight_id"]) in current_ids, snapshot.get("flight_id"))

    if sid == "pub_02_text_interrupt":
        interruptions = [e for e in deliveries if e.get("event_type") == "interruption"]
        actual = interruptions[0]["t_ms"] if interruptions else 1900
        pending_boston = [c for c in calls if normalized(c.get("args", {}).get("destination"))
                          in {"boston", "bos"} and c["t_ms"] <= 1900 and not any(
                              done.get("call_id") == c.get("call_id") and done["t_ms"] <= actual
                              for done in completions)]
        delays = []
        for c in pending_boston:
            cancels = [e for e in trace if e.get("kind") == "tool_cancelled"
                       and e.get("call_id") == c.get("call_id")]
            delay = cancels[0]["t_ms"] - actual if cancels else None
            delays.append({"call_id": c["call_id"], "from_delivery_ms": delay,
                           "from_nominal_ms": cancels[0]["t_ms"] - 1900 if cancels else None})
        check("stale_call_cancelled_within_800ms", all(d["from_delivery_ms"] is not None
              and 0 <= d["from_delivery_ms"] <= 800 and d["from_nominal_ms"] <= 800 for d in delays), delays)
        check("public_interruption_exercised_inflight_tool", bool(pending_boston),
              {"pending_boston_calls": len(pending_boston)}, "coverage")

    if sid == "pub_03_text_chained_booking":
        book = writes[0] if len(writes) == 1 else {}
        args = book.get("args", {})
        provenance = [c for c in successes if c.get("api_name") == "flight_search"
                      and book and before(c, book) and any(
                          r.get("flight_id") == args.get("flight_id") and r.get("depart") == "08:00"
                          for r in c.get("result", {}).get("flights", []))]
        check("booking_id_selected_from_prior_8am_result", bool(provenance)
              and normalized(args.get("passenger_name")) == "alice", args)
        booking = [c for c in successes if c.get("call_id") == book.get("call_id")]
        confirmed = [f for f in finals for c in booking if before(c, f)
                     and normalized(c.get("result", {}).get("booking_id", "missing")) in text(f)]
        check("final_confirms_actual_booking_id", bool(confirmed), [text(f) for f in finals])
        early = [text(e) for e in speech if re.search(r"\b(?:booked|reserved|confirmed)\b", text(e))
                 and not re.search(r"\b(?:will|not|isn't|is not|couldn't|could not)\b", text(e))
                 and not any(before(c, e) for c in booking)]
        check("no_early_completion_claim", not early, early)
        final_slots = finals[-1].get("state_snapshot", {}).get("slots", {}) if finals else {}
        check("booking_snapshot_matches_completed_write", bool(booking) and all(
            final_slots.get(key) == booking[-1].get("result", {}).get(key)
            for key in ("flight_id", "booking_id")), final_slots)

    if sid == "pub_07_visual_port_lookup":
        lookups = [c for c in successes if c.get("api_name") == "lookup_manual"]
        supplied_embeddings = [c for c in calls if "image_embedding" in c.get("args", {})]
        if supplied_embeddings:
            evidence = [row["embedding"] for row in media_evidence or [] if isinstance(row.get("embedding"), dict)]
            verified = []
            for call in supplied_embeddings:
                frames = [e for e in scenario["events"] if e.get("event_type") == "video_frame"
                          and e["timestamp_ms"] <= call["t_ms"]]
                raw_image = (media_root / frames[-1]["payload"]["image_ref"]).read_bytes() if media_root and frames else None
                try:
                    vector = call["args"]["image_embedding"]
                    valid = isinstance(vector, list) and bool(vector) and all(
                        type(v) in (int, float) and math.isfinite(float(v)) for v in vector) and any(vector)
                    vector_hash = hashlib.sha256(json.dumps([float(v) for v in vector],
                        separators=(",", ":"), allow_nan=False).encode()).hexdigest() if valid else None
                except (TypeError, ValueError, OverflowError):
                    vector_hash = None
                verified.append(bool(raw_image and vector_hash and any(
                    e.get("status") == "success" and e.get("http_status") == 200
                    and bool(e.get("model")) and e.get("dimensions") == len(vector)
                    and e.get("vector_sha256") == vector_hash and e.get("input_bytes") == len(raw_image)
                    and e.get("input_sha256") == hashlib.sha256(raw_image).hexdigest() for e in evidence)))
            check("submitted_embedding_requires_computation_evidence", all(verified) if evidence else None,
                  {"matched_current_image_and_vector": verified, "per_run_embedding_records": evidence})
        cited = []
        for c in lookups:
            for page in c.get("result", {}).get("pages", []):
                for f in finals:
                    if (before(c, f) and "hdmi" in normalized(page.get("title"))
                            and "hdmi" in text(f) and re.search(r"\bpage\s*" + re.escape(str(page.get("page"))) + r"\b", text(f))
                            and any(word in text(f) for word in ("display", "monitor", "video", "television", "tv", "projector"))):
                        cited.append({"call_id": c["call_id"], "page": page, "final": text(f)})
        check("visual_answer_cites_retrieved_relevant_page_and_use", bool(cited), cited)
        check("visual_query_contains_observed_port", any("hdmi" in normalized(c.get("args", {}).get("query"))
              for c in lookups), [c.get("args") for c in lookups])

    if sid == "pub_08_text_tool_failure":
        searches = [c for c in calls if c.get("api_name") == "flight_search"]
        first_errors = [e for e in completions if searches and e.get("call_id") == searches[0].get("call_id")
                        and e.get("status") == "error"]
        check("retry_is_bounded_and_after_failure", len(searches) == 2 and bool(first_errors)
              and before(first_errors[0], searches[1])
              and searches[1].get("args") == searches[0].get("args"),
              {"calls": searches, "first_errors": first_errors})

    if sid == "pub_09_text_unseen_tool":
        weather = [c for c in successes if c.get("api_name") == "weather_lookup"]
        grounded = [f for f in finals for c in weather if before(c, f)
                    and any(normalized(c.get("result", {}).get(key, "missing")) in text(f)
                            for key in ("condition", "forecast", "temp_f"))]
        check("unfamiliar_tool_final_after_actual_result", bool(grounded), [text(f) for f in finals])
        early = [text(e) for e in speech if any(word in text(e) for word in ("sunny", "74", "clear skies"))
                 and not any(before(c, e) for c in weather)]
        check("manifest_default_result_not_used_as_live_evidence", not early, early)

    media_refs = [e["payload"][key] for e in scenario["events"]
                  for key in ("audio_ref", "image_ref") if key in e.get("payload", {})]
    if media_refs:
        observed = {m.get("sha256") for row in media_evidence or []
                    if row.get("status") == 200 or row.get("usage")
                    for m in row.get("input_media", []) if m.get("bytes", 0) > 0}
        expected = {ref: hashlib.sha256((media_root / ref).read_bytes()).hexdigest()
                    for ref in media_refs} if media_root else {}
        check("actual_media_bytes_sent_to_provider", None if media_evidence is None or not expected
              else all(digest in observed for digest in expected.values()),
              {"expected_sha256": expected, "observed_sha256": sorted(observed)}, "evidence")
    mandatory = [c for c in checks if c["group"] == "mandatory"]
    gates = [c for c in checks if c["group"] in {"mandatory", "timing", "evidence"}]
    return {"scenario_id": sid, "official_score": score.get("total"),
            "task_complete": all(c["status"] == "pass" for c in mandatory),
            "accepted": all(c["status"] == "pass" for c in gates), "checks": checks,
            "failures": [c["id"] for c in gates if c["status"] != "pass"],
            "limitations": ["Bounded public trace assertions; not a semantic quality judge.",
                            "No hidden-set, Linux/GPU or LLM-quality-multiplier evidence."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace_json", type=Path)
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    import sys
    sys.path.insert(0, str(args.kit.resolve()))
    from harness.mock_env import TOOL_REGISTRY
    rows = json.loads(args.trace_json.read_text(encoding="utf-8"))
    rows = rows if isinstance(rows, list) else [rows]
    report = []
    for row in rows:
        scenario = json.loads((args.kit / "scenarios" / (row["scenario_id"] + ".json")).read_text())
        report.append(audit_public(scenario, row["trace"], row["score"], TOOL_REGISTRY,
                                   row.get("model_evidence"), args.kit))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"cases": len(report), "task_complete": sum(r["task_complete"] for r in report),
                      "accepted": sum(r["accepted"] for r in report), "out": str(args.out)}))


if __name__ == "__main__":
    main()
