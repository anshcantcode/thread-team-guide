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

from .authorization import authorization_grant, contains_value
from .schema import at_path, call_key, scalar_fields, selected_printed_label, validate_args


_ANSWER_FIELDS = {"answer", "instructions", "instruction", "explanation", "guidance",
                  "warning", "warnings", "findings", "paragraphs", "steps"}
_SOURCE_FIELDS = {"sources", "references", "citations", "pages"}
_FOR_TARGET_FIELDS = {"account", "client", "contact", "customer", "employee", "guest",
                      "member", "owner", "passenger", "patient", "person", "recipient", "user"}
_TO_TARGET_FIELDS = {"destination", "location", "target"}
_NUMBER_LITERAL = re.compile(
    r"(?<![\w.-])[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?(?![\w.-])")


def _has_exact_field_value(path, value, command):
    parts = path.split(".")
    aliases = {path, " ".join(part.replace("_", " ") for part in parts)}
    literal = (r"(?P<value>true|false)\b" if type(value) is bool
               else r"(?P<value>" + _NUMBER_LITERAL.pattern + r")")
    found = set()
    for alias in aliases:
        field = r"(?<![\w.])" + re.escape(alias) + r"(?![\w.])"
        pattern = (field +
                   r"\s*(?:(?:=|:)\s*|\b(?:to|is|equals?|of)\b(?:\s+exactly)?\s+)?" + literal)
        for match in re.finditer(pattern, command, re.I):
            try:
                found.add(match["value"].casefold() == "true" if type(value) is bool
                          else Decimal(match["value"]))
            except InvalidOperation:
                pass
    expected = value if type(value) is bool else Decimal(str(value))
    return found == {expected}


def _explicit_numeric_field_values(path, command):
    parts = path.split(".")
    aliases = {path, " ".join(part.replace("_", " ") for part in parts)}
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
    return found


