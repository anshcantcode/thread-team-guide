"""FDB-v3 transport bridge. No benchmark metadata or answers are imported here."""
from __future__ import annotations

import ast
import asyncio
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import sys
import time
import threading
from urllib.parse import urlparse
import uuid

import httpx

from participant.agent import ParticipantAgent
from participant.planner import SYSTEM, _unique_json_object

UPSTREAM_COMMIT = "3e799c45a045256f47d5f1c9cda90157e2d2ec9e"
WRITES = {"book_flight", "update_identity_doc", "modify_autopay", "update_search_filter", "add_to_cart"}


def spelled_identifier(value):
    """Canonicalize one explicitly separated alphanumeric spelling, not prose."""
    if not isinstance(value,str) or not re.search(r"[,\s]",value):
        return value
    tokens = re.split(r"\s*,\s*|\s+",value.strip())
    separators = {"dash":"-","hyphen":"-","underscore":"_"}
    if len(tokens) < 2 or any(not re.fullmatch(r"[A-Za-z0-9]",t) and t.casefold() not in separators for t in tokens):
        return value
    if not any(re.fullmatch(r"[A-Za-z]",t) for t in tokens):
        return value
    return "".join(separators.get(t.casefold(),t) for t in tokens)


def normalize_read_identifiers(decision, context):
    """Normalize only supplied read arguments; never manufacture write authority."""
    text = " ".join(str(m.get("payload",{}).get("text","")) for m in context.get("messages",[])[context.get("current_turn_start",0):])
    if re.search(r"\b(?:literal|verbatim|comma|commas|spaces|quoted|exactly)\b",text,re.I):
        return decision
    for step in decision.get("tool_calls",[]):
        tool = context.get("tools",{}).get(step.get("api_name"),{})
        if tool.get("kind") != "read_only":
            continue
        for name,value in step.get("args",{}).items():
            descriptor = tool.get("args",{}).get(name,{})
            if name.endswith(("_id","_code","_number")) or "identifier" in descriptor.get("description","").lower():
                normalized = spelled_identifier(value)
                step["args"][name] = normalized
                if decision.get("slots",{}).get(name) == value:
                    decision["slots"][name] = normalized
    return decision


def heard_identifier(value, text):
    """The identifier as heard, when one run of heard tokens spells exactly the value.

    "4 5 6 QRS" or "K-L-M-3-4" gives "456QRS" / "KLM34" for a model value such as
    "456qrs" or "K-L-M-3-4". Only letter/digit tokens joined by spaces, commas or
    hyphens qualify, so a dictated "dash" word or other punctuation is preserved.
    """
    if not isinstance(value, str):
        return None
    compact = re.sub(r"[\s,\-]", "", value)
    if not re.fullmatch(r"[A-Za-z0-9]{2,}", compact) or not re.search(r"[A-Za-z]", compact):
        return None
    # Spelling-like tokens only: single characters, digit runs, short all-caps chunks,
    # or one compact token that already mixes letters and digits ("RQ74").
    # A spoken digit word ("x y z eight eight") spells its digit.
    def spelled(token):
        return (len(token) == 1 or token.isdigit() or (token.isupper() and len(token) <= 4)
                or token.casefold() in _SPOKEN_DIGITS
                or (re.search(r"\d", token) and re.search(r"[A-Za-z]", token)))
    tokens = [token for token in re.finditer(r"[A-Za-z0-9]+", text)]
    for start in range(len(tokens)):
        if not spelled(tokens[start][0]):
            continue
        joined = ""
        for end in range(start, min(len(tokens), start + 10)):
            if end > start and not re.fullmatch(r"[\s,\-]+", text[tokens[end - 1].end():tokens[end].start()]):
                break
            if not spelled(tokens[end][0]):
                break
            joined += _SPOKEN_DIGITS.get(tokens[end][0].casefold(), tokens[end][0])
            if len(joined) > len(compact):
                break
            if joined.casefold() == compact.casefold():
                # A single character continuing the spelling on either side means the
                # value would be a truncation of a longer spoken identifier.
                def continues(index, gap):
                    return (0 <= index < len(tokens) and len(tokens[index][0]) == 1
                            and re.fullmatch(r"[\s,\-]+", gap) is not None)
                if (start > 0 and continues(start - 1, text[tokens[start - 1].end():tokens[start].start()])) or (
                        end + 1 < len(tokens) and continues(end + 1, text[tokens[end].end():tokens[end + 1].start()])):
                    break
                return joined.upper() if joined.islower() else joined
    return None


def normalize_heard_identifiers(decision, context):
    """Identifier fields adopt the heard spelling's compact form and casing."""
    from participant.authorization import identifier_field
    text = " ".join(str(m.get("payload",{}).get("text","")) for m in context.get("messages",[])[context.get("current_turn_start",0):])
    if re.search(r"\b(?:literal|verbatim|comma|commas|spaces|quoted|exactly)\b",text,re.I):
        return decision
    pending = list(decision.get("tool_calls",[]))
    while pending:
        step = pending.pop()
        if not isinstance(step, dict):
            continue
        if isinstance(step.get("after_result"), dict):
            pending.append(step["after_result"])
        tool = context.get("tools",{}).get(step.get("api_name"),{})
        if not isinstance(step.get("args"), dict):
            continue
        for name, value in list(step["args"].items()):
            if identifier_field(name, tool.get("args",{}).get(name)):
                heard = heard_identifier(value, text)
                if heard is not None and heard != value:
                    step["args"][name] = heard
    return decision


_SPOKEN_DIGITS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
                  "six": "6", "seven": "7", "eight": "8", "nine": "9"}


class _RepeatedKeys(dict):
    """A JSON object that repeated a key (later value kept until checked)."""


def _json_object_marking_repeats(pairs):
    result, repeated = {}, False
    for key, value in pairs:
        repeated = repeated or key in result
        result[key] = value
    return _RepeatedKeys(result) if repeated else result


def parse_decision(content):
    """Parse a planner decision; a repeated key is fatal except in planner memory.

    "slots" is the planner's own memory, never an action or authority: an object
    there that repeats a key is dropped (returned flag True). A repeated key in
    anything else (tool calls, arguments, citations) stays a protocol error.
    """
    decision = json.loads(content, object_pairs_hook=_json_object_marking_repeats)
    if not isinstance(decision, dict):
        raise ValueError("Planner must return an object")
    def repeated(node):
        if isinstance(node, _RepeatedKeys):
            return True
        if isinstance(node, dict):
            return any(repeated(value) for value in node.values())
        return isinstance(node, list) and any(repeated(value) for value in node)
    dropped = False
    if repeated(decision.get("slots")):
        decision["slots"], dropped = {}, True
    if isinstance(decision, _RepeatedKeys) or repeated(decision):
        raise ValueError("Duplicate JSON object key.")
    return decision, dropped


def strip_vague_praise(decision, context):
    """A search query drops purely subjective praise ("nice watch" -> "watch").

    Only for a field named "query"; constraining words (cheap, best, wireless,
    under ...) are kept, and a query that would become empty is left alone.
    """
    pending = list(decision.get("tool_calls",[]))
    while pending:
        step = pending.pop()
        if not isinstance(step, dict):
            continue
        if isinstance(step.get("after_result"), dict):
            pending.append(step["after_result"])
        value = step.get("args", {}).get("query") if isinstance(step.get("args"), dict) else None
        if isinstance(value, str):
            stripped = re.sub(r"\b(?:really\s+|pretty\s+)?(?:nice|good|great|decent|cool|lovely)\s+", "", value,
                              flags=re.I).strip()
            if stripped:
                step["args"]["query"] = stripped
    return decision


