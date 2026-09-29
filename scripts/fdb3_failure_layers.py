"""Summarize a local 100-recording run by first-divergence candidates.

Evaluator-side only. Reads each case's report entry, result and evaluation.
Labels are candidates for review, not established causes.
"""
import argparse
import collections
import json
from pathlib import Path


def classify(case, result, evaluation):
    labels = []
    if case.get("status") != "completed":
        return ["infrastructure"]
    reason = ((evaluation or {}).get("strict") or {}).get("failure_reason", "") or ""
    events = result.get("controller_events", [])
    voice = result.get("voice_events", [])
    onsets = [row["at"] for row in voice if row.get("event") == "speech_segment_started"]
    calls = result.get("actual_tool_calls", [])
    if onsets and any(isinstance(call.get("timestamp_end"), (int, float)) and call["timestamp_end"] < max(onsets)
                      for call in calls):
        labels.append("premature_call_during_speech")
    window = case.get("upstream_window") or {}
    if case.get("strict_pass") and case.get("window_strict_pass") is False:
        labels.append("late_only")
    if not case.get("strict_pass"):
        clarifications = [str(row.get("payload", {}).get("text", "")) for row in events if row.get("action") == "clarification_request"]
        if any("confirm the action" in text or "confirm the proposed values" in text for text in clarifications):
            labels.append("write_gate_refusal")
        if any("cannot invent" in text or "needs a successful result" in text for text in clarifications):
            labels.append("binding_refusal")
        if any(row.get("delivery") == "stale_dropped" or row.get("event") in {"speech_admission_rejected", "speech_message_unbound"}
               for row in voice):
            labels.append("fragment_admission")
        if "Unexpected tools" in reason:
            labels.append("unexpected_tool")
        if "Missing tools" in reason:
            labels.append("missing_tool")
        if "Wrong arguments" in reason:
            labels.append("wrong_arguments")
    if window.get("late_calls"):
        labels.append("late_call")
    return labels or (["pass"] if case.get("strict_pass") else ["unclassified"])


# One mutually exclusive primary outcome per recording. Causes the controller
# chose (refusals) rank above the scorer symptoms they produce (missing tools).
PRIMARY_ORDER = ("infrastructure", "write_gate_refusal", "binding_refusal", "unexpected_tool",
                 "missing_tool", "wrong_arguments", "late_only", "late_call", "fragment_admission",
                 "unclassified")


def primary(case, labels):
    if case.get("status") == "completed" and case.get("strict_pass") and case.get("window_strict_pass") is not False:
        return "pass"
    return next((label for label in PRIMARY_ORDER if label in labels), "unclassified")


def summarize(run):
    run = Path(run)
    report = json.loads((run / "report.json").read_text(encoding="utf-8"))
    rows, counts, primaries = [], collections.Counter(), collections.Counter()
    for index, case in enumerate(report.get("cases", [])):
        root = run / f"case-{index:03d}"
        result_path, evaluation_path = root / "inference/result.json", root / "evaluation.json"
        result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {}
        evaluation = json.loads(evaluation_path.read_text(encoding="utf-8")) if evaluation_path.is_file() else {}
        labels = classify(case, result, evaluation)
        counts.update(labels)
        outcome = primary(case, labels)
        primaries[outcome] += 1
        rows.append({"case": index, "recording": case.get("recording"), "strict_pass": case.get("strict_pass"),
                     "window_strict_pass": case.get("window_strict_pass"), "primary": outcome, "labels": labels,
                     "failure_reason": case.get("failure_reason", "")})
    cases = report.get("cases", [])
    return {"run": run.name, "cases": len(cases), "strict_pass": sum(bool(c.get("strict_pass")) for c in cases),
            "window_strict_pass": sum(c.get("window_strict_pass") is True for c in cases),
            "infrastructure": sum(c.get("status") != "completed" for c in cases),
            "primary_counts": dict(primaries), "label_counts": dict(counts), "rows": rows,
            "note": ("primary_counts are mutually exclusive and sum to the cases; label_counts overlap "
                     "(a recording can carry several). Both are automatic candidates, not established causes.")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    summary = summarize(args.run)
    if args.output:
        args.output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({key: summary[key] for key in ("run", "cases", "strict_pass", "window_strict_pass",
                                                    "infrastructure", "primary_counts", "label_counts")}, indent=2))


if __name__ == "__main__":
    main()