def _explicit_boolean_field_values(path, command):
    parts = path.split(".")
    aliases = {path, " ".join(part.replace("_", " ") for part in parts)}
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
    parts = path.split(".")
    aliases = {path, " ".join(part.replace("_", " ") for part in parts)}
    found = set()
    for alias in aliases:
        field = r"(?<![\w.])" + re.escape(alias) + r"(?![\w.])"
        pattern = (field +
                   r"\s*(?:(?:=|:)\s*|\b(?:to|is|equals?|of)\b(?:\s+exactly)?\s+)?" +
                   r"(?P<value>(?!\s*\b(?:for|to|and|but|then|with|from|using|based|selected|"
                   r"returned|result|results|lookup|according)\b)[^,;.!?]+?)" +
                   r"(?=\s+\b(?:for|and|but|then|with|from)\b|[,;.!?]|$)")
        found.update(" ".join(match["value"].casefold().split())
                     for match in re.finditer(pattern, command, re.I))

    field_name = parts[-1].casefold().removesuffix("_id")
    relation = ("for" if field_name in _FOR_TARGET_FIELDS else
                "to" if field_name in _TO_TARGET_FIELDS else None)
    if relation:
        pattern = (r"\b" + relation + r"\s+(?P<value>.+?)" +
                   r"(?=\s+\b(?:and|but|then)\b|[,;.!?]|$)")
        found.update(" ".join(match["value"].casefold().split())
                     for match in re.finditer(pattern, command, re.I))
    return found


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
        self._planning_error = None
        self._consumed_grants = set()

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
                for result_pass in (False, True):
                    for event in batch:
                        is_result = isinstance(event, dict) and event.get("event_type") == "tool_result"
                        if is_result == result_pass:
                            if is_result:
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
        return {key: deepcopy(operation[key]) for key in
                ("operation_id", "call_id", "api_name", "args", "kind", "revision", "status", "result")
                if key in operation}

    def _emit(self, action, payload):
        if not self._closed:
            self.out_queue.put_nowait({"action": action, "payload": deepcopy(payload),
                                       "state_snapshot": self.snapshot()})

    def _say(self, action, text):
        if isinstance(text, str) and text.strip():
            if action == "clarification_request":
                self._awaiting_clarification = True
            self._emit(action, {"text": text.strip()})

    def _filler(self, text, *, recovery_id=None):
        # One acknowledgement per completed user turn, one per bounded read retry.
        seen, key = ((self._retry_acknowledged, recovery_id) if recovery_id is not None
                     else (self._acknowledged, self.revision))
        if key in seen:
            return
        seen.add(key)
        self._fillers.append(text)
        self._say("filler_speech", text)

    def _final(self, text):
        key = (self.revision, text)
        if key not in self._finals:
            self._finals.add(key)
            self._say("final_response", text)

    def _invalidate(self):
        self.revision += 1
        self._repair_used = False
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
                    self._invalidate()
                self.tools = deepcopy(raw)
                if resume:
                    self._start_plan()
        elif kind == "video_frame":
            resume = self._request_pending()
            if resume:
                self._invalidate()
            self._append_message(kind, payload)
            self._latest_frame = len(self.messages) - 1
            if resume:
                self._start_plan()
        elif kind in {"user_speech_chunk", "user_audio_chunk", "interruption"}:
            interruption = kind == "interruption"
            if not self._turn_open or interruption:
                # Retain planning memory, but hide it before cancellation emits a snapshot.
                self._state_current = False
                self._invalidate()
                self._request_start = len(self.messages)
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
            self._start_plan()
        elif kind == "tool_result":
            self._result(payload)
        elif kind == "scenario_end":
            # The harness continues sending tool results in its finishing window.
            self._tail_deadline = time.monotonic() + 6
            for op in self.operations.values():
                if "deadline" in op:
                    op["deadline"] = min(op["deadline"], self._tail_deadline - 0.1)

    def _context(self):
        return deepcopy({"tools": self.tools, "state": self.state, "messages": self.messages,
                         "tool_results": self.tool_results, "revision": self.revision,
                         "current_turn_start": self._request_start, "latest_frame_index": self._latest_frame,
                         "observations": list(self.observations.values()),
                         "actions": [self._operation_context(op) for op in self.operations.values()],
                         "planning_error": self._planning_error,
                         "tail_remaining_ms": (max(0, (self._tail_deadline - time.monotonic()) * 1000)
                                               if self._tail_deadline is not None else None)})

    def _request_pending(self):
        return not self._turn_open and not self._awaiting_clarification and (self._plan_task is not None or any(
            op["revision"] == self.revision and op["status"] == "pending" for op in self.operations.values()))

    def _next_deadline(self):
        deadlines = [op["deadline"] for op in self.operations.values()
                     if op["kind"] == "state_modifying" and op["status"] == "pending" and "deadline" in op]
        return max(0, min(deadlines) - time.monotonic()) if deadlines else None

    def _expire_writes(self):
        for op in self.operations.values():
            if (op["kind"] == "state_modifying" and op["status"] == "pending" and
                    time.monotonic() >= op.get("deadline", float("inf"))):
                op["continuation_retired"] = True
                op["status"] = "unknown"
                if op["revision"] == self.revision:
                    self._final("I could not confirm the action's outcome because no result arrived. I will not repeat it without checking what happened.")

    def _start_plan(self):
        if self._plan_task is not None:
            self._plan_task.cancel()
        task = asyncio.create_task(self._plan(self._context(), self.revision))
        self._plan_task = task
        self._tasks.add(task)
        task.add_done_callback(self._finished)

    def _finished(self, task):
        self._tasks.discard(task)
        if not task.cancelled():
            task.exception()  # Consume errors from a superseded background task.

    async def _plan(self, context, revision):
        task = None
        try:
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
        question = decision.get("clarification")
        uncertain_audio = any(
            index >= self._request_start and observation.get("type") == "audio" and observation.get("uncertain") is True
            for index, observation in self.observations.items())
        if uncertain_audio and not (isinstance(question, str) and question.strip()):
            question = "Please confirm the unclear part of that recording before I use it for an action."
        if isinstance(question, str) and question.strip():
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
            for step in calls:
                self._dispatch(step)
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

    def _binding_error(self, step, tool, args, command=None):
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
        primitive_values = [(path, value) for path, value in scalar_fields(args)
                            if type(value) in (bool, int, float) and
                            not any(path == parent or path.startswith(parent + ".") for parent in bindings)]
        if tool["kind"] == "state_modifying" and any(
                not _has_exact_field_value(path, value, command)
                for path, value in primitive_values):
            return _proposed_primitive_values(primitive_values)
        for argument, binding in bindings.items():
            try:
                source = successes[binding["call_id"]]
                result = source["result"]
                actual, bound = at_path(args, argument), at_path(result, binding["path"])
                if type(actual) is not type(bound) or actual != bound:
                    return "A proposed argument does not match the tool result."
                if type(actual) in (int, float):
                    explicit = _explicit_numeric_field_values(argument, command)
                    if explicit and explicit != {Decimal(str(actual))}:
                        return "A proposed argument does not match the explicit user value."
                elif type(actual) is bool:
                    explicit = _explicit_boolean_field_values(argument, command)
                    if explicit and explicit != {actual}:
                        return "A proposed argument does not match the explicit user value."
                elif isinstance(actual, str):
                    explicit = _explicit_string_field_values(argument, command)
                    if explicit and explicit != {" ".join(actual.casefold().split())}:
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
                descriptive = bool(re.search(r"\b(summary|description|message|note|text|comment|query)\b", field + " " + description, re.I))
                # An enum/default validates a value; it does not authorize the write.
                if not descriptive and not contains_value(value, authorized_text):
                    return f"Please supply {path}; I cannot invent that value for a state-changing action."
            if not (required_source or identifier and tool["kind"] == "state_modifying"):
                continue
            explicit = isinstance(value, str) and contains_value(value, supplied)
            if path not in bindings and (required_source or not explicit):
                return f"The value for {path} needs a successful result or an explicit user reference."
        return ""

    def _dispatch(self, step, *, retry=0, depth=0, selection=None):
        if self._closed or self._turn_open or self._awaiting_clarification:
            return
        if not isinstance(step, dict) or not isinstance(step.get("api_name"), str):
            self._say("clarification_request", "I could not identify a valid tool for that action.")
            return
        name, args = step["api_name"], step.get("args", {})
        tool = self.tools.get(name)
        problems = validate_args(tool, args)
        if problems:
            self._say("clarification_request", "I need valid details before acting: " + "; ".join(problems[:3]))
            return
        if depth > 3:
            self._say("clarification_request", "This request needs more steps than I can safely complete at once.")
            return
        grant = None
        if tool["kind"] == "state_modifying":
            grant = authorization_grant(step, tool, self._user_texts(), selection=selection)
            if not grant:
                self._say("clarification_request", "Please explicitly confirm the action and its target before I change anything.")
                return
        binding_error = self._binding_error(step, tool, args, grant)
        if binding_error:
            self._say("clarification_request", binding_error)
            return
        key = call_key(name, args, write=tool["kind"] == "state_modifying")
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
        same = [op for op in self.operations.values() if op["key"] == key and
                (op["request_start"] == self._request_start if grant is not None else op["revision"] == self.revision)]
        if same:
            last = same[-1]
            if not (tool["kind"] == "read_only" and retry == 1 and last["status"] == "error" and last["retry"] == 0):
                if last["status"] == "success":
                    if last["revision"] == self.revision:
                        self._final(self._render(last))
                elif tool["kind"] == "state_modifying" and last["status"] != "pending":
                    self._final("That action was already submitted. Its recorded outcome must be checked before trying again.")
                return last["status"] in {"pending", "success"}
        if grant is not None:
            # Perception/schema revisions change evidence, never user permission.
            if authority_key in self._consumed_grants:
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
        if tool["kind"] == "state_modifying":
            delay = tool.get("delay_range_ms", [0, 3000])
            upper = delay[1] if isinstance(delay, list) and len(delay) == 2 and type(delay[1]) in (int, float) else 3000
            operation["deadline"] = time.monotonic() + min(max(upper / 1000, 0), 30) + 0.5
            if self._tail_deadline is not None:
                operation["deadline"] = min(operation["deadline"], self._tail_deadline - 0.1)
        self.operations[call_id] = operation
        for key, value in args.items():
            if key in self.state["slots"] or key.endswith("_id"):
                self.state["slots"][key] = deepcopy(value)
        self._emit("tool_call", {"call_id": call_id, "api_name": name, "args": args})
        return True

    def _result(self, payload):
        if not isinstance(payload.get("call_id"), str):
            return
        operation = self.operations.get(payload["call_id"])
        if operation is None or payload.get("api_name") != operation["api_name"]:
            return
        if operation["status"] in {"success", "error"}:
            return  # Duplicate/conflicting notifications cannot rewrite terminal evidence.
        status, result = payload.get("status"), payload.get("result")
        if not isinstance(status, str) or status not in {"success", "error"} or not isinstance(result, dict):
            return
        if result.get("status", status) != status:
            return
        error_code = result.get("error")
        if not isinstance(error_code, str):
            error_code = "unknown_error"
        operation["status"], operation["result"] = status, deepcopy(result)
        if status == "error" and operation["kind"] == "state_modifying" and error_code not in {"invalid_args", "not_found", "unknown_tool"}:
            operation["status"] = "unknown"
        if operation["revision"] != self.revision or self._turn_open or self._awaiting_clarification:
            return  # Keep the durable outcome without speaking or resuming suspended work.
        self.tool_results.append({**self._operation_context(operation), "status": status})
        if status == "error":
            if (operation["kind"] == "read_only" and operation["retry"] == 0 and
                    error_code in {"timeout", "unavailable", "temporarily_unavailable", "rate_limited"}):
                self._filler("The lookup failed temporarily. I am retrying it once.", recovery_id=operation["call_id"])
                self._dispatch(operation["step"], retry=1, depth=operation["depth"], selection=operation["selection"])
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
        self._continue_result(operation)

    def _continue_result(self, operation):
        if operation.get("result_announced") or operation.get("continuation_retired"):
            return
        next_step = operation["step"].get("after_result")
        if next_step is not None:
            try:
                continuation, selection = self._continuation(next_step, operation)
            except (KeyError, IndexError, TypeError, ValueError):
                self._final(self._render(operation))
                if not self._repair_used:
                    self._repair_used = True
                    self._planning_error = "The proposed continuation could not select and bind an actual result. Inspect tool_results; never guess an identifier."
                    self._start_plan()
                else:
                    self._say("clarification_request", "The returned options do not identify one safe next action. Please clarify your selection.")
                return
            if not self._dispatch(continuation, depth=operation["depth"] + 1, selection=selection):
                self._final(self._render(operation))
        else:
            question = self._flight_booking_question(operation)
            if question:
                self.state["intent"] = "book_flight"
            self._final(self._render(operation))
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
        if operation["step"].get("result_evidence") is not None and not self._source_matches(operation, template):
            return "The returned source does not confirm the requested target, so I cannot support that explanation with this result."
        result, quoted_paths = self._presentation_result(operation)
        omitted = result != operation["result"]
        cited_answer = self._cited_answer(operation, result, quoted_paths, omitted)
        if cited_answer is not None:
            return cited_answer
        if isinstance(template, str) and template.strip():
            try:
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
                            else text + " " + self._compact_result(result, quoted_paths, omitted))
            except (KeyError, IndexError, TypeError, ValueError):
                pass
        return self._compact_result(result, quoted_paths, omitted)

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
    def _compact_result(result, quoted_paths=(), omitted=False, *, path=""):
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
        body = {key: value for key, value in result.items() if key != "status"}
        if not body:
            if omitted:
                return "The tool completed successfully. Its metadata was omitted from this answer."
            return "The tool completed successfully and returned no additional details."
        return "Returned information: " + render(body, path=path) + "." + (" Some tool metadata was omitted." if omitted else "")

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
