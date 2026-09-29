"""Tethered emulator diagnostic: the FDB controller drives real Android storage.

Desktop-only. No hosted calls, Android Python backend, or benchmark data access.
Timer success means only an OS intent handoff; there is no timer readback/cancel.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import json
import re
import subprocess
import threading
import time
import uuid

from thread_agent.fdb3 import LocalPlanner


TOOLS = {
    "read_checklist": {"kind": "read_only", "description": "Read the actual persisted kitchen checklist, with item_id, text and checked fields.", "args": {}},
    "add_checklist_item": {"kind": "state_modifying", "description": "Add one preparation step to the kitchen checklist. Returns item_id and detail.", "args": {"text": {"type": "string", "required": True, "description": "The preparation step itself, excluding the instruction to add it and the checklist destination."}}},
    "set_checklist_item": {"kind": "state_modifying", "description": "Set checked state of an existing item; read the checklist to obtain its actual item_id first.", "args": {"item_id": {"type": "string", "required": True}, "checked": {"type": "boolean", "required": True}}},
    "request_timer_handoff": {"kind": "state_modifying", "description": "Set up a native Clock timer handoff, seconds 1..86400 and label. This does NOT confirm timer creation. At most one handoff per session. Cannot cancel, replace or update a submitted timer; inspect_timer_handoff explains the actual receipt.", "args": {"seconds": {"type": "integer", "required": True}, "label": {"type": "string", "required": True}}},
    "inspect_timer_handoff": {"kind": "read_only", "description": "Read only the stored handoff receipt, not Clock state. After dispatch, corrections require reviewing Clock manually; no timer cancellation or update is supported.", "args": {}},
}
# Input registration uses three adb commands, then the tool uses two; each
# subprocess has a 25-second timeout. The controller still caps its wait at
# 30 seconds (+ its existing grace), after which an absent receipt is unknown.
for _tool in TOOLS.values():
    _tool["delay_range_ms"] = [0, 125000]


def validate_arguments(name, args):
    if name not in TOOLS or set(args) != set(TOOLS[name]["args"]):
        raise ValueError("Unknown tool or unexpected arguments")
    for key, value in args.items():
        if key in {"text", "label"}:
            maximum = 300 if key == "text" else 120
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum or "\0" in value:
                raise ValueError("Invalid text")
        elif key == "item_id" and (not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value)):
            raise ValueError("Invalid item reference")
        elif key == "checked" and type(value) is not bool:
            raise ValueError("Invalid checked state")
        elif key == "seconds" and (type(value) is not int or not 1 <= value <= 86400):
            raise ValueError("Invalid timer duration")


def encode_request(request):
    """Only a shell-safe alphabet crosses adb's remote shell boundary."""
    raw = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > 8192:
        raise ValueError("Extension command exceeds 8192 bytes")
    return base64.urlsafe_b64encode(raw).decode("ascii")