def restore_first_person(decision, context):
    """A value the model restated in third person takes the user's own words back.

    "my house" -> planner "user's house" -> "my house", only when the current turn says
    "my <same words>"; any other value is left alone.
    """
    text = " ".join(str(m.get("payload", {}).get("text", ""))
                    for m in context.get("messages", [])[context.get("current_turn_start", 0):]
                    if m.get("event_type") in {None, "user_speech_chunk", "interruption"})
    pending = list(decision.get("tool_calls",[]))
    while pending:
        step = pending.pop()
        if not isinstance(step, dict):
            continue
        if isinstance(step.get("after_result"), dict):
            pending.append(step["after_result"])
        if not isinstance(step.get("args"), dict):
            continue
        for name, value in list(step["args"].items()):
            if not isinstance(value, str):
                continue
            match = re.fullmatch(r"\s*(?:the\s+)?(?:user|customer|caller)(?:'s|s'|s)\s+(.+?)\s*", value, re.I)
            if (match and not re.search(r"(?<!\w)" + re.escape(value.strip()) + r"(?!\w)", text, re.I)
                    and not re.search(r"\b(?:not|don't|dont|do not|never)\b[^.!?;]*\bmy\s+"
                                      + re.escape(match[1]) + r"\b", text, re.I)
                    and re.search(r"\bmy\s+" + re.escape(match[1]) + r"\b", text, re.I)):
                step["args"][name] = "my " + match[1]
    return decision


def restore_user_case(decision, context):
    """An all-lowercase value copied from the casefolded clause list takes the user's own casing.

    "Set my city filter to Eugene" -> planner "eugene" -> "Eugene". Only when the value
    occurs as a whole phrase in the current user turn with one consistent surface form.
    """
    text = " ".join(str(m.get("payload", {}).get("text", ""))
                    for m in context.get("messages", [])[context.get("current_turn_start", 0):]
                    if m.get("event_type") in {None, "user_speech_chunk", "interruption"})
    pending = list(decision.get("tool_calls",[]))
    while pending:
        step = pending.pop()
        if not isinstance(step, dict):
            continue
        if isinstance(step.get("after_result"), dict):
            pending.append(step["after_result"])
        if not isinstance(step.get("args"), dict):
            continue
        tool = context.get("tools", {}).get(step.get("api_name"), {})
        properties = tool.get("args", {}) if isinstance(tool, dict) else {}
        for name, value in list(step["args"].items()):
            if not isinstance(value, str) or not value.strip() or value != value.lower() or not re.search(r"[a-z]", value):
                continue
            # Schema literals and bound tool values have their own exact casing;
            # user typography must not rewrite that contract/provenance.
            spec = properties.get(name, {}) if isinstance(properties, dict) else {}
            bindings = step.get("result_bindings", {})
            if (isinstance(spec, dict) and ("enum" in spec or "const" in spec)
                    or isinstance(bindings, dict) and name in bindings
                    or isinstance(step.get("bindings"), dict) and name in step["bindings"]):
                continue
            forms = set(re.findall(r"(?<!\w)" + re.escape(value.strip()) + r"(?!\w)", text, re.I))
            if len(forms) == 1:
                form = forms.pop()
                if form != value.strip():
                    step["args"][name] = form
    return decision


def strip_type_head_noun(decision, context):
    """A "<noun>_type" value names the kind, not the noun: card_type "travel_card" -> "travel".

    Only a trailing copy of the field's own head noun is removed (with a space,
    underscore or hyphen before it), and never when nothing would remain.
    """
    pending = list(decision.get("tool_calls",[]))
    while pending:
        step = pending.pop()
        if not isinstance(step, dict):
            continue
        if isinstance(step.get("after_result"), dict):
            pending.append(step["after_result"])
        if not isinstance(step.get("args"), dict):
            continue
        for name, value in list(step["args"].items()):
            head = re.fullmatch(r"([a-z]+)_type", str(name))
            if not head or not isinstance(value, str):
                continue
            stripped = re.sub(r"[\s_\-]+" + re.escape(head[1]) + r"s?$", "", value.strip(), flags=re.I)
            if stripped and stripped != value.strip():
                step["args"][name] = stripped
    return decision


def fill_declared_write_defaults(decision, context):
    """An omitted optional argument of a write takes the contract's declared default.

    add_to_cart without quantity means quantity 1 by the contract; stating it makes
    the dispatched call explicit. Never invents a value without a declared default.
    """
    pending = list(decision.get("tool_calls",[]))
    while pending:
        step = pending.pop()
        if not isinstance(step, dict):
            continue
        if isinstance(step.get("after_result"), dict):
            pending.append(step["after_result"])
        tool = context.get("tools",{}).get(step.get("api_name"),{})
        if tool.get("kind") != "state_modifying" or not isinstance(step.get("args"), dict):
            continue
        for name, spec in (tool.get("args") or {}).items():
            if (isinstance(spec, dict) and spec.get("required") is False and "default" in spec
                    and name not in step["args"] and name not in (step.get("result_bindings") or {})):
                step["args"][name] = deepcopy(spec["default"])
    return decision


def drop_unstated_optional_numbers(decision, context):
    """Remove an optional read argument the current turn never states.

    Only arguments the contract marks optional, and only when neither the value
    nor its spoken form appears in the current user turn and it is not the
    declared default: an unstated budget such as max_price=50 is invented, and
    omitting it is a valid read. Never repair a write this way: omission can
    silently substitute a default quantity for the user's requested amount.
    """
    from participant.agent import _mentions_value
    text = " ".join(str(m.get("payload",{}).get("text","")) for m in context.get("messages",[])[context.get("current_turn_start",0):])
    pending = list(decision.get("tool_calls",[]))
    while pending:
        step = pending.pop()
        if not isinstance(step, dict):
            continue
        if isinstance(step.get("after_result"), dict):
            pending.append(step["after_result"])
        tool = context.get("tools",{}).get(step.get("api_name"),{})
        if tool.get("kind") != "read_only" or not isinstance(step.get("args"), dict):
            continue
        for name, value in list(step["args"].items()):
            spec = tool.get("args",{}).get(name)
            if (not isinstance(spec, dict) or spec.get("required", True)
                    or spec.get("type") not in {"number", "integer"}
                    or isinstance(value, bool) or not isinstance(value, (int, float))
                    or ("default" in spec and spec["default"] == value)):
                continue
            spoken = str(int(value)) if float(value).is_integer() else str(value)
            if not _mentions_value(tool, name, spoken, text):
                del step["args"][name]
    return decision


def drop_unstated_search_filters(decision, context):
    """Remove invented required search values before strict controller validation.

    "Search Denver, one bedroom" with a guessed max_price 5000 (or 0, or city "") runs with
    that filter absent instead of the guess. The controller then asks for the required
    value; omission never authorizes a null tool argument. Only read-only tools named
    as searches, and only while at least one required filter stays stated.
    """
    from participant.agent import _mentions_value
    from participant.schema import unstated_search_filters
    text = " ".join(str(m.get("payload", {}).get("text", ""))
                    for m in context.get("messages", [])[context.get("current_turn_start", 0):]
                    if m.get("event_type") in {None, "user_speech_chunk", "interruption"})
    pending = list(decision.get("tool_calls",[]))
    while pending:
        step = pending.pop()
        if not isinstance(step, dict):
            continue
        if isinstance(step.get("after_result"), dict):
            pending.append(step["after_result"])
        name, args = step.get("api_name"), step.get("args")
        tool = context.get("tools",{}).get(name,{})
        if not isinstance(args, dict) or not str(name).startswith("search") or tool.get("kind") != "read_only":
            continue
        bound = step.get("result_bindings") or {}
        invented = set()
        for key, value in args.items():
            spec = tool.get("args",{}).get(key)
            if not isinstance(spec, dict) or not spec.get("required") or key in bound or isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                spoken = str(int(value)) if float(value).is_integer() else str(value)
                if not _mentions_value(tool, key, spoken, text):
                    invented.add(key)
            elif isinstance(value, str) and not value.strip():
                invented.add(key)
        trial = {k: v for k, v in args.items() if k not in invented}
        # Only while a stated required filter remains; the removed ones must be eligible.
        if invented and invented <= set(unstated_search_filters(name, tool, trial)):
            step["args"] = trial
    return decision


