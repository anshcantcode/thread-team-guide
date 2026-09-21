"""Strict, test-only trace obligations. No participant imports or model calls."""
from __future__ import annotations

import math
from collections import Counter
from typing import Any

MISSING = object()
SPOKEN = {"filler_speech", "clarification_request", "final_response"}


def get_path(value: Any, path: str, default=MISSING):
    for part in path.split(".") if path else []:
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return default
    return value


def subset(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and subset(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(subset(a, e) for a, e in zip(actual, expected))
    # bool is not a number, even though Python equality says True == 1.
    if type(actual) in (int, float) and type(expected) in (int, float):
        return actual == expected
    return type(actual) is type(expected) and actual == expected


def schema_errors(spec: dict, args: Any, prefix: str = "args") -> list[str]:
    """Validate the documented raw-kit schema, recursively (stricter than its shallow mock)."""
    if not isinstance(args, dict):
        return [f"{prefix}: expected object"]
    errors = []
    for name, field in spec.get("args", spec.get("properties", {})).items():
        path = f"{prefix}.{name}"
        if name not in args:
            if field.get("required"):
                errors.append(f"{path}: missing required value")
            continue
        errors.extend(value_errors(field, args[name], path))
    return errors


def value_errors(field: dict, value: Any, path: str) -> list[str]:
    kind = field.get("type")
    valid = {"string": isinstance(value, str), "number": type(value) is int or (type(value) is float and math.isfinite(value)),
             "boolean": type(value) is bool, "array": isinstance(value, list), "object": isinstance(value, dict)}
    if kind not in valid or not valid[kind]:
        return [f"{path}: expected {kind}"]
    errors = []
    if "enum" in field and not any(subset(value, item) or (type(value) in (int, float) and type(item) in (int, float) and value == item) for item in field["enum"]):
        errors.append(f"{path}: invalid enum")
    if kind == "object":
        errors.extend(schema_errors(field, value, path))
    if kind == "array":
        item = field.get("items", "string")
        item = {"type": item} if isinstance(item, str) else item
        for index, member in enumerate(value):
            errors.extend(value_errors(item, member, f"{path}.{index}"))
    return errors


def selected(trace: list[dict], selector: dict) -> list[tuple[int, dict]]:
    result = []
    for index, row in enumerate(trace):
        if not isinstance(row, dict):
            continue
        if row.get("t_ms", 0) < selector.get("after_ms", -math.inf) or row.get("t_ms", 0) > selector.get("before_ms", math.inf):
            continue
        if "action_in" in selector and row.get("action") not in selector["action_in"]:
            continue
        fields = {k: v for k, v in selector.items() if k not in {"after_ms", "before_ms", "action_in"}}
        if subset({k: row.get(k, MISSING) for k in fields}, fields):
            result.append((index, row))
    return result


def _text_rows(trace, rule):
    action = rule.get("action", "final_response")
    sel = {"kind": "action", "action_in": action} if isinstance(action, list) else {"kind": "action", "action": action}
    for key in ("after_ms", "before_ms"):
        if key in rule:
            sel[key] = rule[key]
    return [(index, row, str(row.get("payload", {}).get("text", ""))) for index, row in selected(trace, sel)]


def _completed_before(trace, call, index):
    return [row for i, row in enumerate(trace[:index]) if isinstance(row, dict) and row.get("kind") == "tool_completed"
            and row.get("call_id") == call.get("call_id") and row.get("api_name") == call.get("api_name")
            and row.get("status") == "success" and isinstance(row.get("result"), dict) and row["result"].get("status") == "success"]


def _check(case: dict, trace: list[dict], rule: dict) -> tuple[bool, str]:
    op = rule["op"]
    if op == "within_tail":
        late = selected(trace, {"kind": "action", "after_ms": rule["deadline_ms"] + .0001})
        return not late, "action emitted after the declared tail" if late else "actions within declared tail"
    if op == "count":
        count = len(selected(trace, rule["select"]))
        lower, upper = rule.get("min", 0), rule.get("max", math.inf)
        return lower <= count <= upper, f"count={count}; expected {lower}..{upper}"
    if op == "sequence":
        cursor = -1
        for selector in rule["selectors"]:
            matches = [i for i, _ in selected(trace, selector) if i > cursor]
            if not matches:
                return False, f"missing ordered step {selector}"
            cursor = min(matches)
        return True, "ordered steps present"
    if op == "snapshot":
        rows = [(i, row) for i, row in enumerate(trace) if isinstance(row, dict) and isinstance(row.get("state_snapshot"), dict)
                and row.get("t_ms", 0) >= rule.get("after_ms", 0)]
        if not rows:
            return False, "missing post-event snapshot"
        state = rows[-1][1]["state_snapshot"]
        ok = subset(state.get("slots"), rule.get("slots", {})) and all(get_path(state, path) is MISSING for path in rule.get("absent", []))
        if "intent" in rule:
            ok = ok and state.get("intent") == rule["intent"]
        return ok, "latest snapshot matches" if ok else "latest snapshot disagrees"
    if op == "text":
        rows = _text_rows(trace, rule)
        texts = [text.casefold() for _, _, text in rows]
        # Positive requirements must coexist in one response, not be scattered over contradictions.
        def matches(text):
            return all(str(v).casefold() in text for v in rule.get("all_of", [])) and (
                not rule.get("any_of") or any(str(v).casefold() in text for v in rule["any_of"]))
        positive = any(matches(text) for text in texts)
        negative = not any(str(v).casefold() in text for text in texts for v in rule.get("none_of", []))
        return positive and negative, "text obligations met" if positive and negative else "text missing/forbidden content"
    if op == "cancel":
        calls = selected(trace, rule["call"])
        if not calls:
            return False, "no pending call to cancel; precondition missing"
        for _, call in calls:
            rows = [row for row in trace if isinstance(row, dict) and row.get("t_ms", 0) >= rule["after_ms"]
                    and row.get("t_ms", 0) <= rule["after_ms"] + rule.get("within_ms", 800)
                    and ((row.get("kind") == "tool_cancelled" and row.get("call_id") == call["call_id"])
                         or (row.get("kind") == "action" and row.get("action") == "cancel_tool"
                             and row.get("payload", {}).get("call_id") == call["call_id"]))]
            if not rows:
                return False, "missing prompt cancellation of a matched call"
        return True, "all matched calls cancelled promptly"
    if op in {"grounded", "binding"}:
        sources = selected(trace, rule["source"])
        targets = selected(trace, rule["target"]) if op == "binding" else [(i, row) for i, row, _ in _text_rows(trace, rule)]
        if not sources or not targets:
            return False, "missing source call or grounded target"
        for index, target in targets:
            for source_index, source in sources:
                if source_index >= index:
                    continue
                for completion in _completed_before(trace, source, index):
                    value = get_path(completion["result"], rule["path"])
                    if value is MISSING:
                        continue
                    if op == "binding":
                        if subset(get_path(target.get("args", {}), rule["arg_path"]), value):
                            return True, "argument bound to a prior actual result"
                    elif str(value).casefold() in str(target.get("payload", {}).get("text", "")).casefold():
                        return True, "response uses prior successful result evidence"
        return False, "result value not grounded in a preceding matched completion"
    if op == "protocol":
        for row in trace:
            if not isinstance(row, dict):
                return False, "trace row must be an object"
            if row.get("kind") in {"protocol_error", "agent_crash", "adapter_error"}:
                return False, f"{row['kind']} observed"
            if row.get("kind") != "action":
                continue
            action = row.get("action")
            if action not in SPOKEN | {"tool_call", "cancel_tool"}:
                return False, "unknown outbound action"
            if action in SPOKEN and not str(row.get("payload", {}).get("text", "")).strip():
                return False, "empty spoken action"
            if action == "final_response":
                state = row.get("state_snapshot")
                if not isinstance(state, dict) or not isinstance(state.get("slots"), dict) or not isinstance(state.get("intent"), str):
                    return False, "missing/malformed final snapshot"
        return True, "protocol clean"
    if op == "schema":
        for _, row in selected(trace, {"kind": "action", "action": "tool_call"}):
            spec = case["tools"].get(row.get("api_name"))
            if not spec or spec.get("kind") not in {"read_only", "state_modifying"}:
                return False, "unknown tool or invalid effect kind"
            errors = schema_errors(spec, row.get("args"))
            if errors:
                return False, "; ".join(errors)
        return True, "all emitted arguments recursively valid"
    if op == "unique_call_ids":
        ids = [row.get("call_id") for _, row in selected(trace, {"kind": "action", "action": "tool_call"})]
        ok = all(isinstance(value, str) and value for value in ids) and len(ids) == len(set(ids))
        return ok, "call IDs unique" if ok else "missing/reused call ID"
    if op == "no_duplicate_writes":
        import json
        writes = [(row.get("api_name"), json.dumps(row.get("args"), sort_keys=True)) for _, row in selected(trace, {"kind": "action", "action": "tool_call"})
                  if case["tools"].get(row.get("api_name"), {}).get("kind") == "state_modifying"]
        ok = all(count <= 1 for count in Counter(writes).values())
        return ok, "no duplicate write dispatch" if ok else "duplicate write dispatch"
    if op == "lifecycle":
        exits = selected(trace, {"kind": "agent_exit", "before_ms": rule["alive_until_ms"] - 0.001})
        shutdown = selected(trace, {"kind": "shutdown", "pending_tasks": 0, "planner_closed": True})
        return not exits and bool(shutdown), "premature exit or missing clean-shutdown evidence" if exits or not shutdown else "tail survived; cleanup observed"
    if op == "media":
        rows = selected(trace, {"kind": "media_access", "media_ref": rule["media_ref"], "status": rule.get("status", "read")})
        if not rows:
            return False, "missing independently observed media access"
        if "sha256" in rule and not any(row.get("sha256") == rule["sha256"] for _, row in rows):
            return False, "wrong media bytes"
        return True, "media access verified (not a semantic correctness result by itself)"
    raise ValueError(f"unknown oracle operation: {op}")


def evaluate_case(case: dict, trace: list[dict]) -> dict:
    checks = []
    for rule in case["oracle"]:
        try:
            passed, detail = _check(case, trace, rule)
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as error:
            passed, detail = False, f"malformed trace/oracle: {type(error).__name__}: {error}"
        checks.append({"id": rule["id"], "passed": bool(passed), "detail": detail})
    failures = [row for row in checks if not row["passed"]]
    return {"passed": bool(checks) and not failures, "checks": checks, "failures": failures}