class EmulatorRegistry:
    package = "com.thread.app"

    def __init__(self, serial, *, adb="adb", run=subprocess.run, session_id=None):
        if not re.fullmatch(r"emulator-[0-9]{4,5}", serial):
            raise ValueError("An explicitly owned emulator-NNNN serial is required; physical devices are unsupported")
        self.serial, self.adb, self.run = serial, str(adb), run
        self.session_id = session_id or uuid.uuid4().hex
        if not re.fullmatch(r"[a-f0-9]{32}", self.session_id):
            raise ValueError("Invalid session reference")
        self.lock = threading.Lock()
        self.records = []
        self.transport_records = []
        self.input_sequence = 0

    def input_started(self, input_sequence):
        self.input_sequence = input_sequence  # Local only; never block the audio event loop.

    def _adb(self, *args):
        def text(value):
            return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value
        record = {'arguments': list(args), 'started_at': time.time(), 'outcome': 'unknown'}
        self.transport_records.append(record)
        try:
            result = self.run([self.adb, "-s", self.serial, *args], check=True,
                              capture_output=True, text=True, timeout=25, shell=False)
            record.update(outcome='completed', returncode=result.returncode,
                          stdout=result.stdout, stderr=result.stderr)
            return result.stdout
        except (OSError, subprocess.SubprocessError) as exc:
            record.update(outcome='error', error_type=type(exc).__name__,
                          returncode=getattr(exc, 'returncode', None),
                          stdout=text(getattr(exc, 'stdout', None)), stderr=text(getattr(exc, 'stderr', None)))
            raise
        finally:
            record['finished_at'] = time.time()

    def exchange(self, command, args=None, *, request_id=None, input_token="initial"):
        request_id = request_id or uuid.uuid4().hex
        if not re.fullmatch(r"[a-f0-9]{32}", request_id) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", input_token):
            raise ValueError("Invalid request/input reference")
        request = {"session_id": self.session_id, "request_id": request_id,
                   "input_token": input_token, "command": command, "args": args or {}}
        payload = encode_request(request)
        # Readiness belongs to input registration, before call_with_context's
        # final freshness guard. Waiting again after that guard could admit an
        # obsolete effect when speech changes while the emulator reconnects.
        if command == 'set_input':
            self._adb("wait-for-device")
        self._adb("shell", "am", "start", "-W", "-n", self.package + "/.Fdb3ExtensionActivity", "--es", "payload", payload)
        raw = self._adb("shell", "run-as", self.package, "cat", "files/fdb3-" + request_id + ".json")
        result = json.loads(raw)
        if (not isinstance(result, dict) or result.get("request_id") != request_id
                or result.get("session_id") != self.session_id
                or result.get("status") not in {"success", "error"}
                or not isinstance(result.get("detail"), str)):
            raise ValueError("Malformed or mismatched native receipt")
        if command == "request_timer_handoff" and result["status"] == "success":
            if result.get("device_status") != "handed_off" or result.get("timer_creation_confirmed") is not False:
                raise ValueError("Timer handoff receipt cannot confirm timer creation")
        return result

    def call(self, name, **args):
        # Plain registry compatibility for focused diagnostics; live bridge uses context.
        return self.call_with_context(name, args, call_id=uuid.uuid4().hex, revision=0, input_sequence=self.input_sequence)

    def call_with_context(self, name, args, *, call_id, revision, input_sequence):
        try:
            validate_arguments(name, args)
        except ValueError:
            return {"status": "error", "error": "invalid_args", "detail": "Invalid extension arguments; no device command was submitted."}
        request_id = uuid.uuid5(uuid.UUID(hex=self.session_id), str(call_id)).hex
        token = "input-" + str(input_sequence)
        with self.lock:
            record = {"tool": name, "args": deepcopy(args), "request_id": request_id, "input_token": token}
            self.records.append(record)
            try:
                if input_sequence != self.input_sequence:
                    record["result"] = {"status": "error", "error": "invalid_args", "detail": "The request was superseded before device submission."}
                    return deepcopy(record["result"])
                # Native admission persists this token before the matching effect.
                admission = self.exchange("set_input", input_token=token)
                if admission["status"] != "success":
                    raise ValueError("Native input registration failed")
                if input_sequence != self.input_sequence:
                    result = {"status": "error", "error": "invalid_args", "detail": "The request was superseded before device submission."}
                else:
                    result = self.exchange(name, args, request_id=request_id, input_token=token)
            except (OSError, subprocess.SubprocessError, ValueError) as exc:
                result = {"status": "error", "error": "outcome_unknown", "detail": "The device receipt was lost. No retry was submitted; inspect the device before further timer action.", "error_type": type(exc).__name__}
            record["result"] = deepcopy(result)
            return result


class ExtensionPlanner(LocalPlanner):
    async def plan(self, context):
        decision = await super().plan(context)
        # Device effects are described only by native receipts, never model assertions.
        def receipts(steps):
            for step in steps:
                if isinstance(step, dict):
                    if step.get("api_name") in TOOLS:
                        step["response_template"] = "{detail}"
                    if isinstance(step.get("after_result"), dict):
                        receipts([step["after_result"]])
        receipts(decision.get("tool_calls", []))
        has_timer = "request_timer_handoff" in context.get("tools", TOOLS)
        if decision.get("response"):
            decision["response"] = "I have no new device receipt to confirm an action."
            if has_timer:
                decision["response"] += " Timer changes after handoff must be checked in Clock."
        if decision.get("clarification"):
            target = "checklist step or timer duration and label" if has_timer else "checklist step"
            decision["clarification"] = f"Please specify the {target}. I have no new device receipt confirming an action."
        return decision
