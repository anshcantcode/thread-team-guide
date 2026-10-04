"""Lossless scalar spelling conversions for parameters declared Any by the FDB mock."""
from decimal import Decimal
import math
import re

from participant.authorization import identifier_field


_NUMBER = re.compile(
    r"(?P<sign>[+-]?)(?:[$\u00a3\u20ac\u20b9]\s*)?"
    r"(?P<number>(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)(?:\.[0-9]+)?)")


def mock_scalar(value):
    """Convert a whole scalar, never prose, identifiers or nested/encoded JSON.

    Leading zeroes, exponents, ranges and units are intentionally not plain
    numbers here. Decimal spellings that would lose precision stay strings.
    This is representation only: the controller must still ground the value.
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.casefold() in {"true", "yes", "false", "no"}:
        return text.casefold() in {"true", "yes"}
    match = _NUMBER.fullmatch(text) if len(text) <= 256 else None
    if match is None:
        return value
    number = match["sign"] + match["number"].replace(",", "")
    if "." not in number:
        return int(number)
    exact = Decimal(number)
    if exact == exact.to_integral_value():
        return int(exact)
    result = float(exact)
    return result if math.isfinite(result) and Decimal(str(result)) == exact else value


def mock_call_args(args, tool):
    """Serialize already checked values only for explicitly declared mock Any.

    The controller's proposal and authority evidence are never overwritten.
    Compound values and identifiers never receive recursive or numeric repair.
    """
    properties = tool.get("args", {}) if isinstance(tool, dict) else {}
    return {name: mock_scalar(value) if isinstance(properties.get(name), dict)
            and properties[name].get("fdb_mock_any") is True
            and not identifier_field(name, properties[name]) else value
            for name, value in args.items()}


def normalize_mock_scalar_proposals(decision, context):
    """Give the existing string-grounding gate the same value a typed planner sent.

    Native numbers get an equivalent decimal spelling, booleans their literal
    spelling (or the user's assigned yes/no). No missing value is supplied, and bindings
    retain exact result types for the controller's provenance checks. The mock
    serialization boundary converts an admitted scalar back to native JSON.
    """
    text = " ".join(str(m.get("payload", {}).get("text", ""))
                    for m in context.get("messages", [])[context.get("current_turn_start", 0):]
                    if m.get("event_type") in {"user_speech_chunk", "interruption"})
    pending = list(decision.get("tool_calls", []))
    while pending:
        step = pending.pop()
        if not isinstance(step, dict):
            continue
        if isinstance(step.get("after_result"), dict):
            pending.append(step["after_result"])
        if not isinstance(step.get("args"), dict):
            continue
        tool = context.get("tools", {}).get(step.get("api_name"), {})
        for name, value in list(step["args"].items()):
            spec = tool.get("args", {}).get(name, {})
            if (not isinstance(spec, dict) or spec.get("fdb_mock_any") is not True
                    or identifier_field(name, spec)
                    or name in (step.get("result_bindings") or {}) or name in (step.get("bindings") or {})):
                continue
            if type(value) is bool:
                literal, synonym = ("true", "yes") if value else ("false", "no")
                if (not re.search(r"\b" + literal + r"\b", text, re.I)
                        and re.search(r"(?:\bto\b|[=:])\s*" + synonym + r"\b", text, re.I)):
                    literal = synonym
                step["args"][name] = literal
            elif type(value) is int or type(value) is float and math.isfinite(value):
                spelling = format(Decimal(str(value)), "f")
                restored = mock_scalar(spelling)
                if type(restored) in (int, float) and restored == value:
                    step["args"][name] = spelling
    return decision