def complete_truncated_identifiers(decision, context):
    """An identifier the model cut short takes the one complete spoken spelling.

    "The order ID is Q, R, S, 4, 5, 6" with order_id "Q" -> "QRS456"; "T three three four
    four" with "3344" -> "T3344". Only when exactly one spelled run in the current
    turn contains the value as a contiguous part; literal/verbatim requests are
    left untouched. The write gate still checks the completed value.
    """
    from participant.authorization import identifier_field, spelled_runs
    text = " ".join(str(m.get("payload",{}).get("text","")) for m in context.get("messages",[])[context.get("current_turn_start",0):])
    if re.search(r"\b(?:literal|verbatim|comma|commas|spaces|quoted|exactly)\b",text,re.I):
        return decision
    runs = spelled_runs(text)
    # Spelling-alphabet words the user defined ("v as in vector") name their letter.
    alphabet = {word: letter for letter, word in re.findall(r"\b([a-z])\s+as\s+in\s+([a-z]+)\b", text.casefold())}
    pending = list(decision.get("tool_calls",[]))
    while pending:
        step = pending.pop()
        if not isinstance(step, dict):
            continue
        if isinstance(step.get("after_result"), dict):
            pending.append(step["after_result"])
        tool = context.get("tools",{}).get(step.get("api_name"),{})
        if not isinstance(step.get("args"), dict):
            continue
        for name, value in list(step["args"].items()):
            if not isinstance(value, str) or not identifier_field(name, tool.get("args",{}).get(name)):
                continue
            tokens = [token for token in re.split(r"[\s,\-]+", value.casefold()) if token]
            compact = "".join(alphabet.get(token, _SPOKEN_DIGITS.get(token, token)) for token in tokens)
            if not re.fullmatch(r"[a-z0-9]+", compact):
                continue
            if compact in runs:
                if any(token in alphabet for token in tokens):
                    step["args"][name] = compact.upper()  # "vector-7-7" -> V77
                continue
            containing = [run for run in runs if compact in run]
            if len(containing) == 1:
                step["args"][name] = containing[0].upper()
    return decision


def normalize_write_identifiers(decision, context, include_reads=False):
    """Compact a write identifier the model copied as its spoken spelling ("m four" -> "M4").

    Representation only, never new authority: the compact form must equal one
    complete spoken spelling in the current turn (the write gate re-checks it and
    rejects truncations), and literal/verbatim requests are left untouched.
    """
    from participant.authorization import identifier_field, spelled_runs
    text = " ".join(str(m.get("payload",{}).get("text","")) for m in context.get("messages",[])[context.get("current_turn_start",0):])
    if re.search(r"\b(?:literal|verbatim|comma|commas|spaces|quoted|exactly)\b",text,re.I):
        return decision
    runs = spelled_runs(text)
    pending = list(decision.get("tool_calls",[]))
    while pending:
        step = pending.pop()
        if not isinstance(step, dict):
            continue
        if isinstance(step.get("after_result"), dict):
            pending.append(step["after_result"])
        tool = context.get("tools",{}).get(step.get("api_name"),{})
        if (tool.get("kind") != "state_modifying" and not include_reads) or not isinstance(step.get("args"), dict):
            continue
        for name, value in list(step["args"].items()):
            if not isinstance(value, str) or not identifier_field(name, tool.get("args",{}).get(name)):
                continue
            # "s_two" / "item_b7": underscores separate spoken parts too, and a leading
            # type word is not part of the identifier.
            head = re.sub(r"^(?:item|product|order|id|number)[\s_\-]+", "", value.strip(), flags=re.I)
            tokens = [token for token in re.split(r"[\s,\-_]+", head) if token]
            if (not tokens or (len(tokens) < 2 and head == value.strip())
                    or not any(re.search(r"[A-Za-z]", token) for token in tokens)
                    or any(not re.fullmatch(r"[A-Za-z]{1,2}\d*|\d+", token) and token.casefold() not in _SPOKEN_DIGITS
                           for token in tokens)):
                continue
            compact = "".join(_SPOKEN_DIGITS.get(token.casefold(), token.upper()) for token in tokens)
            if compact != value and compact.casefold() in runs:
                step["args"][name] = compact
    return decision


