"""Bounded, descriptor-based evidence checks for state-changing proposals.

Language interpretation remains the planner's job. These checks independently
reject a model label/quote without a current, affirmative user command.
"""
from __future__ import annotations

import json
import re

from .schema import scalar_fields


def words(text: str) -> str:
    return " ".join(text.casefold().replace("\u2019", "'").split())


def contains_value(value: str, text: str) -> bool:
    value = words(value)
    return bool(value) and re.search(r"(?<![\w-])" + re.escape(value) + r"(?![\w-])", words(text)) is not None


def _language_only(source):
    """JSON argument values are data, not quoted or negated user instructions."""
    decoder = json.JSONDecoder()
    chars, index = list(source), 0
    while index < len(source):
        if source[index] in "[{":
            try:
                _, length = decoder.raw_decode(source[index:])
                chars[index:index + length] = " " * length
                index += length
                continue
            except ValueError:
                pass
        index += 1
    return "".join(chars)


def _verified_conditions(source, selection):
    """Only exact equality conditions proved by a validated result selection."""
    if not re.search(r"\bif\b", source):
        return source
    if not selection:
        return None
    pattern = r"\bif\s+(?:the\s+)?([a-z][a-z_ ]*?)\s+(?:is|equals?)\s+(?:exactly\s+)?(-?\d+(?:\.\d+)?|true|false|[a-z]+)(?=[.!?;]|$)"
    chars = list(source)
    for match in re.finditer(pattern, source):
        field, expected = match[1].strip(), match[2]
        try:
            expected = json.loads(expected)
        except ValueError:
            pass
        verified = any(path.rsplit(".", 1)[-1].replace("_", " ").casefold() == field
                       and type(actual) is type(expected) and actual == expected
                       for path, actual in selection.items())
        if not verified:
            return None
        chars[match.start():match.end()] = " " * len(match[0])
    scrubbed = "".join(chars)
    return None if re.search(r"\bif\b", scrubbed) else scrubbed


def authorization_grant(step: dict, tool: dict, texts: list[tuple[int, str]], *, selection=None) -> str | None:
    evidence = step.get("authorization")
    if not isinstance(evidence, dict) or not isinstance(evidence.get("quote"), str):
        return None
    quote = words(evidence["quote"])
    if len(quote) < 4:
        return None
    if "message_index" in evidence:
        cited = [text for index, text in texts if index == evidence["message_index"]]
        if not cited or quote not in words(" ".join(cited)):
            return None
    source = words(" ".join(text for _, text in texts))
    if not source or quote not in source:
        return None
    language = _verified_conditions(_language_only(source), selection)
    if language is None:
        return None
    # Reject even when the model cherry-picks the positive part of a negation,
    # quotation, reported command, hypothetical or a later self-retraction.
    unsafe = r"\b(?:don't|do not|never|not yet|hold off|wait|instead|if|unless|until|maybe|might|could i|should i|would i|suppose|imagine|hypothetical|example|said|says|told|stop|forget)\b"
    if re.search(unsafe, language) or '"' in language or "\u201c" in language or "\u201d" in language:
        return None
    if re.search(r"\b(?:not|no)\b", language):
        return None
    description = str(tool.get("description", ""))
    name = str(step.get("api_name", "")).rsplit(".", 1)[-1]
    verbs = set()
    first = re.match(r"\s*([a-zA-Z]+)\b", description)
    if first:
        verbs.add(first[1].casefold())
    verbs.add(re.split(r"[_\-]", name)[0].casefold())
    # Small language equivalences, independent of domains or tool names.
    for group in ({"book", "reserve"}, {"create", "open", "file", "submit"},
                  {"cancel", "undo", "withdraw"}, {"buy", "purchase", "order"},
                  {"send", "dispatch"}, {"delete", "remove"}):
        if verbs & group:
            verbs.update(group)
    verbs -= {"get", "find", "search", "lookup", "list", "check", "read", "show", "retrieve", "tool", "api", ""}
    if not verbs:
        return None
    verb = "(?:" + "|".join(re.escape(item) for item in sorted(verbs)) + ")"
    prefix = r"(?:^|[.!?;,]\s*|\band\s+|\bthen\s+)(?:(?:please|yes|okay|ok|now)\s+)*(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?)?(?:go\s+ahead\s+and\s+)?"
    quote_start = source.find(quote)
    quote_end = quote_start + len(quote)
    matches = [match for match in re.finditer(prefix + "(" + verb + r"\s+[^.!?;]+)", language)
               if match.start(1) < quote_end and match.end(1) > quote_start]
    match = matches[0] if len(matches) == 1 else None
    if not match or not re.search(r"\b" + verb + r"\b", quote):
        return None
    command = words(match[1])
    # A tool cannot borrow permission for a different named object. Pronouns and
    # selected options are resolved by the planner and checked by result binding.
    tail = re.sub(r"^\w+\s+", "", command)
    if re.match(r"(?:it|this|that|them|the\s+(?:selected|chosen|first|second|third|\d))\b", tail):
        return command
    if step.get("result_bindings") and re.match(
            r"(?:(?:with|using|via)\s+)?(?:the|this|that)\s+[^.!?;]*\b(?:option|offer|one|result|selection)\b", tail):
        return command
    target = re.split(r"\b(?:for|to)\b", tail, maxsplit=1)[0]
    if any(isinstance(value, str) and len(value.strip()) > 2 and contains_value(value, target)
           for _, value in scalar_fields(step.get("args", {}))):
        return command
    if selection and any(isinstance(value, str) and contains_value(value, target) for value in selection.values()):
        return command
    ignored = {"a", "an", "the", "to", "of", "for", "from", "with", "and", "by", "in", "on", "as", "specific", "existing", "new", "current", "selected", "one", "tool", "request"}
    nouns = {item.casefold().rstrip("s") for item in re.findall(r"[a-zA-Z]+", description + " " + name.replace("_", " "))
             if item.casefold() not in ignored | verbs}
    supplied = {item.rstrip("s") for item in re.findall(r"[a-zA-Z]+", tail)}
    return command if nouns & supplied else None


def authorized(step: dict, tool: dict, texts: list[tuple[int, str]]) -> bool:
    return bool(authorization_grant(step, tool, texts))
