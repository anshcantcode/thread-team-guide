"""Synthetic broken-agent traces for oracle sensitivity, never agent evidence."""
from copy import deepcopy


def negative_controls(case, witness):
    """Yield (defect, trace) where the mutation necessarily violates this story.

    Eligibility is taken from concrete witness behavior, not oracle return values.
    An always-clarify agent is only a negative control when the task needs a call;
    clarification is correct for genuinely missing arguments or ambiguous audio.
    """
    yield "silent_agent", []
    calls = [r for r in witness if r.get("kind") == "action" and r.get("action") == "tool_call"]
    finals = [r for r in witness if r.get("kind") == "action" and r.get("action") == "final_response"]
    if calls:
        yield "always_clarify", [{"kind": "action", "action": "clarification_request", "t_ms": 150, "payload": {"text": "Please clarify."}}]
        yield "answer_text_without_execution", [deepcopy(r) for r in witness if r.get("kind") == "action" and r.get("action") in {"final_response", "clarification_request"}]
        bad = deepcopy(witness)
        target = next(r for r in bad if r.get("action") == "tool_call")
        first = next(iter(target["args"]), None)
        if first is not None:
            original = target["args"][first]
            target["args"][first] = [] if not isinstance(original, list) else {}
            yield "wrong_argument_type", bad
        bad = [deepcopy(r) for r in witness if r.get("kind") != "tool_completed"]
        # Some stories intentionally have no successful completion (lost write,
        # exhausted retry); their omission isn't a new defect.
        if any(rule["op"] in {"grounded", "binding"} for rule in case["oracle"]):
            yield "fabricated_result_evidence", bad
    else:
        # A schema-valid read/write still violates an explicit no-call task.
        def value(field):
            if "enum" in field:
                return field["enum"][0]
            kind = field["type"]
            if kind == "object":
                return {name: value(spec) for name, spec in field.get("properties", {}).items() if spec.get("required")}
            return {"string": "unrequested", "number": 1, "boolean": False, "array": []}[kind]
        if case["tools"]:
            api, spec = next(iter(case["tools"].items()))
            args = {name: value(field) for name, field in spec.get("args", {}).items() if field.get("required")}
            bad = deepcopy(witness)
            bad.append({"kind": "action", "action": "tool_call", "t_ms": 200, "api_name": api, "call_id": "unauthorized-control", "args": args})
            yield "acts_on_forbidden_request", bad
    if any(r.get("action") == "cancel_tool" or r.get("kind") == "tool_cancelled" for r in witness):
        yield "ignores_interruption_cancellation", [deepcopy(r) for r in witness if r.get("action") != "cancel_tool" and r.get("kind") != "tool_cancelled"]
        bad = deepcopy(witness)
        for row in bad:
            if row.get("action") == "cancel_tool" or row.get("kind") == "tool_cancelled":
                row["t_ms"] += 801
        bad.sort(key=lambda row: row["t_ms"])
        yield "cancels_too_late", bad
    writes = [r for r in calls if case["tools"].get(r["api_name"], {}).get("kind") == "state_modifying"]
    if writes:
        bad = deepcopy(witness)
        again = deepcopy(writes[0])
        again["call_id"] += "-duplicate"
        again["t_ms"] += 1
        bad.append(again)
        bad.sort(key=lambda row: row["t_ms"])
        yield "duplicates_write_with_new_call_id", bad
    if len(calls) >= 2:
        bad = deepcopy(witness)
        mutable_calls = [r for r in bad if r.get("action") == "tool_call"]
        mutable_calls[1]["call_id"] = mutable_calls[0]["call_id"]
        yield "reuses_call_id", bad
    if finals:
        bad = deepcopy(witness)
        for row in bad:
            if row.get("action") == "final_response":
                row.pop("state_snapshot", None)
        yield "omits_final_snapshot", bad
    if any(row.get("kind") == "media_access" for row in witness):
        yield "pretends_to_read_media", [deepcopy(r) for r in witness if r.get("kind") != "media_access"]
    actions = [r for r in witness if r.get("kind") == "action"]
    if actions:
        bad = deepcopy(witness)
        target = next(r for r in reversed(bad) if r.get("kind") == "action")
        end = max(s["at_ms"] for s in case["steps"])
        target["t_ms"] = end + case["tail_ms"] + 1
        bad.sort(key=lambda row: row["t_ms"])
        yield "emits_after_tail", bad