def load_contract(runtime: Path):
    """Read only the public tool declarations, never scenario definitions."""
    tree = ast.parse((runtime / "cascaded_agent.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AssistantFnc")
    types = {"str": "string", "float": "number", "int": "integer"}
    tools = {}
    for fn in cls.body:
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        description = next(ast.literal_eval(k.value) for d in fn.decorator_list
                           if isinstance(d, ast.Call) for k in d.keywords if k.arg == "description")
        params = fn.args.args[1:]
        required = len(params) - len(fn.args.defaults)
        args = {p.arg: {"type": types[p.annotation.id], "required": i < required}
                for i, p in enumerate(params)}
        for p, default in zip(params[required:], fn.args.defaults):
            value = ast.literal_eval(default)
            if value is not None:  # A None default means "absent", not a value to send.
                args[p.arg]["default"] = value
        for line in (ast.get_docstring(fn) or "").splitlines():
            match = re.match(r"\s*(\w+):\s*(.+)", line)
            if match and match[1] in args:
                args[match[1]]["description"] = match[2]
        tools[fn.name] = {"kind": "state_modifying" if fn.name in WRITES else "read_only",
                          "description": description, "args": args,
                          "delay_range_ms": [0, 3000]}
    if len(tools) != 12 or not WRITES <= tools.keys():
        raise ValueError("Unexpected pinned FDB tool contract")
    return tools


def contract_prompt(tools):
    """Recognition vocabulary from the public tool contract only.

    Tool names and the examples quoted in argument descriptions ("platinum",
    "EUR", "BOB12"); never scenario text. Used as the ASR initial prompt.
    """
    terms, seen = [], set()
    for name, tool in tools.items():
        for term in [name] + [example for spec in tool.get("args", {}).values()
                              for example in re.findall(r"'([^']+)'", str(spec.get("description", "")))]:
            term = term.replace("_", " ")
            if term.casefold() not in seen:
                seen.add(term.casefold())
                terms.append(term)
    return ", ".join(terms) + "."


def load_registry(runtime: Path, latency="instant"):
    # The isolated runtime directory contains only these two upstream modules
    # and the public template. No dataset/report path is passed to the agent.
    for name in ("latency_injector", "mock_apis"):
        spec = importlib.util.spec_from_file_location(name, runtime / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules["mock_apis"].MockAPIRegistry(latency_profile=latency)


def planner_view(context):
    """Bound obsolete transcript in model input, retaining authoritative state.

    The controller retains its full audit/operation ledger. Never truncate the
    current request or unresolved outcomes to squeeze them into a model window.
    """
    view = deepcopy(context)
    messages = view.get('messages', [])
    start = view.get('current_turn_start', 0)
    cutoff = max(0, start - 4)
    if cutoff:
        view['messages'] = messages[cutoff:]
        view['history_summary'] = {
            'omitted_prior_messages': cutoff,
            'retained_state': 'state contains active constraints; actions contains the complete outcome ledger',
            'indexing': 'message_index fields and current_turn_start remain original controller indices'}
    return view


MAX_CONTINUATION_DEPTH = 3  # Matches ParticipantAgent._dispatch, which refuses depth > 3.


def argument_schema(descriptor, depth=0):
    """Declared type, enum and nesting of one argument; unknown shapes stay generic."""
    if isinstance(descriptor, str):
        descriptor = {'type': descriptor}
    if not isinstance(descriptor, dict) or depth > 6:
        return {}
    kind = descriptor.get('type')
    schema = {'type': kind} if kind in {'string', 'number', 'integer', 'boolean', 'array', 'object'} else {}
    if isinstance(descriptor.get('enum'), list) and descriptor['enum']:
        schema['enum'] = deepcopy(descriptor['enum'])
    if kind == 'object' and isinstance(descriptor.get('properties'), dict):
        schema['properties'] = {name: argument_schema(child, depth + 1)
                                for name, child in descriptor['properties'].items()}
        schema['additionalProperties'] = False
    if kind == 'array' and 'items' in descriptor:
        schema['items'] = argument_schema(descriptor['items'], depth + 1)
    return schema


def proposal_schema(tools, message_indices=None, clause_ids=None, result_call_ids=None, slot_names=None,
                    retain_call_ids=None):
    """Constrain proposal structure, never manufacture authorization or values.

    Each declared tool gets its own step variant with its argument names and
    types. Required arguments are deliberately not forced by the grammar: a
    bound argument may legitimately come from a result, and forcing presence
    would push a local model to guess values. The controller still rejects any
    missing, undeclared or ill-typed argument after bindings (validate_args).
    With clause_ids, a write cites existing current-turn clause IDs instead of
    regenerating a quote, so a fabricated citation cannot be generated. With
    retain_call_ids, retain_call_id can only name a retainable in-flight read
    (and is absent when there is none), never "null" or a clause ID.
    """
    variants, continuations = [], []
    for name in sorted(tools):
        tool = tools[name]
        kind = tool.get('kind')
        if kind not in {'read_only', 'state_modifying'}:
            continue
        declared = tool.get('args') if isinstance(tool.get('args'), dict) else None
        if declared is None:
            args, bindings, result_bindings = {'type': 'object'}, {'type': 'object'}, {'type': 'object'}
        else:
            args = {'type': 'object', 'properties': {arg: argument_schema(spec) for arg, spec in declared.items()},
                    'additionalProperties': False}
            bindings = {'type': 'object', 'properties': {arg: {'type': 'string'} for arg in declared},
                        'additionalProperties': False}
            call_id = ({'type': 'string', 'enum': sorted(set(result_call_ids))} if result_call_ids
                       else {'type': 'string'})
            result_bindings = {'type': 'object', 'properties': {arg: {
                'type': 'object', 'properties': {'call_id': call_id, 'path': {'type': 'string'}},
                'required': ['call_id', 'path'], 'additionalProperties': False} for arg in declared},
                'additionalProperties': False}
        properties = {'api_name': {'type':'string','enum':[name]}, 'args': args,
            'response_template': {'type':'string'},
            'after_result': {'$ref':'#/$defs/continuation_step'},
            'result_bindings': result_bindings, 'result_evidence': {'type':'object'},
            'refresh': {'type':'boolean'}, 'retain_call_id': {'type':'string'}}
        if result_call_ids is not None and not result_call_ids:
            # No delivered success exists yet: nothing can be bound by call ID.
            del properties['result_bindings']
        if retain_call_ids is not None:
            if retain_call_ids:
                properties['retain_call_id'] = {'type': 'string', 'enum': sorted(set(retain_call_ids))}
            else:
                del properties['retain_call_id']
        required = ['api_name','args','response_template']
        if kind == 'state_modifying':
            if clause_ids is not None:
                properties['authorization'] = {'type': 'object', 'properties': {'clauses': {
                    'type': 'array', 'minItems': 1, 'maxItems': 12,
                    'items': {'type': 'string', 'enum': sorted(set(clause_ids))} if clause_ids else {'type': 'string'}}},
                    'required': ['clauses'], 'additionalProperties': False}
            else:
                properties['authorization'] = {'type':'object', 'properties':{
                    'quote': {'type':'string','minLength':4}, 'message_index': {'type':'integer','minimum':0}},
                    'required':['quote'], 'additionalProperties':False}
                if message_indices is not None:
                    if message_indices:
                        properties['authorization']['properties']['message_index']['enum'] = sorted(set(message_indices))
                    else:
                        del properties['authorization']['properties']['message_index']
            required.append('authorization')
        variants.append({'type':'object','properties':properties,'required':required,'additionalProperties':False})
        # select/bindings only mean something on a continuation of an actual result.
        continued = dict(properties, select={'type':'object', 'properties': {'path': {'type': 'string'},
                         'where': {'type': 'object'}}, 'required': ['path', 'where'], 'additionalProperties': False},
                         bindings=bindings)
        continuations.append({'type':'object','properties':continued,'required':required,'additionalProperties':False})
    # Chains are unrolled to the controller's depth limit, so the grammar cannot
    # generate a runaway after_result chain that exhausts the context window.
    root_ref = '#/$defs/continuation_step_1'
    for variant in variants:
        variant['properties']['after_result'] = {'$ref': root_ref}
    levels = {}
    for level in range(1, MAX_CONTINUATION_DEPTH + 1):
        steps = deepcopy(continuations)
        for step in steps:
            if level < MAX_CONTINUATION_DEPTH:
                step['properties']['after_result'] = {'$ref': f'#/$defs/continuation_step_{level + 1}'}
            else:
                del step['properties']['after_result']
        levels[f'continuation_step_{level}'] = {'oneOf': steps}
    # With slot_names, state slots are limited to declared argument names so an
    # unconstrained object cannot consume the context with invented fields.
    slots = ({'type': 'object', 'properties': {name: {} for name in sorted(set(slot_names))}, 'additionalProperties': False}
             if slot_names is not None else {'type': 'object'})
    schema = {'type':'object','properties':{
        'intent': {'type':'string'}, 'slots': slots,
        'tool_calls': {'type':'array','maxItems':4 if variants else 0,
                       'items': {'$ref':'#/$defs/tool_step'} if variants else {}},
        'response': {'type':['string','null']}, 'clarification': {'type':['string','null']}},
        'required':['intent','slots','tool_calls'], 'additionalProperties':False}
    if variants:
        schema['$defs'] = {'tool_step': {'oneOf':variants}, **levels}
    return schema


PLANNER_GUIDANCE_V2 = (
    '\nComplete every request the user actually makes in this turn. A reported ("she said"), hypothetical, '
    'conditional, negated or cancelled command is not a request: plan no call for it, and still plan the '
    "user's own remaining request (for example a lookup asked in the same turn). "
    'Call the tool that directly does what the user asked when its required arguments are supplied; do not add '
    'searches or lookups the user did not ask for, since every extra call is an error. '
    'Argument values are just the field value: take names and values from the user\'s words, do not invent '
    'synonyms or repeat the parameter\'s own noun (bill_type "water", not "water bill"). If a required value was '
    'not said, ask instead of guessing.')


# Guidance 3: only two targeted sentences (multi-action coverage, direct calls),
# so they can be tested without the rest of the v2 bundle.
PLANNER_GUIDANCE_V3 = (
    '\nEmit one tool call per requested action in the same plan, including several calls of the same tool '
    'with different arguments (for example two documents or two orders). Call the tool that directly does '
    'what the user asked when its required arguments are supplied; do not add a lookup the user did not ask for.')


class LocalPlanner:
    """Existing THREAD proposal format via an explicitly local OpenAI-compatible API."""
    timeout = 180.0
    # Writes cite controller-segmented clause IDs (enum-constrained), not regenerated quotes.
    clause_citations = True

    def __init__(self, endpoint, model, model_journal=None):
        parsed = urlparse(endpoint)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Zero-spend route requires a loopback HTTP endpoint")
        self.endpoint, self.model = endpoint.rstrip("/"), model
        self.requests = []
        self.client = None
        self.assistant_playback = []
        self.model_journal = model_journal
        # Reuse KV only within this scenario (one planner per scenario). Before the
        # first cached request after another scenario used the server, every server
        # slot is erased; if that cannot be confirmed, the request runs uncached.
        # Explicit and recorded per request; off by default.
        self.prompt_cache = os.environ.get("THREAD_FDB3_PROMPT_CACHE", "0") == "1"
        self.cache_owner = uuid.uuid4().hex
        self.cache_owner_file = Path(os.environ.get("THREAD_FDB3_CACHE_OWNER_FILE") or Path(
            os.environ.get("TEMP") or os.environ.get("TMPDIR") or "/tmp")
            / f"thread-fdb3-cache-owner-{parsed.port or 80}")
        # Versioned general planning guidance; 1 = none (earlier runs), 2 = PLANNER_GUIDANCE_V2,
        # 3 = PLANNER_GUIDANCE_V3 only.
        self.guidance = int(os.environ.get("THREAD_FDB3_PLANNER_GUIDANCE", "1"))
        # Bounded follow-up planning after results settle. Independent of guidance so
        # it can be tested alone; unset keeps the earlier coupling (on only with v2).
        follow_up = os.environ.get("THREAD_FDB3_FOLLOW_UP")
        self.follow_up_rounds = (2 if follow_up == "1" else 0) if follow_up in {"0", "1"} \
            else (2 if self.guidance >= 2 else 0)
        # Argument representation repairs (heard identifier spelling for every tool,
        # unstated optional numbers dropped); a separate switch so it is tested alone.
        self.arg_normalize = os.environ.get("THREAD_FDB3_ARG_NORMALIZE", "0") == "1"
        self._model_journal_lock = threading.Lock()

    async def setup(self):
        self.client = httpx.AsyncClient(timeout=self.timeout, trust_env=False)

    async def close(self):
        if self.client:
            await self.client.aclose()

    async def _scenario_cache(self):
        """Return True only when server KV can hold nothing from another scenario."""
        if not self.prompt_cache:
            return False
        try:
            owner = self.cache_owner_file.read_text(encoding='utf-8').strip()
        except OSError:
            owner = ''
        if owner == self.cache_owner:
            return True
        base = self.endpoint.removesuffix('/v1')
        try:
            slots = await self.client.get(base + '/slots')
            slots.raise_for_status()
            ids = [row['id'] for row in slots.json()]
            if not ids:
                return False
            for slot in ids:
                erased = await self.client.post(f'{base}/slots/{slot}?action=erase')
                erased.raise_for_status()
            self.cache_owner_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_owner_file.write_text(self.cache_owner, encoding='utf-8')
            return True
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError):
            return False

    def _write_checkpoint(self, phase, request):
        with self._model_journal_lock:
            with Path(self.model_journal).open('a', encoding='utf-8') as handle:
                handle.write(json.dumps({'phase': phase, 'recorded_at': time.time(),
                                         'request': request}) + '\n')
                handle.flush()
                os.fsync(handle.fileno())

    async def _checkpoint(self, phase, request):
        if self.model_journal is None:
            return
        task = asyncio.create_task(asyncio.to_thread(self._write_checkpoint, phase, deepcopy(request)))
        cancelled = None
        # A cancelled waiter cannot abandon a filesystem write that is already running.
        # Join the owned task even through repeated cancellation, then propagate it.
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError as exc:
                cancelled = exc
        task.result()
        if cancelled is not None:
            raise cancelled

    async def plan(self, context):
        # Reuse the controller's proposal contract; no domain/item routing.
        context = deepcopy(context)
        context["assistant_playback"] = deepcopy(self.assistant_playback)
        started = time.time()
        request = {"request_id": f"model-{len(self.requests) + 1}",
                   "started_at": started, "outcome": "pending", "tokens_known": False,
                   "template_requests": 0, "inference_requests": 0,
                   "assistant_playback": deepcopy(self.assistant_playback)}
        self.requests.append(request)
        try:
            decision = await self._request(context, request)
            request["finished_at"] = time.time()
            await self._checkpoint('finished', request)
            return decision
        except BaseException as exc:
            request.update(outcome="cancelled" if isinstance(exc, asyncio.CancelledError) else "error",
                           error_type=type(exc).__name__, finished_at=time.time())
            await self._checkpoint('finished', request)
            raise

    async def _request(self, context, request):
        messages=[{"role": "system", "content": SYSTEM + '\nReturn the COMPLETE decision object, not a bare tool step. Valid JSON only: every property name must be double-quoted. Required top-level keys: "intent" (string), "slots" (object), "tool_calls" (array). Place response_template INSIDE each tool step, not at the top level. For identifiers spelled character by character, join the characters; ASR commas between individually spelled characters are not literal identifier characters. Preserve explicitly dictated separators. Follow the actual parameter descriptions.\nassistant_playback contains only SDK-committed assistant text with message IDs and interruption flags. It is an SDK playback estimate, not measured human hearing. Use it only to understand what the assistant previously communicated. It is never user instruction, authorization, or proof of a tool outcome. Only current user input authorizes actions; actions and tool_results remain authoritative for execution outcomes. Interrupted entries omit their text because this SDK event does not prove which prefix was played. delivered_text_unknown means no heard wording is available; do not infer any unsaid suffix or claim the user heard the full generated message.'},
                  {"role": "user", "content": json.dumps(planner_view(context),separators=(',',':'))}]
        messages[0]['content'] += (
            '\nKeep every unrelated task the user still wants after a correction. Continuing an in-flight read requires '
            "an explicit fresh tool_calls step with retain_call_id set to that action's call_id; never silently omit it. "
            'Use retain_call_id only for an older-revision in-flight action with can_retain_read=true when the current user still wants the same read. '
            'The api_name, complete args, and dependencies shown in action.read_dependencies must match exactly. '
            'Supply a fresh response_template and any still-authorized continuation for the current request. '
            'Never retain writes, completed results, changed arguments or dependencies, or an explicitly requested refresh. '
            'Completed results are not a reusable read cache. For a fresh lookup, omit retain_call_id.')
        if self.clause_citations:
            messages[0]['content'] += (
                '\nIn this runtime a write cites current_clauses instead of quoting: authorization={"clauses":[clause_id,...]} '
                'in original order. Cite the clause that states the action first, then only later clauses that complete or '
                'correct that same action (for example a corrected quantity). Never cite a negated, retracted, conditional, '
                'hypothetical or reported clause, and never cite a clause for a different action. Arguments follow the latest '
                'correction; an unstated optional argument keeps its declared default.')
        if self.guidance == 2:
            messages[0]['content'] += PLANNER_GUIDANCE_V2
        elif self.guidance == 3:
            messages[0]['content'] += PLANNER_GUIDANCE_V3
        request.update(protocol='llama.cpp native JSON schema',template_requests=1,cache_prompt=self.prompt_cache,
                       cache_scope='scenario',planner_guidance=self.guidance,follow_up_rounds=self.follow_up_rounds,
                       arg_normalize=self.arg_normalize,
                       template_intents=1,inference_requests=0)
        try:
            await self._checkpoint('template_pending', request)
        except BaseException:
            request['template_requests'] = 0
            raise
        rendered=await self.client.post(self.endpoint.removesuffix('/v1')+'/apply-template',json={
            'messages':messages,'chat_template_kwargs':{'enable_thinking':False}})
        rendered.raise_for_status()
        # The installed chat endpoint ignored response_format. Native grammar
        # constrains syntax at generation time; do not repair malformed JSON.
        # Cite only current controller indices, never the example's literal 0 or
        # positions in the compacted prompt. Omission still permits spanning quotes.
        indices = [row.get('message_index',index) for index,row in enumerate(context.get('messages',[]))
                   if type(row.get('message_index',index)) is int
                   and row.get('message_index',index) >= context.get('current_turn_start',0)]
        clause_ids = [row.get('clause_id') for row in context.get('current_clauses', [])
                      if isinstance(row, dict) and isinstance(row.get('clause_id'), str)]
        delivered = [row.get('call_id') for row in context.get('actions', [])
                     if isinstance(row, dict) and row.get('status') == 'success' and isinstance(row.get('call_id'), str)]
        # Slots stay unconstrained: held-out-003 showed that listing every argument name
        # as a slot key made the model fill all of them and run away.
        retainable = [row.get('call_id') for row in context.get('actions', [])
                      if isinstance(row, dict) and row.get('can_retain_read') is True and isinstance(row.get('call_id'), str)]
        schema = proposal_schema(context.get('tools',{}), indices, clause_ids if self.clause_citations else None,
                                 delivered, retain_call_ids=retainable)
        prompt = rendered.json()['prompt']
        if not isinstance(prompt, str):
            raise ValueError('Local template must return a prompt string')
        request.update(inference_requests=1, inference_intents=1)
        try:
            await self._checkpoint('completion_pending', request)
        except BaseException:
            # The pending journal conservatively records intent for crash recovery.
            # A caught checkpoint failure proves this HTTP request was never issued.
            request['inference_requests'] = 0
            raise
        cached = await self._scenario_cache()
        request['cache_prompt'] = cached
        response = await self.client.post(self.endpoint.removesuffix('/v1')+'/completion',json={
            'prompt':prompt,'temperature':0,'n_predict':1800,
            'json_schema':schema,'cache_prompt':cached})
        if cached:
            try:
                # Scenarios run sequentially; record any overlap rather than assume it away.
                request['cache_boundary_overlap'] = (
                    self.cache_owner_file.read_text(encoding='utf-8').strip() != self.cache_owner)
            except OSError:
                request['cache_boundary_overlap'] = True
        request["http_status"] = response.status_code
        response.raise_for_status()
        body = response.json()
        content = body['content']
        usage={'prompt_tokens':body['tokens_evaluated'],'completion_tokens':body['tokens_predicted'],
               'total_tokens':body['tokens_evaluated']+body['tokens_predicted'],
               'cached_tokens':body.get('timings',{}).get('cache_n')}
        request.update(usage=usage,tokens_known=True,content=content,returned_model=body.get('model'),
                       finish_reason=body.get('stop_type'),timings=body.get('timings'),
                       truncated=body.get('truncated'),prompt_characters=len(prompt))
        if body.get('truncated') is True:
            raise ValueError('Local model exhausted its context; incomplete proposal rejected')
        decision, dropped = parse_decision(content)
        if dropped:
            request["slots_dropped_for_repeated_keys"] = True
        decision = normalize_read_identifiers(decision,context)
        decision = normalize_write_identifiers(decision,context,include_reads=self.guidance >= 2 or self.arg_normalize)
        if self.guidance >= 2 or self.arg_normalize:
            decision = normalize_heard_identifiers(decision,context)
        if self.arg_normalize:
            decision = complete_truncated_identifiers(decision,context)
            decision = strip_type_head_noun(decision,context)
            decision = strip_vague_praise(decision,context)
            decision = restore_first_person(decision,context)
            decision = restore_user_case(decision,context)
            decision = drop_unstated_optional_numbers(decision,context)
            decision = drop_unstated_search_filters(decision,context)
            decision = fill_declared_write_defaults(decision,context)
        request["outcome"] = "success"
        return decision


ACK_TEXT = "One moment, checking that now."


class ControllerBridge:
    """One controller/ledger per conversation, with owned execution tasks."""
    def __init__(self, tools, registry, planner):
        self.incoming, self.outgoing = asyncio.Queue(), asyncio.Queue()
        self.controller = ParticipantAgent(self.incoming, self.outgoing, planner=planner)
        self.tools, self.registry = tools, registry
        self.calls, self.events = [], []
        self.voice_events = []
        self._assistant_playback = {}
        self._assistant_playback_receipts = {}
        self.executions = {}
        self.outputs = asyncio.Queue()
        self.tasks = []
        self.blocked_through_revision = -1
        self.admission_lock = threading.Lock()
        self.last_output_revision = -1
        self.input_sequence = 0
        self._audio_segment = None
        self._audio_segment_epoch = None
        self._speech_message_sources = {}
        self.speech_provenance_required = False
        self._empty_resolved_through = -1
        self.closing = False
        self.tool_journal = None
        self.journal_lock = threading.Lock()
        self.evidence_errors = []
        # One logical user turn spans paused speech segments until an answer is
        # delivered or a text instruction arrives. Segment -> turn provenance is immutable.
        self._logical_turn = None
        self._logical_turn_open = False
        self._segment_turns = {}
        # Optional early acknowledgement (seconds after an admitted turn with no answer
        # yet and no new speech). Off unless THREAD_FDB3_ACK_AFTER is set.
        try:
            self.ack_after = float(os.environ.get("THREAD_FDB3_ACK_AFTER") or 0) or None
        except ValueError:
            self.ack_after = None

    def _input_started(self):
        # Optional device registry callback is local state only, never I/O.
        self.input_sequence += 1
        callback = getattr(self.registry,"input_started",None)
        if callback is not None:
            callback(self.input_sequence)

    async def start(self):
        self.tasks = [asyncio.create_task(self.controller.run()), asyncio.create_task(self._pump())]
        await self.incoming.put({"event_type": "tool_manifest", "payload": {"tools": self.tools}})

    def speech_started(self, segment_id=None):
        # Invalidates pending proposals immediately, before the next final ASR.
        with self.admission_lock:
            self.blocked_through_revision = max(self.blocked_through_revision,self.controller.revision)
            self._input_started()
            self._audio_segment = segment_id
            self._audio_segment_epoch = self.input_sequence
            if not self._logical_turn_open:
                self._logical_turn, self._logical_turn_open = uuid.uuid4().hex, True
            if segment_id is not None:
                self._segment_turns.setdefault(segment_id, self._logical_turn)
            turn = self._logical_turn
            # Queue under the lock so onset/context/final order matches decisions.
            self.incoming.put_nowait({"event_type": "interruption", "payload": {"text": "", "logical_turn": turn}})
        return self.input_sequence

    def close_logical_turn(self):
        with self.admission_lock:
            self._logical_turn_open = False

    def retain_context(self, sequence, segment_id, text):
        """Admit a late-decoded earlier segment of the open turn as context only.

        It keeps its own segment provenance, never plans or authorizes by itself,
        and is refused once its turn closed or when it belongs to another turn.
        """
        with self.admission_lock:
            turn = self._segment_turns.get(segment_id)
            if (self.closing or not isinstance(text, str) or not text.strip() or turn is None
                    or not self._logical_turn_open or turn != self._logical_turn):
                self.voice_events.append({'event': 'speech_context_refused', 'at': time.time(),
                                          'segment_id': segment_id, 'input_sequence': sequence})
                return False
            self.incoming.put_nowait({"event_type": "user_speech_chunk", "payload": {
                "text": text, "end_of_turn": False, "context_only": True, "logical_turn": turn,
                "segment_id": segment_id}})
            self.voice_events.append({'event': 'speech_context_retained', 'at': time.time(),
                                      'segment_id': segment_id, 'input_sequence': sequence, 'logical_turn': turn})
            return True

    def current_audio_segment(self, sequence, segment_id):
        return (not self.closing and self.input_sequence == sequence
                and self._audio_segment == segment_id and segment_id is not None)

    def current_speech_source(self, sequence, segment_id):
        """VAD identity survives its own transcript submission's counter increment."""
        return (not self.closing and self._audio_segment_epoch == sequence
                and self._audio_segment == segment_id and segment_id is not None)

    def bind_speech_message(self, message_id, text, sources):
        if message_id in self._speech_message_sources or not sources:
            return False
        self._speech_message_sources[message_id] = (text, tuple(sources))
        return True

    async def resolve_empty_speech(self, sequence, segment_id):
        """Resolve only an explicitly empty successful decode of the current segment."""
        await self.synchronize()
        if not self.current_audio_segment(sequence, segment_id) or sequence <= self._empty_resolved_through:
            return False
        self._empty_resolved_through = sequence
        self.last_output_revision = self.controller.revision
        self.close_logical_turn()
        self.voice_events.append({'event': 'empty_speech_resolved', 'at': time.time(),
                                  'segment_id': segment_id, 'input_sequence': sequence})
        return True

    async def submit(self, text, *, speech_message_id=None):
        with self.admission_lock:
            payload = {"text": text, "end_of_turn": True}
            if speech_message_id is not None:
                source = self._speech_message_sources.pop(speech_message_id, None)
                # The newest source must be the current segment. SDK aggregation may
                # prefix earlier segments, admitted only when they belong to the same
                # still-open logical turn; any other mixed provenance is refused.
                if source is None:
                    detail = 'unbound_or_replayed_message'
                elif source[0] != text:
                    detail = 'text_differs_from_bound_segments'
                elif not source[1] or not self.current_speech_source(*source[1][-1]):
                    detail = 'newest_segment_not_current'
                elif not all(self.current_speech_source(*token) or (
                        self._logical_turn_open and self._segment_turns.get(token[1]) == self._logical_turn)
                        for token in source[1][:-1]):
                    detail = 'earlier_segment_outside_open_turn'
                else:
                    detail = None
                # SDK endpointing can commit a segment only after the next onset. Words
                # of the still-open turn stay as context for its next fresh decision,
                # like a late decode; they never plan or authorize by themselves.
                retained = (detail == 'newest_segment_not_current' and not self.closing
                            and self._logical_turn_open and self._logical_turn is not None
                            and all(self._segment_turns.get(token[1]) == self._logical_turn
                                    for token in source[1]))
                if detail is not None:
                    self.voice_events.append({'event': 'speech_admission_rejected', 'at': time.time(),
                        'message_id': speech_message_id, 'reason': 'missing_replayed_or_stale_provenance',
                        'detail': detail, 'sources': [list(token) for token in (source[1] if source else ())],
                        'current_segment': [self._audio_segment_epoch, self._audio_segment],
                        'logical_turn_open': self._logical_turn_open,
                        'text_matches': source is not None and source[0] == text,
                        'retained_as_context': retained})
                    if retained:
                        self.incoming.put_nowait({"event_type": "user_speech_chunk", "payload": {
                            "text": text, "end_of_turn": False, "context_only": True,
                            "logical_turn": self._logical_turn, "segment_id": source[1][-1][1]}})
                    return False
                turn = self._segment_turns.get(source[1][-1][1])
                if turn is not None and self._logical_turn_open and turn == self._logical_turn:
                    payload["logical_turn"] = turn
            else:
                # A separately submitted text instruction supersedes audio too.
                self._audio_segment = None
                self._logical_turn_open = False
            self.blocked_through_revision = max(self.blocked_through_revision,self.controller.revision)
            self._input_started()
            self.incoming.put_nowait({"event_type": "user_speech_chunk", "payload": payload})
        return True

    async def _pump(self):
        while True:
            event = await self.outgoing.get()
            self.events.append({**deepcopy(event),'bridge_received_at':time.time()})
            action, payload = event["action"], event["payload"]
            if action == "tool_call":
                task = asyncio.create_task(self._execute(payload, event["state_snapshot"]["revision"]))
                self.executions[payload["call_id"]] = task
            elif action in {"final_response", "clarification_request"}:
                await self.outputs.put(event)
            # Cancel requests retire controller continuations. A thread already
            # calling a backend is not assumed cancelled; always reconcile it.

    async def _execute(self, payload, revision):
        await asyncio.sleep(0)  # Give queued speech/corrections precedence.
        outcome = await asyncio.to_thread(self._invoke, payload, revision)
        if outcome is None:
            await self.incoming.put({"event_type":"tool_not_submitted","payload":{
                "call_id":payload['call_id'],"api_name":payload['api_name']}})
            return
        result, status = outcome
        await self.incoming.put({"event_type": "tool_result", "payload": {
            "call_id": payload["call_id"], "api_name": payload["api_name"], "status": status, "result": result}})

    def _invoke(self, payload, revision):
        # Executor admission is the submission linearization point. Never hold
        # this lock during a blocking backend call: admitted effects reconcile
        # after interruption, while queued effects can still be rejected.
        operation = self.controller.operations[payload["call_id"]]
        with self.admission_lock:
            if (self.closing or revision <= self.blocked_through_revision or revision != self.controller.revision
                    or operation["status"] != "pending"):
                return None
            record = {"function": payload["api_name"], "args": deepcopy(payload["args"]),
                      "call_id": payload["call_id"], "revision": revision,
                      "input_sequence":self.input_sequence,
                      "timestamp_start": time.time(), "timestamp_end": None, "outcome": "unknown"}
        # Flush off the audio thread and outside its admission lock. This is a
        # dispatch intent, not proof of invocation. Recheck after disk I/O: a
        # correction may have arrived while the journal was being persisted.
        self._journal_tool('dispatch_intent',record)
        with self.admission_lock:
            admitted=not (self.closing or revision <= self.blocked_through_revision
                or revision != self.controller.revision or operation['status']!='pending')
            if admitted:
                record['timestamp_start']=time.time()
                operation["execution_admitted"] = True
                self.calls.append(record)
        if not admitted:
            record.update(outcome='not_submitted',timestamp_end=time.time())
            self._journal_tool('not_submitted',record)
            return None
        try:
            contextual_call = getattr(self.registry,"call_with_context",None)
            if contextual_call is not None:
                result = contextual_call(payload["api_name"],deepcopy(payload["args"]),
                    call_id=payload["call_id"],revision=revision,input_sequence=record['input_sequence'])
            else:
                result = self.registry.call(payload["api_name"], **payload["args"])
            status = result.get("status", "success")
            record.update(timestamp_end=time.time(), outcome=status, result=deepcopy(result))
        except Exception as exc:
            result, status = {"status": "error", "error": "backend_exception"}, "error"
            record.update(timestamp_end=time.time(), error_type=type(exc).__name__)
        try:
            self._journal_tool('finished',record)
        except OSError as exc:
            # Preserve known actual outcomes in the actor even if the evidence
            # volume fails. Workers reject this as valid experiment evidence.
            self.evidence_errors.append('tool_journal: '+type(exc).__name__)
        return result, status

    def _journal_tool(self, phase, record):
        if self.tool_journal is None:
            return
        with self.journal_lock:
            with Path(self.tool_journal).open('a',encoding='utf-8') as handle:
                handle.write(json.dumps({'phase':phase,'recorded_at':time.time(),'call':record},default=str)+'\n')
                handle.flush()
                os.fsync(handle.fileno())

    def record_assistant_playback(self, item):
        """Accept only the SDK's committed conversation-item event, never TTS plans."""
        if getattr(item, "type", None) != "message" or getattr(item, "role", None) != "assistant":
            return
        item_id, text, interrupted = (getattr(item, "id", None), getattr(item, "text_content", None),
                                      getattr(item, "interrupted", None))
        if not isinstance(item_id, str) or not item_id or not isinstance(text, str) or type(interrupted) is not bool:
            return
        receipt = {"id": item_id, "text": text, "interrupted": interrupted}
        if self._assistant_playback_receipts.get(item_id) == receipt:
            return
        self._assistant_playback_receipts[item_id] = receipt
        row = deepcopy(receipt)
        if interrupted:
            # Pinned SDK can commit full generated text when no synchronized
            # transcript exists, even after only one audio frame was played.
            row.update(text="", delivered_text_unknown=True)
        self._assistant_playback[item_id] = row
        self.voice_events.append({"event": "assistant_playback_committed", "at": time.time(),
                                  "source": "LiveKit conversation_item_added", "estimate": True,
                                  "human_hearing_verified": False, "sdk_committed_text": text,
                                  **deepcopy(row)})

    async def _acknowledge(self, response_sequence, ack):
        """Speak a fixed holding line if the answer is still pending and the user is quiet.

        Never a result or a completion claim; cancelled as soon as the answer is ready.
        Any new speech onset since admission (input_sequence moved) suppresses it.
        """
        await asyncio.sleep(self.ack_after)
        if not self.closing and self.input_sequence == response_sequence:
            self.voice_events.append({"event": "early_acknowledgement", "at": time.time(),
                                      "text": ACK_TEXT, "after_seconds": self.ack_after})
            ack(ACK_TEXT)

    async def response(self, text, timeout=200, *, chat_items=None, speech_message_id=None, ack=None):
        # Reject stale speech before it can clear current outputs or replace the
        # planner's playback context. Submission and provenance check are atomic.
        if not await self.submit(text, speech_message_id=speech_message_id):
            return ""
        # Chat snapshots select the relevant committed IDs. Stored receipts supply
        # text so an older/full snapshot cannot restore an interrupted suffix.
        playback = []
        seen = set()
        for item in chat_items or []:
            item_id = getattr(item, "id", None)
            if (getattr(item, "type", None) == "message" and getattr(item, "role", None) == "assistant"
                    and isinstance(item_id, str) and item_id not in seen and item_id in self._assistant_playback):
                playback.append(deepcopy(self._assistant_playback[item_id]))
                seen.add(item_id)
        if self.controller.planner is not None:
            self.controller.planner.assistant_playback = playback
        while not self.outputs.empty():
            self.outputs.get_nowait()
        response_sequence = self.input_sequence
        parts, revision = [], None
        acknowledging = (asyncio.create_task(self._acknowledge(response_sequence, ack))
                         if ack is not None and self.ack_after else None)
        try:
            return await self._await_answer(response_sequence, parts, revision, timeout)
        finally:
            if acknowledging is not None:
                acknowledging.cancel()

    async def _await_answer(self, response_sequence, parts, revision, timeout):
        async with asyncio.timeout(timeout):
            while True:
                if response_sequence <= self._empty_resolved_through:
                    self.close_logical_turn()
                    return ""  # Terminal retirement, never restore an obsolete answer.
                if revision != self.controller.revision or self.controller.revision <= self.blocked_through_revision:
                    parts, revision = [], self.controller.revision
                while not self.outputs.empty():
                    event = self.outputs.get_nowait()
                    if (event["state_snapshot"]["revision"] == self.controller.revision
                            and self.controller.revision > self.blocked_through_revision):
                        parts.append(event["payload"])
                pending = self.controller._plan_task is not None or any(
                    op['revision'] == self.controller.revision and op['status'] == 'pending'
                    for op in self.controller.operations.values())
                # A controller turn can emit several terminal read results and
                # a clarification. One LLM stream must carry all current output.
                if parts and not pending and self.incoming.empty() and self.outgoing.empty():
                    self.last_output_revision = self.controller.revision
                    self.close_logical_turn()  # The answer ends this logical turn.
                    # Calls can finish in a different order from dispatch. Keep
                    # every receipt once, in call order, without moving unrelated
                    # clarifications or generating a new summary from model prose.
                    order = {call_id: index for index, call_id in enumerate(self.controller.operations)}
                    receipts = iter(sorted((part for part in parts if part.get("call_id") in order),
                                           key=lambda part: order[part["call_id"]]))
                    return " ".join((next(receipts) if part.get("call_id") in order else part)["text"] for part in parts)
                await asyncio.sleep(.01)

    async def synchronize(self):
        if not self.tasks:
            return
        if self.tasks[0].done():
            if self.tasks[0].cancelled():
                return
            error = self.tasks[0].exception()
            if error is not None:
                raise error
            return
        ready = asyncio.Event()
        await self.incoming.put({'event_type':'controller_barrier','payload':{'ready':ready}})
        await asyncio.wait_for(ready.wait(),5)

    async def close(self):
        with self.admission_lock:
            self.closing = True
        while True:
            if self.executions:
                await asyncio.gather(*self.executions.values())
            await self.synchronize()
            await asyncio.sleep(0)  # Let the output pump admit any queued receipts.
            if self.tasks and self.tasks[0].done() and not self.incoming.empty():
                raise RuntimeError('Controller stopped before reconciling queued receipts')
            if all(task.done() for task in self.executions.values()) and self.outgoing.empty() and self.incoming.empty():
                break
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)


def sha256(path):
    with open(path, "rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


async def wait_until_settled(session, recognizer, bridge, *, timeout=250, settle=5.5):
    """Do not finish on an older reply while the last input is still recognized.

    The settle interval exceeds this adapter's maximum VAD endpointing delay.
    This is diagnostic shutdown policy, not an official response-time window.
    """
    began=time.monotonic()
    async with asyncio.timeout(timeout):
        while True:
            latest=max(began,recognizer.last_activity_at)
            if (time.monotonic()-latest >= settle and recognizer.active_recognitions == 0
                    # The SDK reports a silent user as "away" after its idle timeout
                    # (15 s); that is settled, not speech, and must not stall shutdown.
                    and session.user_state in {"listening", "away"} and session.agent_state == "listening"
                    and bridge.controller._plan_task is None
                    and all(task.done() for task in bridge.executions.values())
                    and bridge.last_output_revision == bridge.controller.revision
                    and bridge.controller.revision > bridge.blocked_through_revision):
                return
            await asyncio.sleep(.05)
