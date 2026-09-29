"""Versioned semantic obligations; frozen v1 oracle remains unchanged.

This file can be loaded by path from the independent acceptance adapter.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import re

_spec = importlib.util.spec_from_file_location("samsung_challenge_frozen_v1", Path(__file__).with_name("oracle.py"))
v1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v1)


def expanded(value, path):
    parts = path.split(".") if path else []
    if not parts:
        return [value]
    if parts[0] == "*":
        members = value.values() if isinstance(value, dict) else value if isinstance(value, list) else []
        return [leaf for member in members for leaf in expanded(member, ".".join(parts[1:]))]
    member = v1.get_path(value, parts[0])
    return [] if member is v1.MISSING else expanded(member, ".".join(parts[1:]))


def anchored(trace, selector):
    anchors = v1.selected(trace, selector)
    if len(anchors) != 1:
        raise ValueError("Expected one actually delivered event anchor")
    return anchors[0]


def semantic_check(case, trace, rule):
    op = rule["op"]
    if op == "allowed_calls":
        for _, row in v1.selected(trace, {"kind": "action", "action": "tool_call"}):
            if not any(row.get("api_name") == allowed["api_name"] and v1.subset(row.get("args"), allowed["args"]) for allowed in rule["allowed"]):
                return False, "call has an unrequested target or different retained constraints"
        return True, "all calls use stated target/constraint combinations"
    if op in {"cancel_if_pending", "no_calls_after_event"}:
        event_index, event = anchored(trace, rule["anchor"])
        calls = v1.selected(trace, rule["call"])
        if op == "no_calls_after_event":
            return not any(index > event_index for index, _ in calls), "obsolete arguments must not be dispatched after their actual correction event"
        for index, call in calls:
            if index >= event_index:
                continue
            completed = any(row.get("kind") == "tool_completed" and row.get("call_id") == call["call_id"]
                            and row.get("api_name") == call["api_name"] for row in trace[index + 1:event_index])
            if completed:
                continue
            cancelled = any(row.get("t_ms", 0) <= event["t_ms"] + rule.get("within_ms", 800)
                            and ((row.get("action") == "cancel_tool" and row.get("payload", {}).get("call_id") == call["call_id"])
                                 or (row.get("kind") == "tool_cancelled" and row.get("call_id") == call["call_id"]))
                            for row in trace[event_index + 1:])
            if not cancelled:
                return False, "an actually pending obsolete call was not cancelled promptly"
        return True, "every actually pending obsolete call cancelled; absent/completed calls require none"
    if op == "grounded_any_option":
        sources = v1.selected(trace, rule["source"])
        for final_index, final, text in v1._text_rows(trace, rule):
            for source_index, source in sources:
                if source_index >= final_index:
                    continue
                for completion in v1._completed_before(trace, source, final_index):
                    for path in rule["paths"]:
                        for value in expanded(completion["result"], path):
                            if isinstance(value, str) and value and re.search(r"(?<![\w-])" + re.escape(value) + r"(?![\w-])", text, re.IGNORECASE):
                                return True, "answer identifies an option actually returned by the matched successful lookup"
        return False, "no answer grounded in an actual returned option for this request"
    if op == "no_stale_option_after_event":
        event_index, _ = anchored(trace, rule["anchor"])
        for index, row in enumerate(trace):
            if index <= event_index or row.get("kind") != "action" or row.get("action") != "final_response":
                continue
            text = str(row.get("payload", {}).get("text", ""))
            if any(re.search(r"(?<![\w-])" + re.escape(value) + r"(?![\w-])", text, re.IGNORECASE) for value in rule["forbidden_values"]):
                return False, "final answer uses an obsolete option identifier after the final correction"
        return True, "no obsolete option identifier in the final answer"
    return v1._check(case, trace, rule)


def evaluate_case(case, trace):
    checks = []
    for rule in case["oracle"]:
        try:
            passed, detail = semantic_check(case, trace, rule)
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as error:
            passed, detail = False, f"malformed trace/oracle: {type(error).__name__}: {error}"
        checks.append({"id": rule["id"], "passed": bool(passed), "detail": detail})
    failures = [check for check in checks if not check["passed"]]
    return {"passed": bool(checks) and not failures, "checks": checks, "failures": failures}
