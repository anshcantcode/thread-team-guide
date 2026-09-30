"""Official-native asynchronous controller.

Only this loop commits state and emits actions. Planning is cancellable background
work; queued input wins a race with a ready plan. Tool names and result shapes are
supplied by the manifest rather than dispatched through application domains.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import json
import re
import time
import unicodedata

from .authorization import (authorization_grant, command_head, contains_identifier, contains_value, count_mentions,
                            identifier_field, natural_count, spelled_runs, turn_clauses, _schema_words,
                            _verified_price_conditions)
from .schema import (argument_question, at_path, call_key, scalar_fields, selected_printed_label, validate_args,
                     with_declared_defaults)
from .presentation import quantitative_template_is_bound
from .spoken import PUBLIC_TOOLS, spoken_result


_ANSWER_FIELDS = {"answer", "instructions", "instruction", "explanation", "guidance",
                  "warning", "warnings", "findings", "paragraphs", "steps"}
_SOURCE_FIELDS = {"sources", "references", "citations", "pages"}
_FOR_TARGET_FIELDS = {"account", "client", "contact", "customer", "employee", "guest",
                      "member", "owner", "passenger", "patient", "person", "user"}
_TO_TARGET_FIELDS = {"destination", "location", "recipient", "target"}
# A user turn that ends on a hold marker ("Uh, wait.", "hold on", "let me think")
# keeps the floor: planning starts after a bounded hold, and new speech cancels it
# as usual. It never delays tool results or follow-up rounds.
_HOLD_MARKER = re.compile(
    r"(?:^|[.!?;,]\s*|\b(?:uh|um|oh|no|so|okay|hmm|and|but)\s*,?\s+)"
    r"(?:wait|hold on|hang on|one sec(?:ond)?|just a sec(?:ond)?|let me (?:think|see|check)|actually|sorry)"
    r"[\s,.!?]*$", re.I)
_NUMBER_LITERAL = re.compile(
    r"(?<![\w.-])[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?(?![\w.-])")
_READ_COMMAND = re.compile(
    r"(?:^|[.!?;,]\s*|\b(?:and|then)\s+)\s*(?:(?:also|please|just|now|first)\s+)*"
    r"(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?|"
    r"i(?:'d| would)\s+like\s+(?:you\s+)?to\s+|i\s+(?:want|need)\s+(?:you\s+)?to\s+)?"
    r"(?:search|find|look|track|check|read|get|show|list|inspect|retrieve)\b", re.I)
_READ_QUESTION = re.compile(r"^\s*(?:what|where|when|how|is|are|has|have|does|do)\b.*\?\s*$", re.I)


def _names_read_target(name, text):
    if not isinstance(name, str):
        return False
    nouns = {word.rstrip("s") for word in re.findall(r"[a-z]+", name.replace("_", " ").lower())
             if word not in {"search", "get", "find", "read", "lookup", "check", "track", "list"}}
    return bool(nouns) and nouns <= {word.rstrip("s") for word in re.findall(r"[a-z]+", text.lower())}


def _edit_distance(first, second):
    """Levenshtein distance between two short words."""
    previous = list(range(len(second) + 1))
    for row, left in enumerate(first, 1):
        current = [row]
        for column, right in enumerate(second, 1):
            current.append(min(previous[column] + 1, current[column - 1] + 1, previous[column - 1] + (left != right)))
        previous = current
    return previous[-1]


def _field_aliases(path):
    parts = path.split(".")
    return {path,
            " ".join(part.replace("_", " ") for part in parts),
            re.sub(r"\.(\d+)(?=\.|$)", r"[\1]", path),
            re.sub(r"\.\d+(?=\.|$)", "", path)}


def _has_exact_field_value(path, value, command):
    found = (_explicit_boolean_field_values(path, command) if type(value) is bool
             else _explicit_numeric_field_values(path, command))
    expected = value if type(value) is bool else Decimal(str(value))
    return found == {expected}


def _supported_primitive(tool, path, value, command):
    """Explicit field=value evidence, or a natural count for a sole integer argument.

    "add two", "two of them" or "make it one" can set the tool's only numeric
    argument when it is an integer. Different earlier counts need a retraction;
    no stated count accepts only the declared default. Everything else stays
    on the explicit field=value path.
    """
    if _has_exact_field_value(path, value, command):
        return True
    properties = tool.get("args", {}) if isinstance(tool, dict) else {}
    numeric = [name for name, spec in properties.items()
               if isinstance(spec, dict) and spec.get("type") in {"integer", "number"}]
    if type(value) is not int or numeric != [path] or properties[path].get("type") != "integer":
        return False
    if _explicit_numeric_field_values(path, command):
        return False  # An explicit different field value is never overridden.
    if count_mentions(command):
        return natural_count(command) == value
    return "default" in properties[path] and type(properties[path]["default"]) is int and properties[path]["default"] == value


_NUMBER_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                 "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
                 "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
                 "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}


def spoken_numbers(text):
    """Complete numeric mentions, never a decimal/sign fragment or a sum across
    punctuation. Unsupported word sequences supply no numeric evidence."""
    found, phrase = set(), []
    text = re.sub(r"\ban?\s+(?=(?:hundred|thousand)\b)", "one ", text.casefold())
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)

    def flush():
        if not phrase:
            return
        tokens = phrase[:]
        phrase.clear()
        while tokens and tokens[-1] == "and":
            tokens.pop()  # "two hundred and then": the "and" joins nothing.
        if not tokens:
            return
        sign = -1 if tokens[0] in {"minus", "negative"} else 1
        if tokens[0] in {"minus", "negative", "plus"}:
            tokens = tokens[1:]
        whole, _, fraction = " ".join(tokens).partition(" point ")
        total = current = 0
        previous = None
        literal_whole = _NUMBER_LITERAL.fullmatch(whole)
        for word in ([] if literal_whole else whole.split()):
            if word in _NUMBER_WORDS:
                value = _NUMBER_WORDS[word]
                if previous in _NUMBER_WORDS and not (_NUMBER_WORDS[previous] >= 20 and 0 < value < 10):
                    return  # "fifty fifty" / "one two" is not their arithmetic sum.
                current += value
            elif word == "hundred" and previous in _NUMBER_WORDS and 0 < current < 100:
                current *= 100
            elif word == "thousand" and 0 < current < 1000 and not total:
                total, current = current * 1000, 0
            elif word == "and" and previous in {"hundred", "thousand"}:
                pass
            else:
                return
            previous = word
        if not literal_whole and (previous is None or previous == "and"):
            return
        value = Decimal(whole) if literal_whole else Decimal(total + current)
        if fraction:
            digits = fraction.split()
            if any(not word.isdigit() and (word not in _NUMBER_WORDS or _NUMBER_WORDS[word] > 9) for word in digits):
                return
            value += Decimal("0." + "".join(word if word.isdigit() else str(_NUMBER_WORDS[word]) for word in digits))
        found.add(sign * value)

    numeric_words = set(_NUMBER_WORDS) | {"hundred", "thousand", "and", "point", "minus", "negative", "plus"}
    literal = r"(?P<number>(?<![\w.-])[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:e[+-]?\d+)?(?![\w-]|\.\d))"
    for match in re.finditer(literal + r"|[a-z0-9_]+|[^\w\s]", text):
        token = match[0]
        if match.lastgroup == "number":
            phrase.append(token)
            continue
        if token in numeric_words:
            if token != "and":
                phrase.append(token)
            elif phrase and phrase[-1] in {"hundred", "thousand"}:
                phrase.append(token)  # "two hundred and fifty"
            else:
                flush()  # "under $30 and put three ...": "and" ends the number.
        elif token == "-" and phrase:
            continue
        else:
            flush()
    flush()
    return found


_NEGATORS = (r"(?:not|no|never|cannot|(?:do|does|did|is|are|was|were|wo|ca|could|would|should|"
             r"must|need|has|have|had)n'?t)")


def _said_as_phrase(value, text):
    """A snake_case name said as its words in order, at most two plain words apart
    ("parking_required" in "parking is required"); a negator between them never counts."""
    parts = [re.escape(part) + r"(?:'s)?" for part in str(value).casefold().split("_") if part]
    if len(parts) < 2:
        return False
    gap = r"(?:\s+(?!" + _NEGATORS + r"\b)[\w']+){0,2}\s+"
    spoken = " ".join(str(text).casefold().replace("\u2019", "'").split())
    return re.search(r"(?<![\w-])" + gap.join(parts) + r"(?![\w-])", spoken) is not None


def _affirmed_predicate(args, path, text):
    """A true/yes value affirms a predicate another argument names and the user
    states affirmatively ("pets are allowed"), not just a name ("max price")."""
    spoken = " ".join(str(text).casefold().replace("\u2019", "'").split())
    spoken = re.sub(r"\b(?:don't|dont|do not)\s+forget\s+to\b", "", spoken)
    for other, value in scalar_fields(args):
        if other == path or not isinstance(value, str) or "_" not in value:
            continue
        parts = [re.escape(part) for part in value.casefold().split("_") if part]
        # Copular wording is evidence of a predicate. Arbitrary intervening words
        # ("pets are rarely allowed") and mere compound nouns are not affirmation.
        gap = r"\s+(?:(?:is|are|be|should|must)\s+){0,2}"
        pattern = r"(?<![\w-])" + gap.join(parts) + r"(?![\w-])"
        for clause in re.split(r"[.!?;,]", spoken):
            if re.search(r"\b(?:" + _NEGATORS + r"|without)\b", clause):
                continue
            if any(re.search(r"\b(?:is|are|be)\b", match[0]) for match in re.finditer(pattern, clause)):
                return True
    return False


def _mentions_value(tool, path, value, text):
    """Literal value, a snake_case name said as words, a digit string said as
    number words, or a complete spoken spelling for an identifier field."""
    if isinstance(value, str) and _NUMBER_LITERAL.fullmatch(value):
        return Decimal(value) in spoken_numbers(text)
    if contains_value(value, text):
        return True
    if isinstance(value, str) and "_" in value and (contains_value(value.replace("_", " "), text)
                                                     or _said_as_phrase(value, text)):
        return True
    field = path.split(".")[0]
    properties = tool.get("args", {}) if isinstance(tool, dict) else {}
    return (isinstance(properties, dict) and identifier_field(field, properties.get(field))
            and contains_identifier(value, text))


def _explicit_numeric_field_values(path, command):
    aliases = _field_aliases(path)
    found = set()
    for alias in aliases:
        field = r"(?<![\w.])" + re.escape(alias) + r"(?![\w.])"
        pattern = (field +
                   r"\s*(?:(?:=|:)\s*|\b(?:to|is|equals?|of)\b(?:\s+exactly)?\s+)?" +
                   r"(?P<value>" + _NUMBER_LITERAL.pattern + r")")
        for match in re.finditer(pattern, command, re.I):
            try:
                found.add(Decimal(match["value"]))
            except InvalidOperation:
                pass
    # Literal spoken duration, only when the top-level argument names that exact
    # unit. No conversion, nested-field inference, or competing duration scopes.
    units = r"milliseconds|seconds|minutes|hours"
    durations = list(re.finditer(r"(?P<value>" + _NUMBER_LITERAL.pattern +
                                r")\s+(?P<unit>" + units + r")\b", command, re.I))
    if path in units.split('|') and len(durations) == 1:
        duration = durations[0]
        # Keep the duration attached to the direct action object, not a later
        # clause ("... and roast ... for N seconds"). Anything more expressive
        # needs explicit field evidence; we do not solve arithmetic or options.
        direct = re.fullmatch(r"[a-z]+\s+(?:(?:a|an|the)\s+)?[a-z]+\s+for\s+",
                              command[:duration.start()], re.I)
        tail = command[duration.end():].strip().rstrip('.').strip()
        simple_tail = not tail or re.fullmatch(r"(?:called|named|labelled|labeled)\s+[\w-]+", tail, re.I)
        if (duration['unit'].casefold() == path and direct and simple_tail
                and len(list(_NUMBER_LITERAL.finditer(command))) == 1):
            found.add(Decimal(duration['value']))
    return found


def _explicit_boolean_field_values(path, command):
    aliases = _field_aliases(path)
    found = set()
    for alias in aliases:
        field = r"(?<![\w.])" + re.escape(alias) + r"(?![\w.])"
        pattern = (field +
                   r"\s*(?:(?:=|:)\s*|\b(?:to|is|equals?|of)\b(?:\s+exactly)?\s+)?" +
                   r"(?P<value>true|false)\b")
        found.update(match["value"].casefold() == "true"
                     for match in re.finditer(pattern, command, re.I))
    return found


def _explicit_string_field_values(path, command):
    command = re.sub(r"\b(?:and|but|then)\s+(?:please\s+)?(?:explain|describe|clarify)\b[^,;.!?]*",
                     "", command, flags=re.I)
    parts = path.split(".")
    aliases = _field_aliases(path)
    found = set()
    for alias in aliases:
        field = r"(?<![\w.-])" + re.escape(alias) + r"(?![\w.-])"
        pattern = (field +
                   r"\s*(?:(?:=|:)\s*|\b(?:to|is|equals?|of)\b(?:\s+exactly)?\s+)?" +
                   r"(?P<value>(?!\s*\b(?:for|to|and|but|then|with|from|using|based|selected|"
                   r"returned|result|results|lookup|according)\b)[^,;.!?]+?)" +
                   r"(?=\s+\b(?:for|and|but|then|with|from)\b|[,;.!?]|$)")
        found.update(" ".join(match["value"].casefold().split())
                     for match in re.finditer(pattern, command, re.I))
        compound = (field +
                    r"\s*(?:(?:=|:)\s*|\b(?:to|is|equals?|of)\b(?:\s+exactly)?\s+)?" +
                    r"(?P<value>(?!\s*\b(?:for|to|and|but|then|with|from|using|based|selected|"
                    r"returned|result|results|lookup|according)\b)[^,;.!?]+?)" +
                    r"(?=\s+\b(?:for|but|then|with|from)\b|\s+\band\s+[\w.]+\s*(?:=|:)|[,;.!?]|$)")
        found.update(" ".join(match["value"].casefold().split())
                     for match in re.finditer(compound, command, re.I))

        preceding = (r"\b(?:set|choose|select|use|switch|change)\s+(?:the\s+)?" +
                     r"(?P<value>[^,;.!?]+?)\s+" + field +
                     r"(?=\s+\b(?:for|to|and|but|then)\b|[,;.!?]|$)")
        found.update(" ".join(match["value"].casefold().split())
                     for match in re.finditer(preceding, command, re.I))

    field_name = parts[-1].casefold().removesuffix("_id")
    relation = ("for" if field_name in _FOR_TARGET_FIELDS else
                "to" if field_name in _TO_TARGET_FIELDS else None)
    if relation:
        boundary = r"and|but|then|saying|that" if field_name == "recipient" else r"and|but|then"
        pattern = (r"\b" + relation + r"\s+(?P<value>.+?)" +
                   r"(?=\s+\b(?:" + boundary + r")\b|[,;.!?]|$)")
        found.update(" ".join(match["value"].casefold().split())
                     for match in re.finditer(pattern, command, re.I))
    # A short parser alternative must not authorize truncating one compound value.
    # Explicit field assignments already terminate the compound matcher above.
    return {value for value in found
            if not any(other.startswith(value + " and ") for other in found)}


def _explicit_dictated_message_values(command):
    dictated = re.compile(r"\bsaying\s+(?P<value>.+?)(?=\s+\b(?:but|then)\b|[.!?]|$)", re.I)
    return {" ".join(match["value"].strip(" \t\r\n\"'“”‘’").casefold().split())
            for match in dictated.finditer(command)}


def _bound_leaf_values(path, command, read_values):
    parts = path.split(".")
    if not any(part.isdigit() for part in parts):
        return read_values(path, command)
    indexed = ".".join(f"[{part}]" if part.isdigit() else part for part in parts)
    exact = read_values(indexed, command)
    if exact:
        return exact
    indexed_pattern = r"\.".join(r"\[\d+\]" if part.isdigit() else re.escape(part) for part in parts)
    if re.search(r"(?<![\w.-])" + indexed_pattern + r"(?![\w.-])", command, re.I):
        return set()
    return read_values(path, command)


def _whole_result_delegation(command):
    return bool(re.search(r"\b(?:set|update)\s+(?:the\s+)?(?:selected|chosen|returned)\s+result\b",
                          command, re.I))


def _field_scoped_result_delegation(path, command):
    aliases = _field_aliases(path)
    qualifier = r"(?:returned|selected|chosen|result|lookup)"
    for alias in aliases:
        field = r"(?<![\w.])" + re.escape(alias) + r"(?![\w.])"
        after = (field + r"\s+(?:(?:based\s+on|according\s+to|from|using|with|to)\s+)?" +
                 r"(?:the\s+)?" + qualifier + r"\b")
        before = (r"\b" + qualifier + r"(?:\s+(?!(?:and|but|then)\b)[\w-]+){0,3}" +
                  r"\s+(?:for\s+)?" + field)
        if re.search(after, command, re.I) or re.search(before, command, re.I):
            return True
    return False


def _proposed_primitive_values(values):
    formatted = ", ".join(f"{path}={json.dumps(value, allow_nan=False)}" for path, value in values)
    return ("Please confirm the proposed values exactly: " + formatted +
            ". State the action and target with these field=value pairs in a new instruction.")


class ParticipantAgent:
    def __init__(self, in_queue, out_queue, *, planner=None):
        self.in_queue = in_queue
        self.out_queue = out_queue
        self.planner = planner
        self.tools = {}
        self.state = {"intent": "", "slots": {}}
        self._state_current = True
        self.messages = []
        self.observations = {}
        self.operations = {}
        self.tool_results = []
        self.revision = 0
        self._request_start = 0
        self._held_reads = []
        self._logical_turn = None
        self._turn_open = False
        self._awaiting_clarification = False
        self._latest_frame = None
        self._sequence = 0
        self._plan_task = None
        self._tasks = set()
        self._ready = False
        self._closed = False
        self._tail_deadline = None
        self._fillers = []
        self._acknowledged = set()
        self._retry_acknowledged = set()
        self._finals = set()
        self._repair_used = False
        self._follow_up_round = 0
        self._follow_up_active = False
        self._planning_error = None
        self._consumed_grants = set()
        self._transcript_utterances = {}
        self._active_transcript_utterance = None
        self._deferred_transcript_revision = None
        self._planned_revision = None
        self._answered_revision = None
        self._answer_deadline = None
        self._deferred_transcript_deadline = None

    async def setup(self):
        if self._ready:
            return
        if self.planner is None:
            from .planner import Planner
            self.planner = Planner()
        await self.planner.setup()
        self._ready = True

    async def run(self):
        incoming = None
        try:
            await self.setup()
            incoming = asyncio.create_task(self.in_queue.get())
            while True:
                waiting = {incoming}
                if self._plan_task is not None:
                    waiting.add(self._plan_task)
                await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED, timeout=self._next_deadline())
                # A correction already in the queue must win over a ready model.
                batch = []
                if incoming.done():
                    batch.append(incoming.result())
                    incoming = asyncio.create_task(self.in_queue.get())
                while not self.in_queue.empty():
                    batch.append(self.in_queue.get_nowait())
                # A queued correction also wins over an automatic result-to-write
                # continuation. Results are still reconciled in the durable ledger.
                # Internal barriers acknowledge only after this batch's ledger
                # receipts; corrections retain precedence over continuations.
                for phase in (0, 1, 2):
                    for event in batch:
                        event_kind = event.get("event_type") if isinstance(event, dict) else None
                        event_phase = (2 if event_kind == "controller_barrier" else
                                       1 if event_kind in ("tool_result", "tool_not_submitted") else 0)
                        if event_phase == phase:
                            if phase == 1:
                                self._expire_writes()
                            self._handle(event)
                self._expire_writes()
                task = self._plan_task
                if task is not None and task.done():
                    self._plan_task = None
                    if not task.cancelled():
                        revision, decision = task.result()
                        if revision == self.revision and not self._turn_open:
                            self._apply(decision)
                self._ensure_answer()
        finally:
            if incoming is not None:
                incoming.cancel()
                await asyncio.gather(incoming, return_exceptions=True)
            await self.close()

    async def close(self):
        if self._closed:
            return
        self._closed = True
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=0.5)
            for task in pending:
                task.cancel()
        if self.planner is not None:
            try:
                await asyncio.wait_for(self.planner.close(), timeout=1.0)
            except (Exception, asyncio.CancelledError):
                pass

    def snapshot(self):
        result = deepcopy(self.state) if self._state_current else {"intent": "", "slots": {}}
        result["revision"] = self.revision
        result["actions"] = [self._operation_context(op) for op in self.operations.values()
                             if op["kind"] == "state_modifying"]
        return result

    def _operation_context(self, operation):
        context = {key: deepcopy(operation[key]) for key in
                ("operation_id", "call_id", "api_name", "args", "kind", "revision", "status", "result",
                 "execution_admitted", "read_dependencies", "retained_from_call_id", "awaiting_not_submitted_call_id")
                if key in operation}
        context["can_retain_read"] = bool(operation["kind"] == "read_only"
            and operation.get("execution_admitted") and not operation.get("retained_from_call_id")
            and operation["revision"] != self.revision
            and operation["status"] in {"pending", "cancel_requested"})
        return context

    def _read_dependencies(self, step, tool, selection):
        # Conservative media scope: no inference that a changed recording/frame
        # is irrelevant. Stable task-scoped dependencies are not implemented.
        audio_index = next((index for index in range(len(self.messages) - 1, -1, -1)
                            if self.messages[index]["event_type"] == "user_audio_chunk"), None)
        indices = {self._latest_frame, audio_index}
        return deepcopy({"tool": tool, "result_bindings": step.get("result_bindings", {}),
                         "result_evidence": step.get("result_evidence"), "selection": selection,
                         "media": [{"message_index": index, "revision": self.messages[index]["revision"],
                                    "observation": self.observations.get(index)}
                                   for index in sorted(i for i in indices if i is not None)]})

    def _refresh_read_consumers(self):
        """Recheck adopted evidence before later same-revision use, not just arrival."""
        invalid = set()
        for operation in self.operations.values():
            if (not operation.get("retained_from_call_id") or operation["revision"] != self.revision
                    or operation["status"] not in {"pending", "success", "error", "invalidated"}):
                continue
            current = self._read_dependencies(operation["step"], self.tools.get(operation["api_name"]), operation["selection"])
            if (operation["status"] == "invalidated" or
                    call_key(operation["api_name"], operation["read_dependencies"]) != call_key(operation["api_name"], current)):
                operation.update(status="invalidated", continuation_retired=True)
                invalid.add(operation["call_id"])
        if invalid:
            self.tool_results = [row for row in self.tool_results if row["call_id"] not in invalid]

    def _emit(self, action, payload):
        if not self._closed:
            self.out_queue.put_nowait({"action": action, "payload": deepcopy(payload),
                                       "state_snapshot": self.snapshot()})

    def _borrowed_lookup(self, step):
        """A follow-up lookup whose every value came from a different tool's call this request.

        "Find flights to Vancouver ... and a hotel near the airport": with no hotel tool, a
        small planner substitutes an apartment search in Vancouver. Nothing the user said
        for it is new, so a follow-up round does not add it.
        """
        tool = self.tools.get(step.get("api_name")) if isinstance(step, dict) else None
        if not isinstance(tool, dict) or tool.get("kind") != "read_only" or "retain_call_id" in step:
            return False
        values = [str(value).casefold() for _, value in scalar_fields(step.get("args", {}))
                  if value is not None and not isinstance(value, bool) and str(value).strip()]
        others = {str(value).casefold() for op in self.operations.values()
                  if op.get("request_start") == self._request_start and op.get("api_name") != step.get("api_name")
                  for _, value in scalar_fields(op.get("args", {})) if value is not None}
        if not values or not all(value in others for value in values):
            return False
        # Reusing a city/identifier is not proof of an unrequested lookup. An
        # explicit request naming this tool's target is independent authority.
        for row in turn_clauses(self._user_texts()):
            text = row["text"]
            if (_names_read_target(step["api_name"], text)
                    and (_READ_COMMAND.search(text) or _READ_QUESTION.search(text))
                    and all(path in (step.get("result_bindings") or {}) or _mentions_value(tool, path, str(value), text)
                            for path, value in scalar_fields(step.get("args", {})) if value is not None)):
                return False
        return True

    def _dispatch_plan(self, calls):
        """Dispatch every step of one plan; a refused step does not cancel the others.

        Clarifications raised while the plan dispatches are held, and the first is
        spoken after the remaining steps ran; each step still passes every check.
        """
        held = []
        self._held_clarifications = held
        try:
            for step in calls:
                self._dispatch(step)
        finally:
            self._held_clarifications = None
        # A lookup held for a condition no dispatched step can settle is re-checked now,
        # outside the plan, so it asks rather than waiting silently.
        reads_pending = any(op.get("request_start") == self._request_start and op.get("kind") == "read_only"
                            and op.get("status") in {"pending", "cancel_requested"} for op in self.operations.values())
        if not reads_pending and getattr(self, "_held_reads", None):
            stranded = [item for item in self._held_reads if item[0] == self._request_start]
            self._held_reads = [item for item in self._held_reads if item[0] != self._request_start]
            for _, step, depth in stranded:
                self._dispatch(step, depth=depth)
        false_hold, self._false_hold = getattr(self, "_false_hold", False), False
        if false_hold and not held and not any(op.get("request_start") == self._request_start
                                               for op in self.operations.values()):
            self._say("clarification_request", "Understood, I will not look that up. Anything else?")
        if held:
            text, gate, validation = held[0]
            self._say("clarification_request", text, gate=gate, validation=validation)

    def _say(self, action, text, *, gate=None, call_id=None, validation=None):
        if (action == "clarification_request" and isinstance(text, str) and text.strip()
                and getattr(self, "_held_clarifications", None) is not None):
            self._held_clarifications.append((text, gate, validation))
            return
        if isinstance(text, str) and text.strip():
            if action in {"final_response", "clarification_request"}:
                self._answered_revision = self.revision
                self._answer_deadline = None
            if action == "clarification_request":
                self._awaiting_clarification = True
            payload = {"text": text.strip()}
            if call_id is not None:
                payload["call_id"] = call_id
            if gate:
                payload["gate"] = gate  # Why the write gate refused: evidence, never spoken.
            if validation:
                payload["validation"] = validation  # The validator's own problems: evidence, never spoken.
            self._emit(action, payload)

    def _ensure_answer(self):
        """A settled plan must not leave a completed user turn with only fillers.

        Old cancelled operations cannot settle this revision. Only an active
        plan or a pending current consumer may postpone its answer.
        """
        if (self._planned_revision == self.revision and self._answered_revision != self.revision
                and not self._closed and not self._turn_open and not self._awaiting_clarification
                and self._plan_task is None
                and not any(op["revision"] == self.revision and op["status"] == "pending"
                            for op in self.operations.values())):
            if self._deferred_transcript_revision == self.revision:
                if time.monotonic() >= self._deferred_transcript_deadline:
                    self._final("I cannot yet confirm whether the earlier action was submitted. I have not sent a replacement.")
                return
            # An executor's not-submitted receipt can race the next user input.
            # Give queued corrections a short turn to supersede this fallback.
            if self._answer_deadline is None:
                # Internal evidence refreshes retire obsolete presentation, not
                # the obligation to answer an otherwise unanswered user turn.
                fresh_input = (self.messages and self.messages[-1].get("revision") == self.revision
                               and self.messages[-1].get("event_type") in {
                                   "user_speech_chunk", "user_audio_chunk", "interruption"})
                self._answer_deadline = time.monotonic() + (0.05 if fresh_input else 0.5)
            elif time.monotonic() >= self._answer_deadline:
                self._say("clarification_request", "I could not safely complete that request. Please clarify what you would like me to do next.")
        else:
            self._answer_deadline = None

    def _filler(self, text, *, recovery_id=None):
        # One acknowledgement per completed user turn, one per bounded read retry.
        seen, key = ((self._retry_acknowledged, recovery_id) if recovery_id is not None
                     else (self._acknowledged, self.revision))
        if key in seen:
            return
        seen.add(key)
        self._fillers.append(text)
        self._say("filler_speech", text)

    def _final(self, text, *, call_id=None):
        key = (self.revision, call_id, text)
        if key not in self._finals:
            self._finals.add(key)
            self._say("final_response", text, call_id=call_id)

    def _recover_result_provenance(self, step, tool):
        """Attach the provenance of an identifier copied from a delivered result.

        Only an identifier argument the user did not say, found at exactly one
        path across successful reads of this request, gains that exact
        result_binding. All binding and delegation checks still apply afterwards;
        zero or several occurrences stay unbound and are refused as before.
        """
        args = step.get("args")
        descriptors = tool.get("args", {}) if isinstance(tool.get("args"), dict) else {}
        if not isinstance(args, dict):
            return step
        bindings = step.get("result_bindings", {})
        if not isinstance(bindings, dict):
            return step
        supplied = " ".join(text for _, text in self._user_texts())
        sources = [op for op in self.operations.values() if op["kind"] == "read_only" and op["status"] == "success"
                   and op.get("request_start") == self._request_start and isinstance(op.get("result"), dict)]
        recovered = {}
        for name, value in args.items():
            if (name in bindings or not isinstance(value, str) or not value.strip()
                    or not identifier_field(name, descriptors.get(name)) or _mentions_value(tool, name, value, supplied)):
                continue
            hits = [(op["call_id"], path) for op in sources for path, found in scalar_fields(op["result"])
                    if isinstance(found, str) and found == value]
            if len(hits) == 1:
                recovered[name] = {"call_id": hits[0][0], "path": hits[0][1]}
        if not recovered:
            return step
        return {**step, "result_bindings": {**bindings, **recovered}}

    def _continues_logical_turn(self, payload):
        """Same speaker turn after a pause, while no effect of it has been admitted.

        Only a transport-issued token can continue a turn. Once any write of this
        request was admitted for execution (or settled), later speech starts a new
        request, so older same-turn text can never re-authorize a repeat.
        """
        token = payload.get("logical_turn")
        if (not isinstance(token, str) or not token or token != self._logical_turn
                or self._request_start >= len(self.messages)):
            return False
        return not any(op["kind"] == "state_modifying" and op["request_start"] == self._request_start
                       and (op.get("execution_admitted") or op["status"] in {"success", "error", "unknown"})
                       for op in self.operations.values())

    def _invalidate(self, *, preserve_answer=False):
        answered = preserve_answer and self._answered_revision == self.revision
        self.revision += 1
        if answered:
            self._answered_revision = self.revision
        self._deferred_transcript_revision = None
        self._deferred_transcript_deadline = None
        self._answer_deadline = None
        self._repair_used = False
        self._follow_up_round = 0
        self._follow_up_active = False
        self._planning_error = None
        if self._plan_task is not None:
            self._plan_task.cancel()
            self._plan_task = None
        self.tool_results = []
        for operation in self.operations.values():
            if operation["status"] == "pending":
                operation["status"] = "cancel_requested"
                self._emit("cancel_tool", {"call_id": operation["call_id"]})

    def _append_message(self, event_type, payload):
        self.messages.append({"message_index": len(self.messages), "revision": self.revision,
                              "event_type": event_type, "payload": deepcopy(payload)})

    def _handle_transcript_revision(self, payload):
        """Explicit ASR hypotheses replace one slot; only final text is authority.

        Each event contains the whole transcript, not a suffix. Revisions must
        strictly increase, including the final event. Retired utterances cannot
        reopen a later user turn. Legacy additive chunks use the existing path.
        """
        utterance, revision = payload.get("utterance_id"), payload.get("transcript_revision")
        if (not isinstance(utterance, str) or not utterance.strip() or len(utterance) > 200
                or type(revision) is not int or revision < 0
                or not isinstance(payload.get("text"), str)
                or type(payload.get("end_of_turn", False)) is not bool):
            return
        previous = self._transcript_utterances.get(utterance)
        if previous is not None and (utterance != self._active_transcript_utterance
                                     or revision <= previous["revision"]):
            return
        if previous is None:
            previous = {"index": len(self.messages), "state_before": deepcopy(self.state)}
            self._transcript_utterances[utterance] = previous
        else:
            # Slots inferred from an earlier hypothesis are not retained as facts.
            self.state = deepcopy(previous["state_before"])
        self._active_transcript_utterance = utterance
        previous["revision"] = revision
        self._state_current = False
        self._invalidate()
        self._request_start = previous["index"]
        self._awaiting_clarification = False
        self._turn_open = payload.get("end_of_turn") is not True
        canonical = deepcopy(payload)
        if self._turn_open:
            canonical["text"] = ""  # Provisional words never enter planning or grants.
        message = {"message_index": previous["index"], "revision": self.revision,
                   "event_type": "user_speech_chunk", "payload": canonical}
        if previous["index"] == len(self.messages):
            self.messages.append(message)
        else:
            self.messages[previous["index"]] = message
        self.observations.pop(previous["index"], None)
        if self._turn_open:
            return
        observe_input = getattr(self.planner, "observe_input", None)
        if callable(observe_input):
            try:
                observe_input(deepcopy(message), self._request_start)
            except Exception:
                pass  # Optional preparation cannot replace canonical processing.
        received = " ".join(payload["text"].split())[:180]
        self._filler(f"I am checking your request now: {received}" if received
                     else "I am checking your request and the available tools now.")
        self._start_plan()

    def _handle(self, event):
        if not isinstance(event, dict) or not isinstance(event.get("payload", {}), dict):
            return
        kind, payload = event.get("event_type"), event.get("payload", {})
        if not isinstance(kind, str):
            return
        if kind == "tool_manifest":
            raw = payload.get("tools")
            if isinstance(raw, dict):
                resume = self._request_pending()
                if self.tools and raw != self.tools:
                    self._invalidate(preserve_answer=True)
                self.tools = deepcopy(raw)
                if resume:
                    self._start_plan()
        elif kind == "video_frame":
            resume = self._request_pending()
            if resume:
                self._invalidate(preserve_answer=True)
            self._append_message(kind, payload)
            self._latest_frame = len(self.messages) - 1
            if resume:
                self._start_plan()
        elif kind in {"user_speech_chunk", "user_audio_chunk", "interruption"}:
            if kind == "user_speech_chunk" and ({"utterance_id", "transcript_revision"} & payload.keys()):
                self._handle_transcript_revision(payload)
                return
            self._active_transcript_utterance = None
            interruption = kind == "interruption"
            continuing = self._continues_logical_turn(payload)
            if payload.get("context_only") is True:
                # Earlier same-turn speech decoded after a newer onset: bounded
                # context with its own provenance. It never plans or authorizes
                # by itself; only a later fresh decision can use it.
                if kind == "user_speech_chunk" and continuing and payload.get("end_of_turn") is False:
                    self._append_message(kind, payload)
                return
            if (not self._turn_open or interruption) and not continuing:
                # Retain planning memory, but hide it before cancellation emits a snapshot.
                self._state_current = False
                self._invalidate()
                self._request_start = len(self.messages)
                self._awaiting_clarification = False
                token = payload.get("logical_turn")
                self._logical_turn = token if isinstance(token, str) and token else None
            elif continuing and (not self._turn_open or interruption):
                # A pause inside one logical turn: stop obsolete work immediately but
                # keep the preceding clauses in the current request for the next decision.
                self._state_current = False
                self._invalidate()
                self._awaiting_clarification = False
            self._append_message(kind, payload)
            self._turn_open = not (interruption or payload.get("end_of_turn") is True)
            observe_input = getattr(self.planner, "observe_input", None)
            if callable(observe_input):
                try:
                    observe_input(deepcopy(self.messages[-1]), self._request_start)
                except Exception:
                    pass  # Optional preparation cannot replace canonical turn processing.
            if self._turn_open:
                return
            if interruption:
                text = payload.get("text", "")
                if isinstance(text, str) and text.strip():
                    received = " ".join(text.split())[:180]
                    self._filler(f"I heard your update: {received} I am checking the revised request now.")
                else:
                    self._filler("I have stopped the pending work. I am listening for your update.")
                    return
            elif kind == "user_audio_chunk":
                self._filler("I am checking the complete recording and any corrections before acting." if not self._fillers
                             else "I am checking the new recording against your earlier request.")
            else:
                text = " ".join(message["payload"].get("text", "") for message in self.messages[self._request_start:]
                                if isinstance(message["payload"].get("text"), str))
                received = " ".join(text.split())[:180]
                self._filler(f"I am checking your request now: {received}" if received
                             else "I am checking your request and the available tools now.")
            latest = payload.get("text") if kind == "user_speech_chunk" else None
            held = isinstance(latest, str) and _HOLD_MARKER.search(latest.strip()) is not None
            if held:
                self._start_plan(hold=self.hold_seconds)
            else:
                self._start_plan()
        elif kind == "tool_result":
            self._result(payload)
        elif kind == "tool_not_submitted":
            self._not_submitted(payload)
        elif kind == "controller_barrier":
            # In-process executor protocol only, not serialized conversation data.
            ready = payload.get("ready")
            if isinstance(ready, asyncio.Event):
                ready.set()
        elif kind == "scenario_end":
            # The harness continues sending tool results in its finishing window.
            self._tail_deadline = time.monotonic() + 6
            for op in self.operations.values():
                if "deadline" in op:
                    op["deadline"] = min(op["deadline"], self._tail_deadline - 0.1)

    def _context(self):
        self._refresh_read_consumers()
        context = deepcopy({"tools": self.tools, "state": self.state, "messages": self.messages,
                         "tool_results": self.tool_results, "revision": self.revision,
                         "current_turn_start": self._request_start, "latest_frame_index": self._latest_frame,
                         "observations": list(self.observations.values()),
                         "actions": [self._operation_context(op) for op in self.operations.values()],
                         "planning_error": self._planning_error,
                         "tail_remaining_ms": (max(0, (self._tail_deadline - time.monotonic()) * 1000)
                                               if self._tail_deadline is not None else None)})
        if getattr(self.planner, "clause_citations", False) is True:
            # Same segmentation the write gate uses; planners cite IDs, never regenerate text.
            context["current_clauses"] = [{key: row[key] for key in ("clause_id", "message_index", "text")}
                                          for row in turn_clauses(self._user_texts())]
        return context

    def _request_pending(self):
        return not self._turn_open and not self._awaiting_clarification and (self._plan_task is not None or any(
            op["revision"] == self.revision and op["status"] == "pending" for op in self.operations.values()))

    def _next_deadline(self):
        deadlines = [op["deadline"] for op in self.operations.values()
                     if op["status"] == "pending" and "deadline" in op]
        if self._answer_deadline is not None:
            deadlines.append(self._answer_deadline)
        if (self._deferred_transcript_revision == self.revision
                and self._answered_revision != self.revision and self._deferred_transcript_deadline is not None
                and self._plan_task is None
                and not any(op["revision"] == self.revision and op["status"] == "pending"
                            for op in self.operations.values())):
            deadlines.append(self._deferred_transcript_deadline)
        return max(0, min(deadlines) - time.monotonic()) if deadlines else None

    def _expire_writes(self):
        # Reads (including retained consumers) also need a bounded result wait.
        for op in self.operations.values():
            if (op["status"] == "pending" and
                    time.monotonic() >= op.get("deadline", float("inf"))):
                op["continuation_retired"] = True
                op["status"] = "unknown"
                if op["revision"] == self.revision:
                    if op["kind"] == "read_only":
                        self._final("I could not complete the lookup because no valid result arrived. Please try again.")
                    else:
                        self._final("I could not confirm the action's outcome because no result arrived. I will not repeat it without checking what happened.")

    # Seconds to wait before planning a turn that ends on a hold marker.
    hold_seconds = 2.0

    def _start_plan(self, hold=0.0):
        self._planned_revision = self.revision
        self._answer_deadline = None
        if self._plan_task is not None:
            self._plan_task.cancel()
        task = asyncio.create_task(self._plan(self._context(), self.revision, hold))
        self._plan_task = task
        self._tasks.add(task)
        task.add_done_callback(self._finished)

    def _finished(self, task):
        self._tasks.discard(task)
        if not task.cancelled():
            task.exception()  # Consume errors from a superseded background task.

    async def _plan(self, context, revision, hold=0.0):
        task = None
        try:
            if hold:
                self._emit("planning_held", {"seconds": hold})
                await asyncio.sleep(hold)
            # Keep the configured planner budget, plus the existing cleanup margin.
            # wait_for can accept a late decision when a planner swallows cancellation.
            timeout = getattr(self.planner, "timeout", 4.5) + 0.5
            deadline = time.monotonic() + timeout
            task = asyncio.create_task(self.planner.plan(context))
            self._tasks.add(task)
            task.add_done_callback(self._finished)
            done, _ = await asyncio.wait({task}, timeout=timeout)
            if not done or time.monotonic() >= deadline:
                raise asyncio.TimeoutError
            decision = task.result()
            if not isinstance(decision, dict):
                raise ValueError("The planner did not return an object")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            from .planner import PlannerError
            message = str(exc)
            if (isinstance(exc, PlannerError)
                    and message.startswith(("Gemini returned HTTP 429;", "Gemini returned HTTP 503;"))):
                decision = {"clarification": message}
            else:
                decision = {"clarification": "I could not reliably interpret that request. Please clarify what you want me to do."}
        finally:
            if task is not None and not task.done():
                task.cancel()
        return revision, decision

    def _apply(self, decision):
        if self._awaiting_clarification:
            return
        if not isinstance(decision.get("observations", []), list):
            self._say("clarification_request", "I could not validate the recording observations. Please repeat the request.")
            return
        if self._follow_up_active:
            # A follow-up round may only add remaining requested calls; the results
            # were already answered, so its prose or clarification is not spoken.
            self._follow_up_active = False
            self._planning_error = None
            calls = decision.get("tool_calls") if isinstance(decision, dict) else None
            if isinstance(calls, list) and calls and len(calls) <= 4:
                self._dispatch_plan([step for step in calls if not self._borrowed_lookup(step)])
            return
        if getattr(self.planner, "audio_mode", "independent") == "single_call_reads":
            from .planner import _joint_audio_key
            for row in decision.get("observations", []):
                if not isinstance(row, dict) or row.get("type") != "audio":
                    continue
                index = row.get("message_index")
                marker = _joint_audio_key(row.get("_audio_joint_only"))
                valid_index = type(index) is int and 0 <= index < len(self.messages)
                if (not valid_index or ("_audio_joint_only" in row and
                        (marker is None or marker[:2] != (index, self.messages[index].get("revision"))))
                        or "_audio_joint_only" not in row and not self._verified_audio_row(index, row)):
                    self._say("clarification_request", "I could not verify the recording's source. Please repeat the request.")
                    return
        intent, slots = decision.get("intent"), decision.get("slots")
        if isinstance(intent, str):
            self.state["intent"] = intent
        if isinstance(slots, dict):
            self.state["slots"] = {key: deepcopy(value) for key, value in slots.items()
                                   if isinstance(key, str) and value is not None}
        if isinstance(intent, str) and isinstance(slots, dict):
            self._state_current = True
        for observation in decision.get("observations", []) if isinstance(decision.get("observations", []), list) else []:
            if not isinstance(observation, dict):
                continue
            index = observation.get("message_index")
            if type(index) is not int or not 0 <= index < len(self.messages):
                continue
            media_type = observation.get("type")
            expected = {"audio": "user_audio_chunk", "image": "video_frame"}.get(media_type) if isinstance(media_type, str) else None
            if expected == self.messages[index]["event_type"]:
                self.observations[index] = deepcopy(observation)
                if media_type == "audio" and getattr(self.planner, "audio_mode", "independent") == "single_call_reads":
                    key = _joint_audio_key(observation.get("_audio_joint_only"))
                    pending = self.planner._pending_audio_sources
                    if key is not None and pending.get(index) == key:
                        pending.pop(index)
        self._refresh_read_consumers()
        question = decision.get("clarification")
        uncertain_audio = any(
            index >= self._request_start and observation.get("type") == "audio" and observation.get("uncertain") is True
            for index, observation in self.observations.items())
        if uncertain_audio and not (isinstance(question, str) and question.strip()):
            question = "Please confirm the unclear part of that recording before I use it for an action."
        if isinstance(question, str) and question.strip():
            if self._unconfirmed_claim(question):
                question = "I do not have a successful tool result confirming that action."
            self._say("clarification_request", question)
            return
        calls = decision.get("tool_calls", [])
        if not isinstance(calls, list):
            self._say("clarification_request", "I could not validate the proposed action. Please clarify the request.")
            return
        if calls:
            try:
                unique = {call_key(step["api_name"], step.get("args", {}),
                                   write=self.tools.get(step["api_name"], {}).get("kind") == "state_modifying")
                          for step in calls}
            except (KeyError, TypeError, ValueError, AttributeError):
                self._say("clarification_request", "I could not validate the proposed actions. Please clarify the request.")
                return
            # Bound distinct effects; repeated model proposals are handled by the
            # submission ledger and must not suppress one legitimate operation.
            if len(unique) > 4:
                self._say("clarification_request", "Please narrow this request to a few actions at a time.")
                return
            self._dispatch_plan(calls)
            return
        response = decision.get("response")
        if isinstance(response, str) and response.strip():
            if self._unconfirmed_claim(response):
                self._final("I do not have a successful tool result confirming that action.")
            else:
                self._final(response)
        else:
            self._say("clarification_request", "Please clarify what you would like me to do.")

    def _verified_audio_row(self, index, observation):
        return any(key[:2] == (index, self.messages[index].get("revision"))
                   and all(observation.get(field) == cached[field]
                           for field in ("message_index", "type", "transcript", "uncertain"))
                   for key, cached in getattr(self.planner, "_audio_cache", {}).items())

    def _conflicting_spelling(self, args):
        """Ask when the turn names this write's person in two near-identical spellings.

        "The passenger is Mina Porter ... use Mena Porter": a recogniser can hear one name
        two ways, and either could be the user's. Only for *name fields, only a one-word
        difference of at most two letters with the same initial.
        """
        spoken = re.findall(r"[a-z']+", " ".join(text for _, text in self._user_texts()).casefold())
        for path, value in scalar_fields(args):
            if not isinstance(value, str) or not path.rsplit(".", 1)[-1].endswith("name"):
                continue
            parts = value.casefold().split()
            if len(parts) < 2:
                continue
            for index in range(len(spoken) - len(parts) + 1):
                gram = spoken[index:index + len(parts)]
                diffs = [(heard, own) for heard, own in zip(gram, parts) if heard != own]
                if (len(diffs) == 1 and min(map(len, diffs[0])) >= 3 and diffs[0][0][0] == diffs[0][1][0]
                        and _edit_distance(*diffs[0]) <= 2):
                    other = " ".join(word.capitalize() for word in gram)
                    return f"I heard both {other} and {value}. Which name should I use?"
        return ""

    def _read_condition(self, step, tool):
        """Return ok, pending, false or unverified for a conditional lookup.

        "Search for a kettle. If everything's over $50, track order Q7 instead": the tracking
        lookup waits for this request's search and is skipped when a returned price makes the
        condition false. A lookup the user also asks for outside a condition always runs.
        """
        values = [(path, str(value)) for path, value in scalar_fields(step.get("args", {}))
                  if type(value) in (str, int, float) and str(value).strip()]
        sentences = {}
        rows = turn_clauses(self._user_texts())
        # Politeness is not a condition: "under a hundred dollars if possible".
        polite = re.compile(r"\bif\s+(?:at\s+all\s+)?(?:possible|you\s+can|you\s+could|you\s+would|you\s+please|"
                            r"you\s+don't\s+mind|that's\s+(?:ok|okay|alright|all\s+right)|necessary|needed)\b"
                            r"(?=\s*(?:[,.!?;]|$))")
        rows = [{**row, "text": polite.sub(" ", row["text"])} for row in rows]
        for row in rows:
            sentences.setdefault(row["sentence"], []).append(row["text"])
        hits = [text for text in (" ".join(parts) for parts in sentences.values())
                if (values and all(_mentions_value(tool, path, value, text) for path, value in values))
                or (not values and _names_read_target(step.get("api_name"), text))]
        if not hits:
            return "ok"
        last_mention = max((row["start"] for row in rows
                            if any(_mentions_value(tool, path, value, row["text"]) for path, value in values)
                            or (not values and _names_read_target(step.get("api_name"), row["text"]))), default=-1)
        if any(row["start"] > last_mention and re.fullmatch(
                r"(?:(?:actually|sorry|no)\s*,?\s*)?(?:never mind|nevermind|forget (?:it|that)|"
                r"cancel (?:it|that)|don't do (?:it|that)|do not do (?:it|that)|stop|wait|hold on|hold off|"
                r"(?:maybe|perhaps) later)[.!?,; ]*", row["text"]) for row in rows):
            return "false"
        # A later withdrawal is not an unconditional request merely because it
        # repeats the identifier; nor is a declarative "my order is X".
        for text in hits:
            if re.search(r"\b(?:don't|dont|do not|never|stop|hold off)\s+(?:\w+\s+){0,2}"
                         r"(?:search|find|look|track|check|read|get|show|list|inspect|retrieve)\b", text):
                return "false"
        conditioned = [text for text in hits if re.search(r"\bif\b", text)]
        # Discovery for a conditional write ("book a flight if refundable") is
        # how its facts are learned, not a lookup commanded by that condition.
        conditioned = [text for text in conditioned if _READ_COMMAND.search(text)
                       or re.match(r"\s*(?:but\s+)?if\b", text)]
        for text in conditioned:
            before = re.split(r"\band\s+if\b", text, maxsplit=1)[0]
            if (before != text and not re.search(r"\bif\b", before) and _READ_COMMAND.search(before)
                    and all(_mentions_value(tool, path, value, before) for path, value in values)):
                return "ok"
        if not conditioned or any((_READ_COMMAND.search(text) or _READ_QUESTION.search(text))
                                  for text in hits if text not in conditioned):
            return "ok"
        current = [op for op in self.operations.values() if op.get("request_start") == self._request_start
                   and op.get("kind") == "read_only"]
        lookups = [op["result"] for op in current if op.get("status") == "success" and isinstance(op.get("result"), dict)]
        pending = any(op.get("status") in {"pending", "cancel_requested"} for op in current)
        statuses = []
        for text in conditioned:
            proved, status, _ = _verified_price_conditions(text, step, lookups, pending, falsify_only=True)
            if status == "ok" and re.search(r"\bif\b", proved):
                status = "unverified"
            statuses.append(status)
        return ("ok" if "ok" in statuses else "pending" if "pending" in statuses else
                "unverified" if "unverified" in statuses else "false")

    def _recited_step(self, step, tool):
        """The same write cited to the single current clause that states all its string values."""
        # A true/false value is an affirmed predicate ("pets are allowed"), not a spoken
        # word; the value check on the re-cited clause still has to affirm it.
        values = [(path, value) for path, value in scalar_fields(step.get("args", {}))
                  if isinstance(value, str) and len(value.strip()) > 1
                  and value.strip().casefold() not in {"true", "false", "yes", "no"}]
        authorization = step.get("authorization")
        cited = set(authorization.get("clauses") or []) if isinstance(authorization, dict) else set()
        if not values or not cited:
            return None
        candidates = [row["clause_id"] for row in turn_clauses(self._user_texts())
                      if all(_mentions_value(tool, path, value, row["text"]) for path, value in values)]
        if len(candidates) != 1 or candidates == sorted(cited):
            return None
        return {**deepcopy(step), "authorization": {"clauses": candidates}}

    _EXAMPLE_GUARDED_ARGS = {"destination", "query", "order_id", "card_type", "city"}

    def _copied_schema_example(self, tool, args, api_name=None):
        """True when a free-text read argument equals an example quoted in the public
        contract's argument description and the user never said it in this request."""
        said = re.sub(r"[^a-z0-9]+", " ", " ".join(text for _, text in self._user_texts()).casefold())
        for name, value in (args or {}).items():
            spec = (tool.get("args") or {}).get(name)
            if name not in self._EXAMPLE_GUARDED_ARGS or not isinstance(value, str) or not isinstance(spec, dict):
                continue
            examples = {example.casefold() for example in re.findall(r"'([^']+)'", str(spec.get("description", "")))}
            words = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
            # A spelled-out form ("B-O-B-1-2") is the user saying it too.
            if (value.casefold() in examples and words and f" {words} " not in f" {said} "
                    and not contains_identifier(value, said)):
                return True
            # An identifier returned by a different tool ("APT1" from an apartment search
            # reused as an order number) that the user never said is not this lookup's value.
            if name.endswith("_id") and words and f" {words} " not in f" {said} " and not contains_identifier(value, said):
                for op in self.operations.values():
                    if (op.get("status") == "success" and op.get("api_name") != api_name
                            and any(v == value for _, v in scalar_fields(op.get("result") or {}))):
                        return True
        return False

    def _user_texts(self):
        texts = []
        for index in range(self._request_start, len(self.messages)):
            message = self.messages[index]
            if message["event_type"] in {"user_speech_chunk", "interruption"}:
                text = message["payload"].get("text")
                if isinstance(text, str):
                    texts.append((index, text))
            elif message["event_type"] == "user_audio_chunk":
                observation = self.observations.get(index, {})
                # Joint-native read context may support questions, never write authority.
                if (observation.get("uncertain") is False and "_audio_joint_only" not in observation
                        and isinstance(observation.get("transcript"), str)
                        and (getattr(self.planner, "audio_mode", "independent") != "single_call_reads"
                             or self._verified_audio_row(index, observation))):
                    texts.append((index, observation["transcript"]))
        return texts

    def _binding_error(self, step, tool, args, command=None, selection=None):
        bindings = step.get("result_bindings", {})
        if not isinstance(bindings, dict):
            return "Result bindings must be an object."
        successes = {key: op for key, op in self.operations.items() if op["status"] == "success"}
        supplied = " ".join(text for _, text in self._user_texts())
        if not isinstance(command, str):
            command = ""
        authorization = step.get("authorization")
        authorized_text = authorization.get("quote") if isinstance(authorization, dict) else command
        if not isinstance(authorized_text, str):
            authorized_text = command
        cited_ids = authorization.get("clauses") if isinstance(authorization, dict) else None
        rows = turn_clauses(self._user_texts())
        cited_rows = [row for row in rows if isinstance(cited_ids, list) and row["clause_id"] in cited_ids]
        # A dictated value continued in its own segment ("the number is DL." / "555." / "swap it in")
        # lies between the cited clauses: a bare value fragment there is part of what was cited.
        if len(cited_rows) > 1:
            first, last = rows.index(cited_rows[0]), rows.index(cited_rows[-1])
            cited_rows = [row for index, row in enumerate(rows) if row in cited_rows or first < index < last
                          and re.fullmatch(r"[a-z0-9][a-z0-9\s,.\-]{0,23}", row["text"].strip())
                          and re.search(r"\d", row["text"]) and not re.search(r"[a-z]{4,}", row["text"])]
        cited_text = " ".join(row["text"] for row in cited_rows)
        # A topic phrase in the command's own sentence ("About my passport, update it,
        # the new number is T441") states its value too; other sentences never do.
        sentences = {row["sentence"] for row in cited_rows}
        sentence_text = " ".join(row["text"] for row in rows if row["sentence"] in sentences and row not in cited_rows)
        mention_text = (authorized_text + " " + cited_text + " " + sentence_text).strip()
        # A returned identifier establishes provenance, never permission to
        # replace an explicitly named identifier in the user's command. Scope
        # this check to a sole identifier field so unrelated field roles are not
        # conflated, and retain pronoun/selected-result delegation when no ID is
        # named. Both recovered and explicit bindings pass through this check.
        identifiers = [(path, value) for path, value in scalar_fields(args)
                       if isinstance(value, str) and identifier_field(
                           path.split(".")[0], tool.get("args", {}).get(path.split(".")[0]))]
        head = command_head(command)
        target = re.sub(r"^\w+\s+(?:(?:my|the|a|an|our)\s+)?", "", head)
        target = re.split(r"\b(?:from|to|for|with|using)\b", target, maxsplit=1)[0].strip(" .,;!?")
        named_ids = spelled_runs(target) | set(re.findall(r"\b(?=[a-z0-9]*[a-z])(?=[a-z0-9]*\d)[a-z0-9]+\b", target, re.I))
        if tool["kind"] == "state_modifying" and len(identifiers) == 1 and named_ids:
            path, value = identifiers[0]
            if not _mentions_value(tool, path, value, head):
                return f"Please supply {path}; I cannot invent a replacement for the explicitly named identifier."
        # A categorical direct object ("pay the water bill") likewise cannot
        # be replaced by a different type mentioned in a later status statement.
        # Derive the noun from the declared *_type field, never from a domain list.
        for path, value in scalar_fields(args) if tool["kind"] == "state_modifying" else ():
            if isinstance(value, str) and path.endswith("_type"):
                noun = path.rsplit(".", 1)[-1][:-5].replace("_", " ")
                named = re.fullmatch(r"(.+?)\s+" + re.escape(noun), target)
                category = named[1] if named else target if re.fullmatch(r"[a-z][\w-]*", target) else ""
                if (category and category not in _schema_words(tool) | {"it", "this", "that", "them"}
                        and not _mentions_value(tool, path, value, category)):
                    return f"Please supply {path}; I cannot invent a replacement for the explicitly named type."
        # In a change from X to Y, X is the superseded value, not authority to
        # write it merely because it occurs in the cited request. Ordinary source
        # phrases ("pull from checking") have no such replacement construction.
        if tool["kind"] == "state_modifying" and re.match(
                r"(?:update|modify|change|switch|set|adjust|edit|replace|swap|move)\b", command, re.I):
            changes = list(re.finditer(r"\bfrom\s+((?:(?![.!?;](?:\s|$)|\b(?:then|and|but|i|we|you)\b).)+?)"
                                       r"\s+to\s+(.+?)(?=[.!?;](?:\s|$)|$)", command, re.I))
            for path, value in scalar_fields(args):
                if isinstance(value, str) and any(_mentions_value(tool, path, value, change[1])
                        and not _mentions_value(tool, path, value, change[2]) for change in changes):
                    return f"The proposed value for {path} was replaced by the user's from/to correction."
        primitive_values = [(path, value) for path, value in scalar_fields(args)
                            if type(value) in (bool, int, float) and
                            not any(path == parent or path.startswith(parent + ".") for parent in bindings)]
        if tool["kind"] == "state_modifying" and any(
                not _supported_primitive(tool, path, value, command)
                for path, value in primitive_values):
            return _proposed_primitive_values(primitive_values)
        for argument, binding in bindings.items():
            try:
                source = successes[binding["call_id"]]
                result = source["result"]
                actual, bound = at_path(args, argument), at_path(result, binding["path"])
                # A lookup may qualify a returned identifier ("APT1, Portland" for APT1);
                # writes still need the exact returned value.
                qualified = (tool["kind"] == "read_only" and isinstance(actual, str) and isinstance(bound, str)
                             and len(bound.strip()) >= 2 and actual != bound
                             and re.search(r"(?<![A-Za-z0-9])" + re.escape(bound.strip()) + r"(?![A-Za-z0-9])", actual))
                if not qualified and (type(actual) is not type(bound) or actual != bound):
                    return "A proposed argument does not match the tool result."
                if tool["kind"] == "state_modifying" and isinstance(actual, (dict, list)):
                    delegated = (_field_scoped_result_delegation(argument, authorized_text) or
                                 _whole_result_delegation(authorized_text))
                    for path, value in scalar_fields(actual, prefix=argument):
                        if type(value) is bool:
                            explicit = _bound_leaf_values(path, command, _explicit_boolean_field_values)
                            expected = value
                        elif type(value) in (int, float):
                            explicit = _bound_leaf_values(path, command, _explicit_numeric_field_values)
                            expected = Decimal(str(value))
                        elif isinstance(value, str):
                            explicit = _bound_leaf_values(path, authorized_text, _explicit_string_field_values)
                            expected = " ".join(value.casefold().split())
                        else:
                            continue
                        if explicit and explicit != {expected}:
                            return "A proposed argument does not match the explicit user value."
                        if not explicit and not delegated:
                            return "A proposed argument does not match the explicit user value."
                if type(actual) in (int, float):
                    explicit = _explicit_numeric_field_values(argument, command)
                    if explicit and explicit != {Decimal(str(actual))}:
                        return "A proposed argument does not match the explicit user value."
                elif type(actual) is bool:
                    explicit = _explicit_boolean_field_values(argument, command)
                    if explicit and explicit != {actual}:
                        return "A proposed argument does not match the explicit user value."
                elif tool["kind"] == "state_modifying" and isinstance(actual, str):
                    explicit = _explicit_string_field_values(argument, authorized_text)
                    if explicit and explicit != {" ".join(actual.casefold().split())}:
                        return "A proposed argument does not match the explicit user value."
                    if (not explicit and not contains_value(actual, authorized_text) and
                            not argument.rsplit(".", 1)[-1].endswith("_id") and selection is None and
                            not _field_scoped_result_delegation(argument, authorized_text)):
                        return "A proposed argument does not match the explicit user value."
                if source["revision"] != self.revision and not (isinstance(actual, str) and contains_value(actual, supplied)):
                    return "An earlier result needs an explicit current reference before I can use it for this action."
            except (KeyError, IndexError, TypeError, ValueError):
                return "A proposed argument has no current successful source."
        for path, value in scalar_fields(args):
            description = ""
            spec = {"properties": tool.get("args", {})}
            for part in path.split("."):
                spec = spec.get("items", {}) if part.isdigit() else spec.get("properties", {}).get(part, {})
                if not isinstance(spec, dict):
                    spec = {}
            description = str(spec.get("description", ""))
            required_source = bool(re.search(r"\b(returned|result)\b", description, re.I))
            identifier = path.rsplit(".", 1)[-1].endswith("_id")
            bound = any(path == parent or path.startswith(parent + ".") for parent in bindings)
            if tool["kind"] == "state_modifying" and isinstance(value, str) and value and not bound:
                field = path.rsplit(".", 1)[-1].replace("_", " ")
                field_context = field + " " + description
                descriptive = bool(re.search(r"\b(summary|description|message|note|text|comment|query)\b", field_context, re.I))
                message_body = bool(re.search(r"\b(message|body|text|content)\b", field_context, re.I))
                # An enum/default validates a value; it does not authorize the write.
                field_parts = path.split(".")
                while field_parts and field_parts[-1].isdigit():
                    field_parts.pop()
                field_path = ".".join(field_parts) or path
                target_field = field_path.rsplit(".", 1)[-1].casefold().removesuffix("_id")
                if target_field in _FOR_TARGET_FIELDS | _TO_TARGET_FIELDS:
                    explicit = _explicit_string_field_values(field_path, authorized_text)
                    if explicit and explicit != {" ".join(value.casefold().split())}:
                        return f"Please supply {path}; I cannot invent that value for a state-changing action."
                    if not explicit and not _mentions_value(tool, path, value, mention_text):
                        return f"Please supply {path}; I cannot invent that value for a state-changing action."
                else:
                    if descriptive:
                        explicit = (_explicit_dictated_message_values(authorized_text)
                                    if message_body else set())
                    else:
                        explicit = _explicit_string_field_values(path, authorized_text)
                    normalized = " ".join(value.casefold().split())
                    if explicit and normalized not in explicit:
                        return f"The proposed value for {path} does not match the explicit user value."
                    affirmed = value.casefold() in {"true", "yes"} and _affirmed_predicate(args, path, mention_text)
                    if (not descriptive and not explicit and not affirmed
                            and not _mentions_value(tool, path, value, mention_text)):
                        return f"Please supply {path}; I cannot invent that value for a state-changing action."
            if not (required_source or identifier and tool["kind"] == "state_modifying"):
                continue
            explicit = isinstance(value, str) and _mentions_value(tool, path, value, supplied)
            if path not in bindings and (required_source or not explicit):
                return f"The value for {path} needs a successful result or an explicit user reference."
        return ""

    def _dispatch(self, step, *, retry=0, depth=0, selection=None, recited=False):
        if self._closed or self._turn_open or self._awaiting_clarification:
            return
        self._refresh_read_consumers()
        if not isinstance(step, dict) or not isinstance(step.get("api_name"), str):
            self._say("clarification_request", "I could not identify a valid tool for that action.")
            return
        name, args = step["api_name"], step.get("args", {})
        tool = self.tools.get(name)
        # Omitted user details do not make a declared required parameter optional.
        # Ask for the missing value instead of inventing it or passing null, in the
        # contract's words; the validator's paths and messages are evidence only.
        problems = validate_args(tool, args)
        if problems:
            self._say("clarification_request", argument_question(tool, args),
                      validation={"api_name": name, "problems": problems})
            return
        if depth > 3:
            self._say("clarification_request", "This request needs more steps than I can safely complete at once.")
            return
        grant = None
        if tool["kind"] == "state_modifying":
            step = self._recover_result_provenance(step, tool)
            if self._active_transcript_utterance is not None:
                for op in self.operations.values():
                    if (op["request_start"] == self._request_start and op["status"] == "not_submitted"
                            and not op.get("authority_released")):
                        self._consumed_grants.discard(op.get("authority_key"))
                        op["authority_released"] = True
            earlier = [op for op in self.operations.values() if
                    op["kind"] == "state_modifying" and op["request_start"] == self._request_start
                    and op["revision"] != self.revision and op["status"] != "not_submitted"]
            if self._active_transcript_utterance is not None and earlier:
                if all(not op.get("execution_admitted") and op["status"] in {"pending", "cancel_requested"}
                       for op in earlier):
                    # A trusted executor notification must prove no submission.
                    # Runners without this protocol conservatively remain deferred.
                    self._deferred_transcript_revision = self.revision
                    self._deferred_transcript_deadline = max(op.get("deadline", time.monotonic() + 3.5)
                                                             for op in earlier)
                    self._filler("I am checking whether the earlier request was submitted before acting.")
                else:
                    self._final("An earlier transcript already submitted an action. I must check its outcome before a revised transcript can authorize another action.")
                return False
            trace = []
            current = [op for op in self.operations.values() if op.get("request_start") == self._request_start
                       and op.get("kind") == "read_only"]
            grant = authorization_grant(step, tool, self._user_texts(), selection=selection,
                                        operations=self.operations.values(), history=self.messages[:self._request_start],
                                        trace=trace, lookup_done=any(op.get("status") == "success" for op in current),
                                        lookups=[op["result"] for op in current
                                                 if op.get("status") == "success" and isinstance(op.get("result"), dict)],
                                        lookups_pending=any(op.get("status") in {"pending", "cancel_requested"} for op in current),
                                        allow_attachment=not recited)
            rounds = getattr(self.planner, "follow_up_rounds", 0)
            if (not grant and trace and trace[-1].startswith("awaiting own lookup") and isinstance(rounds, int)
                    and self._follow_up_round < rounds
                    and any(op.get("status") in {"pending", "cancel_requested"} for op in current)):
                # The follow-up round re-plans once this request's lookup settles.
                self._emit("write_deferred", {"api_name": name, "gate": {"api_name": name, "reasons": trace}})
                return
            if not grant:
                # Several commands in one cited span ("update my passport ... and change my
                # license"), or a citation stretched over a later correction of another target:
                # re-cite once to the single clause that states this write's values.
                if not recited and any("commands for this action in the cited region" in reason
                                       or "retraction inside cited clause" in reason for reason in trace):
                    repaired = self._recited_step(step, tool)
                    if repaired is not None:
                        return self._dispatch(repaired, retry=retry, depth=depth, selection=selection, recited=True)
                self._say("clarification_request", "Please explicitly confirm the action and its target before I change anything.",
                          gate={"api_name": name, "reasons": trace or ["unrecorded"]})
                return
        if tool["kind"] == "read_only" and "retain_call_id" not in step:
            condition = self._read_condition(step, tool)
            if condition != "ok":
                # Held until this request's lookup settles; dropped when a result makes it false.
                reads_pending = any(op.get("request_start") == self._request_start and op.get("kind") == "read_only"
                                    and op.get("status") in {"pending", "cancel_requested"}
                                    for op in self.operations.values())
                # Inside a plan a later step may be the lookup that settles it: decide after the plan.
                in_plan = getattr(self, "_held_clarifications", None) is not None
                if condition == "pending" or condition == "unverified" and (reads_pending or in_plan):
                    self.__dict__.setdefault("_held_reads", []).append((self._request_start, deepcopy(step), depth))
                self._emit("read_held", {"api_name": name, "condition": condition})
                if condition == "unverified" and not reads_pending and not in_plan:
                    # Nothing running can settle the condition: never hold silently (the turn
                    # would get no answer); ask instead.
                    self._say("clarification_request", "Should I go ahead and look that up?")
                elif condition == "false" and in_plan:
                    self._false_hold = True  # _dispatch_plan answers if nothing else in the turn does
                elif condition == "false" and not any(op.get("request_start") == self._request_start
                                                      for op in self.operations.values()):
                    self._say("clarification_request", "Understood, I will not look that up. Anything else?")
                return
        if tool["kind"] == "read_only" and self._copied_schema_example(tool, args, name):
            # A small planner copies a contract example ("London", "headphones") when the
            # user never said it; that lookup is unrequested. Ask instead of calling it.
            self._say("clarification_request", "Could you tell me exactly what you would like me to look up?")
            return
        binding_error = self._binding_error(step, tool, args, grant, selection)
        if not binding_error and tool["kind"] == "state_modifying":
            binding_error = self._conflicting_spelling(args)
        if binding_error and tool["kind"] == "state_modifying" and (
                "cannot invent" in binding_error or "no current successful source" in binding_error
                or "needs a successful result" in binding_error):
            rounds = getattr(self.planner, "follow_up_rounds", 0)
            reads = [op for op in self.operations.values() if op.get("request_start") == self._request_start
                     and op.get("kind") == "read_only"]
            if (isinstance(rounds, int) and self._follow_up_round < rounds
                    and any(op.get("status") in {"pending", "cancel_requested"} for op in reads)):
                self._emit("write_deferred", {"api_name": name, "binding": binding_error})
                return
        if binding_error:
            if tool["kind"] == "state_modifying" and not recited and "cannot invent" in binding_error:
                repaired = self._recited_step(step, tool)
                if repaired is not None:
                    return self._dispatch(repaired, retry=retry, depth=depth, selection=selection, recited=True)
            self._say("clarification_request", binding_error)
            return
        # An omitted argument and its declared default are one effect for the ledger.
        write = tool["kind"] == "state_modifying"
        key = call_key(name, with_declared_defaults(args, tool) if write else args, write=write)
        retained, deferred_read = None, None
        if "retain_call_id" in step:
            source_id = step["retain_call_id"]
            source = self.operations.get(source_id) if isinstance(source_id, str) else None
            dependencies = self._read_dependencies(step, tool, selection)
            if (tool["kind"] != "read_only" or source is None or source["kind"] != "read_only"
                    or source.get("retained_from_call_id") or source.get("awaiting_not_submitted_call_id")
                    or source["key"] != key or source["revision"] == self.revision
                    or step.get("refresh", False) is not False
                    or call_key(name, source.get("read_dependencies", {})) != call_key(name, dependencies)):
                self._say("clarification_request", "I cannot retain that lookup with these dependencies. Please request a fresh lookup.")
                return False
            if source["status"] == "not_submitted":
                # A trusted executor receipt proves this creates no duplicate.
                step = {k: deepcopy(v) for k, v in step.items() if k != "retain_call_id"}
            elif (source.get("execution_admitted")
                  and source["status"] in {"pending", "cancel_requested"}):
                retained = source
            elif (not source.get("execution_admitted") and source["status"] == "cancel_requested"
                  and source["revision"] != self.revision):
                deferred_read = source
            else:
                self._say("clarification_request", "That lookup is not a confirmed in-flight read. Please request a fresh lookup.")
                return False
        # A fresh explicit user instruction can authorize the same effect again.
        # Reperceiving the same recording can change its transcript, not its user turn.
        authority_key = (self._request_start, grant) if grant is not None else None
        # A submitted effect cannot be repeated while its outcome is unsettled.
        if tool["kind"] == "state_modifying" and any(
                op["kind"] == "state_modifying" and op["key"] == key and
                op["request_start"] != self._request_start and
                op["status"] in {"pending", "unknown", "cancel_requested"}
                for op in self.operations.values()):
            self._final("That action was already submitted. Its recorded outcome must be checked before trying again.")
            return False
        same = [op for op in self.operations.values() if op["key"] == key and op["status"] not in {"not_submitted", "invalidated"} and
                (op["request_start"] == self._request_start if grant is not None else op["revision"] == self.revision)]
        if retained is not None or deferred_read is not None:
            marker = "retained_from_call_id" if retained is not None else "awaiting_not_submitted_call_id"
            source_id = (retained if retained is not None else deferred_read)["call_id"]
            same = [op for op in same if op.get(marker) == source_id]
        if same:
            last = same[-1]
            if not (tool["kind"] == "read_only" and retry == 1 and last["status"] == "error" and last["retry"] == 0):
                if last["status"] == "success":
                    if last["revision"] == self.revision:
                        self._final(self._render(last), call_id=last["call_id"])
                elif tool["kind"] == "state_modifying" and last["status"] != "pending":
                    self._final("That action was already submitted. Its recorded outcome must be checked before trying again.")
                return last["status"] in {"pending", "success"}
        if grant is not None:
            # Perception/schema revisions change evidence, never user permission.
            if authority_key in self._consumed_grants:
                # A second write cited the clause the first one used ("Mortgage from savings. I also
                # want my credit card from checking."): try the one unused clause that names every
                # value of this write, once, through every check again.
                repaired = None if recited else self._recited_step(step, tool)
                if repaired is not None:
                    return self._dispatch(repaired, retry=retry, depth=depth, selection=selection, recited=True)
                self._say("clarification_request", "I have already used that instruction for one action. Please explicitly authorize an additional action.")
                return
            self._consumed_grants.add(authority_key)
        self._sequence += 1
        call_id = f"call-{self._sequence}"
        operation_id = same[-1]["operation_id"] if same else f"operation-{self._sequence}"
        operation = {"operation_id": operation_id, "call_id": call_id, "api_name": name, "args": deepcopy(args), "kind": tool["kind"],
                     "request_start": self._request_start,
                     "revision": self.revision, "status": "pending", "key": key, "step": deepcopy(step),
                     "retry": retry, "depth": depth, "selection": deepcopy(selection), "authority_key": authority_key}
        if tool["kind"] == "read_only":
            operation["read_dependencies"] = self._read_dependencies(step, tool, selection)
        if retained is not None:
            # A new consumer owns presentation/continuation, never the original
            # execution's revision, step, authority, or admission. Omitted tasks
            # are not implicitly retained. Completed results are never cached.
            operation["retained_from_call_id"] = retained["call_id"]
            retained["continuation_retired"] = True
        if deferred_read is not None:
            operation["awaiting_not_submitted_call_id"] = deferred_read["call_id"]
        delay = tool.get("delay_range_ms", [0, 3000])
        upper = delay[1] if isinstance(delay, list) and len(delay) == 2 and type(delay[1]) in (int, float) else 3000
        operation["deadline"] = time.monotonic() + min(max(upper / 1000, 0), 30) + 0.5
        if self._tail_deadline is not None:
            operation["deadline"] = min(operation["deadline"], self._tail_deadline - 0.1)
        self.operations[call_id] = operation
        for key, value in args.items():
            if key in self.state["slots"] or key.endswith("_id"):
                self.state["slots"][key] = deepcopy(value)
        if retained is None and deferred_read is None:
            self._emit("tool_call", {"call_id": call_id, "api_name": name, "args": args})
        return True

    def _not_submitted(self, payload):
        """Trusted executor receipt; an admitted effect can never use this path."""
        call_id = payload.get("call_id")
        operation = self.operations.get(call_id) if isinstance(call_id, str) else None
        if (operation is None or payload.get("api_name") != operation["api_name"]
                or operation.get("execution_admitted")
                or operation.get("retained_from_call_id") or operation.get("awaiting_not_submitted_call_id")
                or operation["status"] not in {"pending", "cancel_requested"}):
            return
        operation.update(status="not_submitted", continuation_retired=True)
        if not operation.get("authority_released"):
            self._consumed_grants.discard(operation.get("authority_key"))
            operation["authority_released"] = True
        for consumer in list(self.operations.values()):
            if (consumer.get("awaiting_not_submitted_call_id") != call_id
                    or consumer["status"] not in {"pending", "cancel_requested"}):
                continue
            current = consumer["status"] == "pending" and consumer["revision"] == self.revision
            consumer.update(status="not_submitted", continuation_retired=True)
            step = {key: value for key, value in consumer["step"].items() if key != "retain_call_id"}
            dependencies = self._read_dependencies(step, self.tools.get(consumer["api_name"]), consumer["selection"])
            if (current and not self._turn_open and not self._awaiting_clarification
                    and call_key(consumer["api_name"], consumer["read_dependencies"]) == call_key(consumer["api_name"], dependencies)):
                self._dispatch(step, depth=consumer["depth"], selection=consumer["selection"])
        if (self._deferred_transcript_revision == self.revision
                and self._active_transcript_utterance is not None and not self._turn_open
                and not self._awaiting_clarification and operation["request_start"] == self._request_start
                and all(op["status"] == "not_submitted" for op in self.operations.values()
                        if op["kind"] == "state_modifying" and op["request_start"] == self._request_start
                        and op["revision"] != self.revision)):
            self._deferred_transcript_revision = None
            self._start_plan()

    def _result(self, payload):
        if not isinstance(payload.get("call_id"), str):
            return
        operation = self.operations.get(payload["call_id"])
        if operation is None or payload.get("api_name") != operation["api_name"]:
            return
        if operation["status"] in {"success", "error", "not_submitted", "invalidated"}:
            return  # Duplicate/conflicting notifications cannot rewrite terminal evidence.
        status, result = payload.get("status"), payload.get("result")
        if not isinstance(status, str) or status not in {"success", "error"} or not isinstance(result, dict):
            return
        if result.get("status", status) != status:
            return
        if operation.get("awaiting_not_submitted_call_id"):
            return  # No backend call exists for a deferred consumer.
        if operation.get("retained_from_call_id"):
            source = self.operations[operation["retained_from_call_id"]]
            if (source["status"] != status
                    or call_key(source["api_name"], source.get("result", {})) != call_key(source["api_name"], result)):
                return  # Consumers only receive the original execution's receipt.
        error_code = result.get("error")
        if not isinstance(error_code, str):
            error_code = "unknown_error"
        operation["status"], operation["result"] = status, deepcopy(result)
        for consumer in self.operations.values():
            if (consumer.get("awaiting_not_submitted_call_id") == operation["call_id"]
                    and consumer["status"] in {"pending", "cancel_requested"}):
                consumer.update(status="not_submitted", continuation_retired=True)
                if consumer["revision"] == self.revision and not self._turn_open and not self._awaiting_clarification:
                    self._say("clarification_request", "The earlier lookup completed before its admission was confirmed. Please request a fresh lookup.")
        if status == "error" and operation["kind"] == "state_modifying" and error_code not in {"invalid_args", "not_found", "unknown_tool"}:
            operation["status"] = "unknown"
        consumers = [op for op in self.operations.values()
                     if op.get("retained_from_call_id") == operation["call_id"]]
        for consumer in consumers:
            self._result({"call_id": consumer["call_id"], "api_name": operation["api_name"],
                          "status": status, "result": result})
        if consumers:
            return  # Never revive the original execution's continuation.
        if operation["revision"] != self.revision or self._turn_open or self._awaiting_clarification:
            return  # Keep the durable outcome without speaking or resuming suspended work.
        self._refresh_read_consumers()
        if operation["status"] == "invalidated":
            return  # A changed dependency cannot resurrect a retained consumer.
        self.tool_results.append({**self._operation_context(operation), "status": status})
        if status == "error":
            if operation.get("continuation_retired"):
                return
            if (operation["kind"] == "read_only" and operation["retry"] == 0 and
                    error_code in {"timeout", "unavailable", "temporarily_unavailable", "rate_limited"}):
                self._filler("The lookup failed temporarily. I am retrying it once.", recovery_id=operation["call_id"])
                retry_step = {key: value for key, value in operation["step"].items() if key != "retain_call_id"}
                self._dispatch(retry_step, retry=1, depth=operation["depth"], selection=operation["selection"])
            elif operation["kind"] == "state_modifying":
                self._final("I could not confirm the action's outcome. I will not repeat a state-changing request without checking it.")
                operation["result_announced"] = True
            else:
                self._final("Sorry, I was unable to complete the lookup. " + str(result.get("error", "Tool error")))
            return
        for key, value in result.items():
            # Tool prose remains evidence in tool_results, never a new user slot.
            # Returned identifiers retain their established snapshot role.
            identifier = type(value) in (int, float) or isinstance(value, str) and value and not re.search(r"\s", value)
            if key.endswith("_id") and identifier:
                self.state["slots"][key] = value
        if operation.get("continuation_retired"):
            return  # Keep the receipt/slots, but never resume expired work.
        self._continue_result(operation)
        # A conditional lookup held for this request's results is re-checked now: it runs
        # when the condition holds and is dropped when a returned price makes it false.
        held, self._held_reads = getattr(self, "_held_reads", []), []
        for request_start, step, depth in held:
            if request_start == self._request_start:
                self._dispatch(step, depth=depth)
        self._maybe_follow_up()

    def _maybe_follow_up(self):
        """Plan once more after this request's calls settle, for remaining requested work.

        Bounded by the planner's follow_up_rounds; only when every call of the current
        revision is terminal and at least one succeeded. All dispatch checks apply.
        """
        rounds = getattr(self.planner, "follow_up_rounds", 0)
        if (not isinstance(rounds, int) or self._follow_up_round >= rounds or self._closed or self._turn_open
                or self._awaiting_clarification or self._plan_task is not None):
            return
        current = [op for op in self.operations.values() if op["revision"] == self.revision]
        if (not current or any(op["status"] in {"pending", "cancel_requested"} for op in current)
                or not any(op["status"] == "success" for op in current)):
            return
        self._follow_up_round += 1
        self._follow_up_active = True
        self._planning_error = ("Follow-up round: the calls in tool_results are complete and already answered. "
            "Plan only actions the user requested in this turn that have not been done yet, such as a later "
            "step that needs a returned identifier or a second task. Never repeat a completed call. "
            "If nothing remains, return tool_calls [].")
        # A small planner extracts a second request's values into slots ("credit card ... from
        # checking") yet plans only the first call, then reports nothing left. Name the extracted
        # values no current call used; every gate still applies to anything it proposes.
        used = {str(value).casefold() for op in current for _, value in scalar_fields(op.get("args", {}))}
        unused = [f"{key}={value}" for key, value in self.state["slots"].items()
                  if isinstance(value, (str, int, float)) and not isinstance(value, bool)
                  and not key.endswith("_id") and str(value).strip() and str(value).casefold() not in used]
        if unused:
            self._planning_error += (" Slots you extracted that no call has used yet: " + ", ".join(unused[:8])
                + ". If they belong to an action the user requested and did not cancel or condition, and a declared "
                "tool does exactly that action, plan it now; never substitute a different kind of tool. Otherwise "
                "ignore them.")
        uncovered = self._uncovered_requests(current)
        if uncovered:
            self._planning_error += (" User requests in this turn that no call has handled yet: "
                + "; ".join(f'"{text}"' for text in uncovered)
                + ". Plan each one that a declared tool directly performs, in order, using returned results where "
                "needed; skip any the user cancelled or corrected, any whose condition the results make false, and "
                "any no declared tool performs.")
        self._start_plan()

    _REQUEST_VERBS = re.compile(r"\b(?:" + "|".join(("book", "reserve", "add", "include", "update", "change", "set",
        "switch", "modify", "adjust", "cancel", "remove", "order", "buy", "search", "find", "look", "track", "check",
        "calculate", "convert", "pay", "move", "swap", "replace", "use", "raise", "raised", "increase", "bump", "lower",
        "reduce", "decrease")) + r")\b")

    def _uncovered_requests(self, current):
        """Current-turn command clauses that no call of this revision cites or states a value of."""
        cited, values = set(), []
        for op in current:
            authorization = op.get("step", {}).get("authorization") if isinstance(op.get("step"), dict) else None
            if isinstance(authorization, dict) and isinstance(authorization.get("clauses"), list):
                cited |= set(authorization["clauses"])
            tool = self.tools.get(op.get("api_name"), {})
            values += [(op.get("api_name", ""), tool, path, str(value)) for path, value in scalar_fields(op.get("args", {}))
                       if value is not None and not isinstance(value, bool) and len(str(value).strip()) > 1]
        found = []
        for row in turn_clauses(self._user_texts()):
            text = row["text"]
            if (row["clause_id"] in cited or len(text.split()) < 3 or not self._REQUEST_VERBS.search(text)
                    or re.match(r"(?:let me|i think|you know)\b", text)):
                continue
            named_reads = {name for name, tool in self.tools.items() if isinstance(tool, dict) and tool.get("kind") == "read_only"
                           and _names_read_target(name, text)} if _READ_COMMAND.search(text) else set()
            stating = [tool for name, tool, path, value in values if _mentions_value(tool, path, value, text)
                       and (not named_reads or tool.get("kind") != "read_only" or name in named_reads)]
            # A change request ("update my max price to 1500, then search") is not handled by a
            # lookup that merely reuses its value.
            change = re.search(r"\b(?:update|change|set|raise|raised|increase|bump|lower|reduce|switch|modify|adjust)\b",
                               text)
            if stating and (not change or any(tool.get("kind") == "state_modifying" for tool in stating)):
                continue
            found.append(text.rstrip(",;"))
        return found[:4]

    def _continue_result(self, operation):
        if operation.get("result_announced") or operation.get("continuation_retired"):
            return
        next_step = operation["step"].get("after_result")
        if next_step is not None:
            if operation["api_name"] in PUBLIC_TOOLS:
                # A successful lookup is also a completed requested step, even
                # when it supplies the next call's arguments.
                self._final(self._render(operation), call_id=operation["call_id"])
            try:
                continuation, selection = self._continuation(next_step, operation)
            except (KeyError, IndexError, TypeError, ValueError):
                self._final(self._render(operation), call_id=operation["call_id"])
                if not self._repair_used:
                    self._repair_used = True
                    self._planning_error = "The proposed continuation could not select and bind an actual result. Inspect tool_results; never guess an identifier."
                    self._start_plan()
                elif self._plan_task is None:
                    # While the repair plan is still running it may yet bind this step (a planner
                    # attached one continuation under two lookups); do not preempt it.
                    self._say("clarification_request", "The returned options do not identify one safe next action. Please clarify your selection.")
                return
            if not self._dispatch(continuation, depth=operation["depth"] + 1, selection=selection):
                self._final(self._render(operation), call_id=operation["call_id"])
        else:
            question = self._flight_booking_question(operation)
            if question:
                self.state["intent"] = "book_flight"
            self._final(self._render(operation), call_id=operation["call_id"])
            if question:
                self._say("clarification_request", question)

    def _continuation(self, step, operation):
        if not isinstance(step, dict):
            raise ValueError("Invalid continuation")
        step = deepcopy(step)
        root, prefix = operation["result"], ""
        selector = step.pop("select", None)
        if selector is not None:
            values = at_path(root, selector["path"])
            where = selector["where"]
            if not isinstance(values, list) or not isinstance(where, dict) or not where:
                raise ValueError("Selection needs an array and explicit conditions")
            matches = []
            for index, value in enumerate(values):
                try:
                    if all(type(at_path(value, path)) is type(expected) and at_path(value, path) == expected
                           for path, expected in where.items()):
                        matches.append((index, value))
                except (KeyError, IndexError, TypeError, ValueError):
                    continue  # An incomplete row cannot satisfy the selection.
            if len(matches) != 1:
                raise ValueError("The selection is not unique")
            index, root = matches[0]
            prefix = f"{selector['path']}.{index}."
        bindings = step.pop("bindings", {})
        if not isinstance(bindings, dict):
            raise ValueError("Invalid bindings")
        args = step.setdefault("args", {})
        sources = step.setdefault("result_bindings", {})
        if not isinstance(args, dict) or not isinstance(sources, dict):
            raise ValueError("Continuation arguments and sources must be objects")
        for argument, path in bindings.items():
            if not isinstance(argument, str) or not isinstance(path, str):
                raise ValueError("Bindings must use string paths")
            value = at_path(root, path)
            parent = args
            parts = argument.split(".")
            for part in parts[:-1]:
                if not isinstance(parent, dict):
                    raise ValueError("Nested bindings require object arguments")
                parent = parent.setdefault(part, {})
            if not isinstance(parent, dict):
                raise ValueError("Nested bindings require object arguments")
            parent[parts[-1]] = deepcopy(value)
            sources[argument] = {"call_id": operation["call_id"], "path": prefix + path}
        # A "{result.path}" template left in an argument is a guessed reference to
        # an unseen result, never a literal user value: repair from actual results.
        if any(isinstance(value, str) and re.fullmatch(r"\{[\w.\[\]-]+\}", value.strip())
               for _, value in scalar_fields(args)):
            raise ValueError("Unresolved result placeholder in continuation arguments")
        return step, selector["where"] if selector is not None else None

    def _flight_booking_question(self, operation):
        """Recover only a verified, unfinished documented flight-booking goal."""
        from datetime import date
        from .planner import _flight_discovery_search, _flight_text_goal, _literal_name_words
        args, step = operation["args"], operation["step"]
        if (operation["api_name"] != "flight_search" or operation["kind"] != "read_only" or operation["depth"] != 0
                or operation["request_start"] != self._request_start or not self.messages or self._latest_frame is not None
                or set(args) - {"destination", "date"} or self.state["slots"] != args
                or "?" in str(step.get("response_template", ""))
                or len({op["operation_id"] for op in self.operations.values() if op["revision"] == self.revision}
                       | {operation["operation_id"]}) != 1):
            return None
        search = _flight_discovery_search(self.tools, args)
        if search is None:
            return None
        row_shape = {"flight_id": "string", "depart": "string", "price_usd": "number"}
        result, rows = operation["result"], operation["result"].get("flights")
        row_contract = {"kind": "read_only", "args": {k: {"type": v, "required": True} for k, v in row_shape.items()}}
        if (set(result) - {"status", "flights"} or not isinstance(rows, list) or not rows
                or any(validate_args(row_contract, row) or not row["flight_id"] or re.search(r"\s", row["flight_id"]) for row in rows)):
            return None
        if self.messages[self._request_start]["event_type"] in {"user_speech_chunk", "interruption"}:
            goal = _flight_text_goal(self._context(), completed_read_args=args)
            if (goal is None
                    or any(validate_args(search, prefix["args"]) for prefix in goal["prefixes"])
                    or any(op["kind"] == "state_modifying" and op["request_start"] >= goal["start"]
                           for op in self.operations.values())):
                return None
            return "Which returned flight should I book, and what passenger name should I use?"
        atom = r"[^\W\d_]+(?:[-'][^\W\d_]+)*"
        name = rf"({atom}(?: +{atom})*?)"
        repair = rf"(?:(?:wait,? +)?actually,? +)?make +(?:that|it) +{name}[.!?]?"
        # Audio still requires every source to belong to this verified current turn.
        start = self._request_start
        if any(op["kind"] == "state_modifying" and op["request_start"] >= start for op in self.operations.values()):
            return None
        utterances = []
        for index in range(start, len(self.messages)):
            message = self.messages[index]
            payload, kind = message["payload"], message["event_type"]
            observation = self.observations.get(index, {})
            if (kind != "user_audio_chunk" or message["revision"] != self.revision
                    or observation.get("type") != "audio" or type(observation.get("message_index")) is not int
                    or observation["message_index"] != index or observation.get("uncertain") is not False
                    or payload.get("end_of_turn") is not (index == len(self.messages) - 1)):
                return None
            utterances.append(observation.get("transcript"))
        if not utterances or any(not isinstance(text, str) or any(ord(c) < 32 for c in text) for text in utterances):
            return None
        suffix = ""
        if "date" in args:
            literal_date = args["date"]
            if re.fullmatch(r"today|tomorrow|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday", literal_date, re.I) is None:
                try:
                    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", literal_date) is None:
                        return None
                    date.fromisoformat(literal_date)
                except ValueError:
                    return None
            suffix = rf" +(?:on|for) +{re.escape(literal_date)}"
        command = rf"(?:(?:uh|um),? +)?(?:can +you +)?(?:please +)?(?:book|reserve) +a +flight +to +{name}{suffix}[.!?]?"
        destination = None
        for index, text in enumerate(utterances):
            match = re.fullmatch(repair if index else command, text.strip(), re.I)
            if match is None:
                return None
            destination = match[1]
            if not _literal_name_words(destination) or validate_args(search, {**args, "destination": destination}):
                return None
        if destination == args.get("destination"):
            return "Which returned flight should I book, and what passenger name should I use?"
        return None

    def _render(self, operation):
        template = operation["step"].get("response_template")
        lead = "Done. " if operation.get("kind") == "state_modifying" else "Here is what I found: "
        if operation["step"].get("result_evidence") is not None and not self._source_matches(operation, template):
            return "The returned source does not confirm the requested target, so I cannot support that explanation with this result."
        raw = operation.get("result")
        if (operation.get("status") != "success" or operation.get("api_name") in PUBLIC_TOOLS and isinstance(raw, dict) and
                (raw.get("status", "success") != "success" or "error" in raw)):
            return "I do not have a successful tool result confirming that outcome."
        result, quoted_paths = self._presentation_result(operation)
        omitted = result != operation["result"]
        if operation.get("api_name") in PUBLIC_TOOLS:
            spoken = spoken_result(operation["api_name"], operation.get("args"), result) if not omitted and not quoted_paths else None
            return spoken if spoken is not None else self._compact_result(result, quoted_paths, omitted, lead=lead)
        cited_answer = self._cited_answer(operation, result, quoted_paths, omitted)
        if cited_answer is not None:
            return cited_answer
        if isinstance(template, str) and template.strip():
            try:
                if not quantitative_template_is_bound(template, result):
                    return self._compact_result(result, quoted_paths, omitted, lead=lead)
                consumed, selected_omissions = [], []
                def substitute(match):
                    value = at_path(result, match[1])
                    if value != at_path(operation["result"], match[1]):
                        selected_omissions.append(match[1])
                    # A status code or an echoed input is not an answer to a lookup.
                    if match[1] != "status" and not (
                            match[1] in operation["args"] and value == operation["args"][match[1]]):
                        consumed.append(match[1])
                    if any(match[1] == path or match[1].startswith(path + ".") or path.startswith(match[1] + ".")
                           for path in quoted_paths):
                        return "quoted tool data: " + json.dumps(value, ensure_ascii=False)
                    return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
                pattern = r"\{([^{}]+)\}"
                literals = re.sub(pattern, "", template)
                text = re.sub(pattern, substitute, template).strip()
                if "{" not in literals and "}" not in literals and not self._unconfirmed_claim(text):
                    return (text + (" Some tool metadata was omitted." if selected_omissions else "") if consumed
                            else text + " " + self._compact_result(result, quoted_paths, omitted, lead=lead))
            except (KeyError, IndexError, TypeError, ValueError):
                pass
        return self._compact_result(result, quoted_paths, omitted, lead=lead)

    def _cited_answer(self, operation, result, quoted_paths, omitted):
        """Keep returned answer content with its source, never template claims."""
        if operation.get("kind", "read_only") != "read_only":
            return None
        template = operation["step"].get("response_template")
        evidence = operation["step"].get("result_evidence")
        paths = re.findall(r"\{([^{}]+)\}", template) if isinstance(template, str) else []
        source_paths = {evidence["path"]} if isinstance(evidence, dict) else set()
        for path in paths:
            parent, _, field = path.rpartition(".")
            try:
                record = at_path(result, parent)
            except (KeyError, IndexError, TypeError, ValueError):
                continue
            if (field in {"title", "name", "doc", "page", "url", "answer"} and isinstance(record, dict) and
                    (set(parent.split(".")) & _SOURCE_FIELDS or
                     "doc" in record or "url" in record)):
                source_paths.add(path)
        if not source_paths:
            # Missing citation placeholders cannot lend returned sources to
            # static template prose. Preserve the projected result instead.
            def has_source(value, depth=0):
                if depth > 20:
                    return False
                if isinstance(value, dict):
                    return (bool(set(value) & _SOURCE_FIELDS) or
                            bool(set(value) & {"doc", "url"} and set(value) & {"title", "name"}) or
                            any(has_source(item, depth + 1) for item in value.values()))
                return isinstance(value, list) and any(has_source(item, depth + 1) for item in value)
            if not has_source(operation["result"]):
                return None
            selected = {}
            for path in paths:
                parts = path.split(".")
                answer_index = next((index for index, field in enumerate(parts) if field in _ANSWER_FIELDS), None)
                if answer_index is None:
                    continue
                parent = ".".join(parts[:answer_index])
                try:
                    at_path(result, path)
                    record = at_path(result, parent)
                except (KeyError, IndexError, TypeError, ValueError):
                    continue
                # Unwrap the selected answer up to its sources, but never cross
                # a list boundary into a different returned record.
                while isinstance(record, dict) and parent and not set(record) & _SOURCE_FIELDS:
                    ancestor = parent.rpartition(".")[0]
                    owner = at_path(result, ancestor)
                    if not isinstance(owner, dict):
                        break
                    parent, record = ancestor, owner
                if isinstance(record, dict):
                    selected[parent] = record
            return " ".join(self._compact_result(record, quoted_paths, omitted, path=parent + "." if parent else "")
                            for parent, record in selected.items()) if selected else self._compact_result(result, quoted_paths, omitted)
        parents = {path.rpartition(".")[0] for path in source_paths}
        if len(parents) != 1:
            return "The response cites multiple records. Please clarify which returned reference to use."
        parent = parents.pop()
        try:
            record = at_path(result, parent)
        except (KeyError, IndexError, TypeError, ValueError):
            return self._compact_result(result, quoted_paths, omitted)
        if not isinstance(record, dict):
            return self._compact_result(result, quoted_paths, omitted)
        if any(parent == path or parent.startswith(path + ".") for path in quoted_paths):
            return self._compact_result(result, quoted_paths, omitted)

        # Explicit answer fields and one structural source association;
        # a title match establishes relevance, not entailment of generated prose.
        def answers(value, prefix="", primary=False):
            if prefix in quoted_paths:
                return []
            if not primary:
                if not isinstance(value, dict):
                    return []
                keys = [key for key in value if key in _ANSWER_FIELDS]
                if not keys:
                    keys = [key for key in value if key in {"payload", "data", "body", "content", "result", "response"}]
                    if len(keys) != 1:
                        return []
                return [text for key in keys for text in answers(
                    value[key], f"{prefix}.{key}" if prefix else key, key in _ANSWER_FIELDS)]
            if isinstance(value, str):
                return [value] if value.strip() else []
            if isinstance(value, list):
                return [text for index, item in enumerate(value)
                        for text in answers(item, f"{prefix}.{index}", True)]
            if isinstance(value, dict):
                entries = []
                for key, item in value.items():
                    parts = answers(item, f"{prefix}.{key}", True)
                    if parts:
                        entries.append(str(key) + ": " + " ".join(parts))
                return ["{" + "; ".join(entries) + "}"] if entries else []
            return [] if value is None else [json.dumps(value)]

        content = answers(record, parent)
        returned_answer = bool(content)
        # A sibling answer can cite a single source in the same wrapper. Never
        # take an answer from another row, another call, or an ambiguous list.
        parts = parent.split(".") if parent else []
        if not content and len(parts) >= 2 and parts[-1].isdigit() and parts[-2] in _SOURCE_FIELDS:
            owner_path = ".".join(parts[:-2])
            owner = at_path(result, owner_path)
            sources = owner[parts[-2]]
            sibling_answer = answers(owner, owner_path)
            returned_answer = returned_answer or bool(sibling_answer)
            if (parts[-2] != "pages" and isinstance(sources, list) and len(sources) == 1 and
                    not any(owner.get(field) for field in _SOURCE_FIELDS - {parts[-2]})):
                content = sibling_answer
        locator = {key: record[key] for key in ("doc", "page", "title", "name", "url")
                   if key in record and isinstance(record[key], (str, int, float)) and not isinstance(record[key], bool)}
        if not locator:
            return self._compact_result(record, quoted_paths, omitted, path=parent + "." if parent else "")
        general = self._general_function(operation)
        function = general if not returned_answer else ""
        unclassified = function and set(at_path(operation["result"], parent)) - (set(locator) | {"status"})
        wrapper_data = {}
        if general and len(parts) >= 2 and parts[-1].isdigit() and parts[-2] in _SOURCE_FIELDS:
            owner = at_path(result, ".".join(parts[:-2]))
            # Keep lookup-level facts separate from the selected reference. Do
            # not attach another source list or another result row to its citation.
            wrapper_data = {key: value for key, value in owner.items()
                            if key not in _SOURCE_FIELDS | _ANSWER_FIELDS
                            and not (key in {"status", "search_mode"} and isinstance(value, str))}
            if wrapper_data:
                function = ""
        prefix = ""
        if isinstance(evidence, dict) and evidence.get("target_basis") == "printed_text":
            prefix = "If you mean the item labelled " + json.dumps(evidence["contains"], ensure_ascii=False) + ", "
        if unclassified:
            # A pre-result generalization must not replace unfamiliar actual
            # content, including capability flags outside the named prose roles.
            text = self._compact_result(record, quoted_paths, omitted, path=parent + "." if parent else "")
            function = ""
        elif function:
            text = "That type of item is generally used to " + function.removesuffix(".") + "."
        else:
            text = ("The returned reference states: " + " ".join(content) if content else
                    "The lookup returned a reference, but no answer text establishing the requested explanation.")
        text = prefix + text[0].lower() + text[1:] if prefix else text
        text += (" The lookup returned this reference: " if function else " Reference: ")
        text += "; ".join(key + " " + str(value) for key, value in locator.items()) + "."
        if wrapper_data:
            text += " The lookup also returned: " + json.dumps(wrapper_data, ensure_ascii=False) + "."
        for path in sorted(quoted_paths):
            text += " Quoted tool data (" + path + "): " + json.dumps(at_path(result, path), ensure_ascii=False)
        return text + (" Some tool metadata was omitted." if omitted else "")

    def _general_function(self, operation):
        """Admit separately attributed background knowledge, not a truth check."""
        step = operation["step"]
        value, evidence = step.get("general_function"), step.get("result_evidence")
        if (not isinstance(value, str) or not value.strip() or len(value) > 240 or
                not any(char.isalpha() for char in value) or value.splitlines() != [value] or
                re.search(r"[{}\[\]`]|\b[a-z][a-z0-9+.-]*://|www\.", value, re.I)):
            return ""
        if (operation.get("kind") != "read_only" or operation.get("status") != "success" or
                operation.get("revision") != self.revision or step.get("after_result") is not None or
                step.get("authorization") is not None or not isinstance(evidence, dict) or
                evidence.get("target_basis") != "printed_text" or
                not isinstance(evidence.get("path"), str) or evidence["path"].rsplit(".", 1)[-1] not in {"title", "name"}):
            return ""
        index = self._latest_frame
        if (type(index) is not int or not 0 <= index < len(self.messages) or
                self.messages[index].get("event_type") != "video_frame"):
            return ""
        label = selected_printed_label(self.observations.get(index), index)
        if label is None or evidence.get("contains") != label:
            return ""
        return value.strip()

    def _presentation_result(self, operation):
        """Project ancillary fields for output only; raw evidence keeps its shape.

        Named field roles are a bounded policy, not a prose classifier.
        A return schema with explicit presentation roles could replace this list.
        """
        ancillary = {"auxiliary", "metadata", "annotation", "annotations", "commentary",
                     "note", "notes", "debug", "diagnostic", "diagnostics"}
        def label(value):
            value = re.sub(r"([a-z])([A-Z])", r"\1 \2", value)
            value = unicodedata.normalize("NFC", re.sub(r"['\u2019]s\b", "", value.casefold()))
            return " ".join("".join(char if char.isalnum() or unicodedata.category(char).startswith("M")
                                    else " " for char in value).split())

        def fields(value, prefix="", depth=0):
            if depth > 20:
                return
            if isinstance(value, dict):
                for key, item in value.items():
                    path = prefix + str(key)
                    name = label(str(key))
                    if name.split()[-1:] and name.split()[-1] in ancillary:
                        yield path, name
                    else:
                        yield from fields(item, path + ".", depth + 1)
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    yield from fields(item, prefix + str(index) + ".", depth + 1)

        paths = dict(fields(operation["result"]))
        # A named field request cannot silently expose the same field from a
        # different successful call. Ambiguous requests need an API/path name.
        peers = [op for op in self.operations.values() if op is not operation and
                 op.get("status") == "success" and op.get("revision") == self.revision]
        parts, ended = [], False
        for index, text in self._user_texts():
            if ended:
                parts = []
            parts.append(text)
            ended = self.messages[index]["payload"].get("end_of_turn") is True
        supplied = " ".join(parts).strip()
        # This optional readout is a complete direct request, not an English
        # authorization parser. No leftover reported/conditional clauses qualify.
        command = re.fullmatch(r"(?:please\s+)?(?:quote|read|show|display|include|list|return)\s+(?:the\s+)?(.+?)[.!?]?",
                               supplied, re.I | re.S)
        if re.search(r'''["\u201c\u201d`\u2018]|(?<!\w)['\u2019]|['\u2019](?!\w)''', supplied):
            command = None
        quoted_paths = set()
        if command:
            request = re.split(r"\s+(?:from|in|with|for|returned\s+with)\s+", command[1], maxsplit=1, flags=re.I)
            subject = request[0].strip()
            qualifier = re.sub(r"^the ", "", label(request[1])) if len(request) == 2 else None
            matches = []
            for source in [operation, *peers]:
                for path, name in fields(source["result"]):
                    related = {label(source["api_name"]), label(source["api_name"]).split()[0]}
                    related.update(label(part) for part in path.split(".")[:-1] if not part.isdigit())
                    related.update(item.removesuffix("s") for item in list(related))
                    if qualifier is not None and qualifier not in related:
                        continue
                    selected = path if label(subject) in {name, label(path)} else None
                    components = subject.split(".")
                    # Resolve accepted aliases against unique actual keys. Never
                    # fall back to the whole parent when descendant lookup fails.
                    for prefix in (path.split("."), [path.rsplit(".", 1)[-1]]):
                        if len(components) <= len(prefix) or any(label(a) != label(b) for a, b in zip(components, prefix)):
                            continue
                        selected = path
                        value = at_path(source["result"], path)
                        for component in components[len(prefix):]:
                            if isinstance(value, dict):
                                keys = [key for key in value if label(str(key)) == label(component)]
                                if len(keys) != 1:
                                    selected = None
                                    break
                                key = keys[0]
                            elif isinstance(value, list) and component.isdigit() and int(component) < len(value):
                                key = int(component)
                            else:
                                selected = None
                                break
                            value = value[key]
                            selected += "." + str(key)
                        break
                    if selected is not None:
                        matches.append((source, selected))
            if len(matches) == 1 and matches[0][0] is operation:
                quoted_paths.add(matches[0][1])

        def project(value, prefix="", depth=0, restricted=False):
            if depth > 20:
                return "additional nested details"
            path = prefix[:-1]
            restricted = restricted or path in paths
            if restricted and not any(path == chosen or path.startswith(chosen + ".") or chosen.startswith(path + ".")
                                      for chosen in quoted_paths):
                return "[omitted tool metadata]"
            if isinstance(value, dict):
                return {key: project(item, prefix + str(key) + ".", depth + 1, restricted)
                        for key, item in value.items()
                        if not (restricted or prefix + str(key) in paths) or any(
                            prefix + str(key) == chosen or (prefix + str(key)).startswith(chosen + ".") or
                            chosen.startswith(prefix + str(key) + ".") for chosen in quoted_paths)}
            if isinstance(value, list):
                # Keep every position so a template cannot select a different row.
                return [project(item, prefix + str(index) + ".", depth + 1, restricted) for index, item in enumerate(value)]
            return value
        return project(operation["result"]), quoted_paths

    @staticmethod
    def _source_matches(operation, template):
        """Check a named cited record, not semantic entailment of arbitrary prose."""
        evidence = operation["step"]["result_evidence"]
        if not isinstance(evidence, dict) or not isinstance(template, str):
            return False
        path, requested = evidence.get("path"), evidence.get("contains")
        if not isinstance(path, str) or not isinstance(requested, str) or "{" + path + "}" not in template:
            return False
        try:
            actual = at_path(operation["result"], path)
        except (KeyError, IndexError, TypeError, ValueError):
            return False
        if not isinstance(actual, str):
            return False
        def words(value):
            value = unicodedata.normalize("NFC", value.casefold())
            return " ".join("".join(char if char.isalnum() or unicodedata.category(char).startswith("M")
                                    else " " for char in value).split())
        wanted = words(requested)
        return any(char.isalnum() for char in wanted) and " " + wanted + " " in " " + words(actual) + " "

    @staticmethod
    def _compact_result(result, quoted_paths=(), omitted=False, *, path="", lead="Here is what I found: "):
        """Bounded factual fallback for unfamiliar schemas, without another model call."""
        def render(value, depth=0, path=""):
            prefix = ""
            primary = bool(set(path.split(".")) & (_ANSWER_FIELDS | _SOURCE_FIELDS))
            if path[:-1] in quoted_paths:
                depth = 0
                if path[:-1].rsplit(".", 1)[-1].isdigit():
                    prefix = "quoted tool data: "
            if isinstance(value, dict):
                if depth > 20:
                    return "additional nested details"
                items = list(value.items())
                if not primary and any(isinstance(item, (dict, list)) and key not in _SOURCE_FIELDS
                                       for key, item in items):
                    # A structured response's records are the fallback answer.
                    # Do not volunteer prose metadata alongside those records;
                    # primary prose and explicitly requested metadata still belong.
                    items = [(key, item) for key, item in items if not isinstance(item, str)
                             or item and not re.search(r"\s", item)
                             or key in _ANSWER_FIELDS
                             or path + str(key) in quoted_paths]
                selected = [item for index, item in enumerate(items)
                            if primary or index < 6 or item[0] in _ANSWER_FIELDS | _SOURCE_FIELDS]
                text = "; ".join(str(key).replace("_", " ") +
                                 (" (quoted tool data)" if path + str(key) in quoted_paths else "") + ": " +
                                 render(item, depth + 1, path + str(key) + ".")
                                 for key, item in selected)
                return prefix + (text + (f"; {len(items) - len(selected)} more fields" if len(items) > len(selected) else "") or "empty object")
            if isinstance(value, list):
                if not value:
                    return prefix + "no entries"
                count = len(value) if primary else min(6, len(value)) if all(isinstance(item, str) for item in value) else 1
                requested = sorted({int(chosen[len(path):].split(".")[0]) for chosen in quoted_paths
                                    if chosen.startswith(path) and chosen[len(path):].split(".")[0].isdigit()})
                indices = requested[:6] if requested else range(count)
                first = "; ".join(render(value[index], depth + 1, path + str(index) + ".") for index in indices)
                return prefix + first + (f"; {len(value) - len(indices)} additional entries returned" if len(value) > len(indices) else "")
            if isinstance(value, str):
                text = value.strip() if primary else " ".join(value.split())
                if not primary:
                    text = text[:180] + ("..." if len(text) > 180 else "")
                return prefix + (json.dumps(text, ensure_ascii=False) if any(path.startswith(parent + ".") for parent in quoted_paths) else text)
            return prefix + json.dumps(value, ensure_ascii=False)
        body = {key: value for key, value in result.items() if key != "status"} if isinstance(result, dict) else result
        if not body:
            if omitted:
                return "The tool completed successfully. Its metadata was omitted from this answer."
            return "The tool completed successfully and returned no additional details."
        # Plain spoken lead: "Returned information" was garbled by synthesis and
        # transcription ("Returned in, formation") and read as a data dump.
        return lead + render(body, path=path) + "." + (" Some tool metadata was omitted." if omitted else "")

    def _unconfirmed_claim(self, text):
        # Completion words are tied to available write descriptors, not domains.
        for name, tool in self.tools.items():
            if not isinstance(name, str) or not isinstance(tool, dict) or tool.get("kind") != "state_modifying":
                continue
            verb = name.rsplit(".", 1)[-1].split("_")[0].casefold()
            forms = {verb + "d" if verb.endswith("e") else verb + "ed"}
            if verb.endswith("y"):
                forms.add(verb[:-1] + "ied")
            if verb == "cancel":
                forms.add("cancelled")
            if verb == "send":
                forms.add("sent")
            if verb == "buy":
                forms.add("bought")
            if any(re.search(r"\b" + re.escape(form) + r"\b", text, re.I) for form in forms):
                if not any(op["api_name"] == name and op["status"] == "success" and op["revision"] == self.revision
                           for op in self.operations.values()):
                    return True
        return False
