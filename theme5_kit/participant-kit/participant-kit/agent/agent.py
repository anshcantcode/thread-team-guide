"""ParticipantAgent -- translates the official Theme 5 harness protocol
(docs/PROTOCOL.md) into calls on THREAD's existing Session controller
(thread_agent/engine.py).

IMPORTANT: This file is a THIN TRANSLATION LAYER only. All the real
interruption/cancellation/decision logic already exists and is tested in
thread_agent/engine.py's Session class -- do NOT duplicate or rewrite that
logic here. If something isn't behaving right, the fix almost certainly
belongs in the translation below, not in engine.py.

Status: first draft, based on a static read of engine.py and PROTOCOL.md.
Marked TODOs are places that need a teammate's input or actual test runs
against pub_01.json / pub_02.json to get right. Nothing here has been run
yet -- treat every line as "probably right, please verify."
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

# TODO: confirm these import paths match the actual repo layout once this
# file lives inside participant-kit/agent/ -- you may need to add the repo
# root to sys.path, or copy/vendor engine.py + protocol.py alongside this
# file, since the harness imports ParticipantAgent from an isolated folder.
from thread_agent.engine import Session
from thread_agent.protocol import InputEvent


def _new_id(prefix: str = "evt") -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


class ParticipantAgent:
    """Official contract: constructed as ParticipantAgent(in_queue, out_queue).
    The harness calls `await agent.run()` as a task on its own event loop.
    Keep __init__ trivial (PROTOCOL.md section 5.3) -- real setup happens in
    setup(), which the harness awaits before the scenario clock starts.
    """

    def __init__(self, in_queue: asyncio.Queue, out_queue: asyncio.Queue):
        self.in_queue = in_queue
        self.out_queue = out_queue
        self.session: Session | None = None
        self._outbox_task: asyncio.Task | None = None

    async def setup(self):
        # TODO: figure out what `planner` argument Session expects (it's
        # passed in as the first positional arg -- probably something built
        # around thread_agent/planner.py). This is the biggest unknown right
        # now and likely needs a teammate who's touched planner.py directly.
        planner = None  # <-- placeholder, will crash until this is filled in
        self.session = Session(planner, evaluation=True, external=True)
        # Session's own worker task is already started inside Session.__init__
        # (see self.worker = asyncio.create_task(self._work())). We just need
        # to drain its outbox into the official out_queue continuously.
        self._outbox_task = asyncio.create_task(self._drain_outbox())

    async def run(self):
        try:
            while True:
                event = await self.in_queue.get()
                # TODO: confirm whether the harness ever sends a literal None
                # or relies purely on `scenario_end` + eventual cancellation.
                # PROTOCOL.md doesn't mention a None sentinel like adapter.py
                # used -- leaving this check in as a safety net only.
                if event is None:
                    break
                await self._handle_event(event)
        finally:
            if self._outbox_task:
                self._outbox_task.cancel()
            if self.session:
                await self.session.close()

    # ------------------------------------------------------------------
    # Incoming: official event dicts -> Session.accept(InputEvent)
    # ------------------------------------------------------------------

    async def _handle_event(self, event: dict):
        event_type = event.get("event_type")
        payload = event.get("payload", {})

        if event_type == "tool_manifest":
            # TODO: translate payload["tools"] (official schema, see TOOLS.md)
            # into whatever Manifest shape thread_agent/protocol.py expects,
            # then feed it into self.session similarly to how adapter.py did
            # it in its __init__ (checked[manifest.id] = manifest, etc.).
            return

        if event_type == "user_speech_chunk":
            await self.session.accept(InputEvent(
                id=_new_id("in"),
                type="transcript",
                text=payload.get("text", ""),
                utterance_id=payload.get("utterance_id", "turn-1"),
                end_of_turn=payload.get("end_of_turn"),
            ))
            return

        if event_type == "user_audio_chunk":
            # TODO: this is the hard one. PROTOCOL.md 1.2 says we get a raw
            # audio_ref (file path), not a transcript -- we need to either
            # call a hosted multimodal API (e.g. Gemini) or a local model
            # (Whisper) to transcribe it ourselves, then feed the result in
            # as a "transcript" InputEvent like above. Acknowledge (filler)
            # BEFORE transcribing, since transcription takes real time.
            return

        if event_type == "video_frame":
            # TODO: translate into an InputEvent the way engine.py's
            # accept() expects for event.type == 'frame' (it reads
            # event.data['mime'] and event.data['base64'] -- but the
            # official kit gives us a file path (image_ref), not base64,
            # so this needs a small file-read + encode step first.
            return

        if event_type == "interruption":
            await self.session.accept(InputEvent(
                id=_new_id("in"),
                type="interrupt",
                text=payload.get("text", ""),
            ))
            return

        if event_type == "tool_result":
            await self.session.accept(InputEvent(
                id=_new_id("in"),
                type="tool_result",
                data={
                    "call_id": payload.get("call_id"),
                    "result": payload.get("result"),
                    "notification_id": _new_id("notice"),
                },
            ))
            return

        if event_type == "scenario_end":
            # No more scripted user events will arrive, but tool_results
            # might still come in during the tail window. Nothing to do here
            # except let the existing loop keep running until run() exits.
            return

        # Unknown event type -- log nothing to the official trace (that's
        # the harness's job), just ignore it defensively.
        return

    # ------------------------------------------------------------------
    # Outgoing: Session.outbox items -> official action dicts
    # ------------------------------------------------------------------

    async def _drain_outbox(self):
        while True:
            item = await self.session.outbox.get()
            action = self._translate(item)
            if action is not None:
                await self.out_queue.put(action)

    def _translate(self, item: dict) -> dict | None:
        kind = item.get("type")

        if kind == "speak":
            return {"action": "filler_speech", "payload": {"text": item.get("text", "")}}

        if kind == "clarify":
            return {"action": "clarification_request", "payload": {"text": item.get("text", "")}}

        if kind == "final":
            # engine.py's say() attaches state_snapshot=self.summary() only
            # when final=True -- exactly matches PROTOCOL.md's requirement
            # that final_response always carries one.
            snapshot = item.get("state_snapshot", {})
            return {
                "action": "final_response",
                "payload": {"text": item.get("text", "")},
                "state_snapshot": {
                    # NOTE: engine.py's summary() uses key "goal"; official
                    # kit wants "intent". This rename is the one confirmed,
                    # concrete fix -- everything else in this file is a
                    # best guess pending a real test run.
                    "intent": snapshot.get("goal"),
                    "slots": snapshot.get("slots", {}),
                },
            }

        if kind == "tool_call":
            return {
                "action": "tool_call",
                "payload": {
                    "call_id": item.get("call_id"),
                    "api_name": item.get("tool"),
                    "args": item.get("arguments", {}),
                },
            }

        if kind == "cancel":
            return {"action": "cancel_tool", "payload": {"call_id": item.get("call_id")}}

        # Everything else (session_started, slot_changed, results_published,
        # goal_changed, etc.) is internal telemetry from engine.py's emit()
        # calls -- useful for our own debugging, but not part of the
        # official action vocabulary, so we don't forward it to out_queue.
        return None
