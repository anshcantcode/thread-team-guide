"""Known-gap reproductions, NOT recovery acceptance tests or live evidence.

Runs the installed LiveKit StreamAdapter and AgentActivity with scripted VAD/STT
and the actual ControllerBridge. No model, server, microphone, or synthesis.

Safe recovery needs a segment identity assigned where capture/VAD boundaries
are observed, before serial decode can backlog. The same identity must fence
the bridge onset and a success-empty resolution; sampling input_sequence in
_recognize_impl is insufficient. A matching resolution can retire only that
turn's response waiter and emit fixed clarification, with no planner call,
grant restoration, tool retry, or replay. Newer input must invalidate a queued
clarification before it reaches audio. Failed/cancelled decode is not empty.
The present SDK adapter exposes no such shared boundary identity.
"""
import asyncio
from copy import deepcopy
import threading
from types import SimpleNamespace
import unittest

from livekit import rtc
from livekit.agents import Agent, AgentSession, stt, vad, APIConnectOptions
from livekit.agents.stt.stream_adapter import StreamAdapter

from thread_agent.fdb3 import ControllerBridge
from thread_agent.fdb3_voice import SegmentVAD, ThreadVoiceAgent, ControllerLLM, EMPTY_SPEECH_CLARIFICATION


def vad_event(kind, number):
    frame = rtc.AudioFrame(number.to_bytes(2, "little") * 160, 16000, 1, 160)
    return vad.VADEvent(type=kind, samples_index=number * 160, timestamp=number / 10,
        speech_duration=.1, silence_duration=.1, frames=[frame])


class QueuedVAD(vad.VAD):
    def __init__(self):
        super().__init__(capabilities=vad.VADCapabilities(update_interval=.01))
        self.created = asyncio.Event()
        self.instance = None

    def stream(self):
        self.instance = QueuedVADStream(self)
        self.created.set()
        return self.instance


class QueuedVADStream(vad.VADStream):
    async def _main_task(self):
        async for _ in self._input_ch:
            pass

    def segment(self, number):
        self._event_ch.send_nowait(vad_event(vad.VADEventType.START_OF_SPEECH, number))
        self._event_ch.send_nowait(vad_event(vad.VADEventType.END_OF_SPEECH, number))


class ScriptedSTT(stt.STT):
    def __init__(self, bridge, replies):
        super().__init__(capabilities=stt.STTCapabilities(streaming=False, interim_results=False))
        self.bridge, self.replies, self.started = bridge, replies, []
        self.release_first = asyncio.Event()
        self.outcomes = []

    async def _recognize_impl(self, buffer, *, language, conn_options):
        # Read the marker in this artificial frame only to prove backlog ordering;
        # production PCM has no analogous trusted input-epoch field.
        number = int.from_bytes(bytes(buffer.data)[:2], "little")
        self.started.append({"segment": number, "decoder_start_epoch": self.bridge.input_sequence})
        try:
            if number == 1:
                await self.release_first.wait()
            reply = self.replies[number - 1]
            if isinstance(reply, BaseException):
                raise reply
        except BaseException as exc:
            self.outcomes.append({"segment": number, "outcome": type(exc).__name__})
            raise
        self.outcomes.append({"segment": number, "outcome": "success", "text": reply})
        return stt.SpeechEvent(stt.SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[stt.SpeechData(language="en", text=reply)])


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(.005)


class EmptyASRBoundaryReproductions(unittest.IsolatedAsyncioTestCase):
    async def adapter(self, bridge, replies):
        recognizer, detector = ScriptedSTT(bridge, replies), QueuedVAD()
        adapter = StreamAdapter(stt=recognizer, vad=detector)
        stream = adapter.stream(conn_options=APIConnectOptions(max_retry=0))
        events = []
        async def consume():
            async for event in stream:
                events.append(event)
        consumer = asyncio.create_task(consume())
        await asyncio.wait_for(detector.created.wait(), 2)
        return recognizer, detector.instance, adapter, stream, consumer, events

    async def test_current_empty_success_is_dropped_and_old_response_times_out(self):
        entered, release = threading.Event(), threading.Event()
        class Planner:
            contexts = []
            async def setup(self): pass
            async def close(self): pass
            async def plan(self, context):
                self.contexts.append(deepcopy(context))
                return {"tool_calls": [{"api_name": "find_tile", "args": {},
                    "response_template": "Original tile {tile}."}]}
        def lookup(name, **args):
            entered.set()
            if not release.wait(2): raise TimeoutError("fixture release missing")
            return {"status": "success", "tile": "jade"}
        bridge = ControllerBridge({"find_tile": {"kind": "read_only", "args": {}}}, SimpleNamespace(call=lookup), Planner())
        await bridge.start()
        session = AgentSession(turn_detection="manual", resume_false_interruption=False)
        session.on("user_state_changed", lambda event: bridge.speech_started() if event.new_state == "speaking" else None)
        recognizer, detector, adapter, stream, consumer, events = await self.adapter(bridge, [""])
        response = None
        try:
            await session.start(agent=Agent(instructions="Independent SDK boundary reproduction"))
            response = asyncio.create_task(bridge.response("Find a jade tile.", timeout=.3))
            await until(entered.is_set)
            previous_revision = bridge.controller.revision
            session._activity.on_start_of_speech(vad_event(vad.VADEventType.START_OF_SPEECH, 1))
            await until(lambda: bridge.controller.revision > previous_revision)
            detector.segment(1)
            recognizer.release_first.set()
            await until(lambda: len(recognizer.started) == 1)
            await asyncio.sleep(.02)
            release.set()
            await until(lambda: bridge.controller.operations["call-1"]["status"] == "success")
            with self.assertRaises(TimeoutError):
                await response
            self.assertEqual([event.type for event in events], [stt.SpeechEventType.START_OF_SPEECH, stt.SpeechEventType.END_OF_SPEECH])
            self.assertEqual(len(bridge.controller.planner.contexts), 1)
            self.assertEqual(recognizer.outcomes, [{"segment": 1, "outcome": "success", "text": ""}])
            self.assertEqual(len(bridge.calls), 1)
            self.assertTrue(bridge.controller.operations["call-1"]["execution_admitted"])
            self.assertTrue(bridge.outputs.empty())
            self.assertEqual(bridge.controller.operations["call-1"]["result"]["tile"], "jade")
        finally:
            release.set()
            recognizer.release_first.set()
            if response and not response.done(): response.cancel()
            if response: await asyncio.gather(response, return_exceptions=True)
            await stream.aclose()
            await asyncio.gather(consumer, return_exceptions=True)
            await adapter.aclose()
            await session.aclose()
            await bridge.close()

    async def test_cancelled_decode_also_has_no_final_but_is_not_empty_success(self):
        bridge = ControllerBridge({}, SimpleNamespace(), None)
        recognizer, detector, adapter, stream, consumer, events = await self.adapter(bridge, [""])
        try:
            bridge.speech_started()
            detector.segment(1)
            await until(lambda: len(recognizer.started) == 1)
            await stream.aclose()
            await asyncio.gather(consumer, return_exceptions=True)
            self.assertEqual(recognizer.outcomes, [{"segment": 1, "outcome": "CancelledError"}])
            self.assertFalse(any(event.type == stt.SpeechEventType.FINAL_TRANSCRIPT for event in events))
        finally:
            await stream.aclose()
            await asyncio.gather(consumer, return_exceptions=True)
            await adapter.aclose()

    async def test_current_decoder_start_epoch_mislabels_queued_old_empty_segment(self):
        bridge = ControllerBridge({}, SimpleNamespace(), None)
        recognizer, detector, adapter, stream, consumer, events = await self.adapter(bridge, ["older", "", "newest"])
        try:
            bridge.speech_started()
            detector.segment(1)
            await until(lambda: len(recognizer.started) == 1)
            bridge.speech_started()
            empty_epoch = bridge.input_sequence
            detector.segment(2)
            bridge.speech_started()
            newer_epoch = bridge.input_sequence
            detector.segment(3)
            self.assertEqual(len(recognizer.started), 1)  # Adapter blocked on first decode.
            recognizer.release_first.set()
            await until(lambda: len(events) == 8)  # Three boundaries, two nonempty finals.
            empty_start = recognizer.started[1]
            self.assertEqual(empty_start["segment"], 2)
            self.assertNotEqual(empty_start["decoder_start_epoch"], empty_epoch)
            self.assertEqual(empty_start["decoder_start_epoch"], newer_epoch)
            finals = [event for event in events if event.type == stt.SpeechEventType.FINAL_TRANSCRIPT]
            self.assertEqual([event.alternatives[0].text for event in finals], ["older", "newest"])
            self.assertTrue(all(event.request_id == "" for event in events))
        finally:
            recognizer.release_first.set()
            await stream.aclose()
            await asyncio.gather(consumer, return_exceptions=True)
            await adapter.aclose()


class EmptyASRRecoveryAcceptance(unittest.IsolatedAsyncioTestCase):
    async def start(self, replies, *, registry=None, output=None, planner=None, controller_llm=False):
        class Planner:
            def __init__(self): self.contexts = []
            async def setup(self): pass
            async def close(self): pass
            async def plan(self, context):
                self.contexts.append(deepcopy(context))
                return {"tool_calls": [{"api_name": "find_tile", "args": {},
                    "response_template": "Old tile {tile}."}]} if registry else {"response": "Current answer."}
        bridge = ControllerBridge({"find_tile": {"kind": "read_only", "args": {}}}, registry or SimpleNamespace(), planner or Planner())
        await bridge.start()
        detector, recognizer = QueuedVAD(), ScriptedSTT(bridge, replies)
        boundary = SegmentVAD(detector, bridge)
        session = AgentSession(stt=recognizer, vad=boundary, turn_detection="vad", llm=ControllerLLM(bridge) if controller_llm else None,
            min_endpointing_delay=.01, max_endpointing_delay=.02, resume_false_interruption=False)
        boundary.session = session
        if output is not None:
            session.output.audio = output
        committed = []
        session.on("conversation_item_added", lambda event: committed.append(event.item))
        await session.start(agent=ThreadVoiceAgent(bridge))
        await asyncio.wait_for(detector.created.wait(), 2)
        self.resources.append((session, bridge, recognizer, boundary))
        return bridge, recognizer, detector.instance, boundary, session, committed

    async def asyncSetUp(self): self.resources = []

    async def asyncTearDown(self):
        for session, bridge, recognizer, boundary in reversed(self.resources):
            await asyncio.wait_for(session.aclose(), 3)
            await asyncio.wait_for(bridge.close(), 3)

    async def test_matching_empty_success_retires_waiter_and_preserves_actual_outcome(self):
        entered, release = threading.Event(), threading.Event()
        def lookup(name, **args):
            entered.set()
            if not release.wait(2): raise TimeoutError("fixture not released")
            return {"status": "success", "tile": "jade"}
        bridge, recognizer, detector, boundary, session, committed = await self.start([""], registry=SimpleNamespace(call=lookup))
        response = asyncio.create_task(bridge.response("Find a jade tile.", timeout=2))
        try:
            await until(entered.is_set)
            detector.segment(1)
            recognizer.release_first.set()
            await until(lambda: any(item.text_content == EMPTY_SPEECH_CLARIFICATION for item in committed))
            self.assertEqual(await asyncio.wait_for(response, 1), "")
            release.set()
            await until(lambda: bridge.controller.operations["call-1"]["status"] == "success")
            self.assertEqual(len(bridge.calls), 1)
            self.assertEqual(len(bridge.controller.planner.contexts), 1)
            self.assertEqual(bridge.controller.operations["call-1"]["result"]["tile"], "jade")
            self.assertFalse(any("Old tile" in (item.text_content or "") for item in committed))
            resolutions = [row for row in bridge.voice_events if row["event"] == "empty_speech_resolved"]
            self.assertEqual(len(resolutions), 1)
            self.assertFalse(await bridge.resolve_empty_speech(resolutions[0]["input_sequence"], resolutions[0]["segment_id"]))
        finally:
            release.set()
            if not response.done(): response.cancel()
            await asyncio.gather(response, return_exceptions=True)

    async def test_backlogged_old_empty_does_not_resolve_newer_speech(self):
        bridge, recognizer, detector, boundary, session, committed = await self.start(["", "newer words"])
        detector.segment(1)
        await until(lambda: len(recognizer.started) == 1)
        detector.segment(2)
        await until(lambda: bridge.input_sequence == 2)
        recognizer.release_first.set()
        await until(lambda: len(recognizer.outcomes) == 2)
        await asyncio.sleep(.05)
        rows = [row for row in bridge.voice_events if row["event"] == "speech_segment_recognition"]
        self.assertEqual([row["input_sequence"] for row in rows], [1, 2])
        self.assertFalse(any(row["event"] == "empty_speech_resolved" for row in bridge.voice_events))
        self.assertFalse(any(item.text_content == EMPTY_SPEECH_CLARIFICATION for item in committed))

    async def test_latest_of_two_empty_decodes_resolves_exactly_once(self):
        bridge, recognizer, detector, boundary, session, committed = await self.start(["", ""])
        detector.segment(1)
        await until(lambda: len(recognizer.started) == 1)
        detector.segment(2)
        await until(lambda: bridge.input_sequence == 2)
        recognizer.release_first.set()
        await until(lambda: any(item.text_content == EMPTY_SPEECH_CLARIFICATION for item in committed))
        resolutions = [row for row in bridge.voice_events if row["event"] == "empty_speech_resolved"]
        self.assertEqual([row["input_sequence"] for row in resolutions], [2])
        self.assertEqual(sum(item.text_content == EMPTY_SPEECH_CLARIFICATION for item in committed), 1)
        self.assertEqual(bridge.controller.planner.contexts, [])

    async def test_newer_submitted_text_fences_empty_decode(self):
        bridge, recognizer, detector, boundary, session, committed = await self.start([""])
        detector.segment(1)
        await until(lambda: len(recognizer.started) == 1)
        await bridge.submit("Newer independently typed instruction.")
        recognizer.release_first.set()
        await until(lambda: len(recognizer.outcomes) == 1)
        await asyncio.sleep(.05)
        self.assertFalse(any(row["event"] == "empty_speech_resolved" for row in bridge.voice_events))
        self.assertFalse(any(item.text_content == EMPTY_SPEECH_CLARIFICATION for item in committed))

    async def test_cancelled_decode_never_resolves_and_shutdown_drains_queue(self):
        bridge, recognizer, detector, boundary, session, committed = await self.start([""])
        detector.segment(1)
        await until(lambda: len(recognizer.started) == 1)
        await asyncio.wait_for(session.aclose(), 3)
        rows = [row for row in bridge.voice_events if row["event"] == "speech_segment_recognition"]
        self.assertEqual(rows[0]["outcome"], "cancelled")
        self.assertFalse(any(row["event"] == "empty_speech_resolved" for row in bridge.voice_events))
        self.assertFalse(committed)
        self.assertIsNone(boundary.stream_generation)
        self.assertFalse(boundary.decoder_active)
        self.assertTrue(boundary.segments.empty())

    async def test_failed_decode_never_becomes_empty_success(self):
        bridge, recognizer, detector, boundary, session, committed = await self.start([RuntimeError("authored ASR failure")])
        detector.segment(1)
        recognizer.release_first.set()
        await until(lambda: any(row.get("outcome") == "error" for row in bridge.voice_events))
        self.assertFalse(any(row["event"] == "empty_speech_resolved" for row in bridge.voice_events))
        self.assertFalse(any(item.text_content == EMPTY_SPEECH_CLARIFICATION for item in committed))

    async def test_new_onset_during_old_speech_cleanup_blocks_clarification_admission(self):
        bridge, recognizer, detector, boundary, session, committed = await self.start([""])
        entered, release = asyncio.Event(), asyncio.Event()
        real_interrupt = session.interrupt
        async def delayed_interrupt(future):
            await future
            entered.set()
            await release.wait()
        pending = []
        def interrupt(**kwargs):
            task = asyncio.create_task(delayed_interrupt(real_interrupt(**kwargs)))
            pending.append(task)
            return task
        session.interrupt = interrupt
        try:
            detector.segment(1)
            recognizer.release_first.set()
            await asyncio.wait_for(entered.wait(), 2)
            detector._event_ch.send_nowait(vad_event(vad.VADEventType.START_OF_SPEECH, 2))
            await until(lambda: bridge.input_sequence == 2)
            release.set()
            await asyncio.gather(*pending)
            await asyncio.sleep(.03)
            self.assertFalse(any(item.text_content == EMPTY_SPEECH_CLARIFICATION for item in committed))
            self.assertIsNone(boundary.clarification)
        finally:
            release.set()
            session.interrupt = real_interrupt
            await asyncio.gather(*pending, return_exceptions=True)

    async def test_next_onset_interrupts_owned_clarification_handle(self):
        from tests_fdb3.test_playback_provenance import PartialAudioOutput
        output = PartialAudioOutput()
        bridge, recognizer, detector, boundary, session, committed = await self.start([""], output=output)
        real_say = session.say
        async def audio():
            yield rtc.AudioFrame(b"\x10\x10" * 480, 24000, 1, 480)
            await asyncio.Event().wait()
        session.say = lambda text, **kwargs: real_say(text, audio=audio(), **kwargs)
        detector.segment(1)
        recognizer.release_first.set()
        await asyncio.wait_for(output.started.wait(), 2)
        clarification = boundary.clarification
        detector._event_ch.send_nowait(vad_event(vad.VADEventType.START_OF_SPEECH, 2))
        await until(lambda: clarification.interrupted)
        self.assertIsNone(boundary.clarification)
        self.assertEqual(bridge.input_sequence, 2)
        self.assertEqual(bridge.controller.planner.contexts, [])

    async def test_empty_success_cannot_restore_earlier_write_authority(self):
        bridge, recognizer, detector, boundary, session, committed = await self.start([""])
        bridge.controller.tools["set_mode"] = {"kind": "state_modifying", "description": "Set a mode.",
            "args": {"mode": {"type": "string", "required": True}}}
        await bridge.submit("Set mode quiet.")
        await bridge.synchronize()
        detector.segment(1)
        recognizer.release_first.set()
        await until(lambda: any(item.text_content == EMPTY_SPEECH_CLARIFICATION for item in committed))
        bridge.controller._dispatch({"api_name": "set_mode", "args": {"mode": "quiet"},
            "authorization": {"quote": "Set mode quiet"}})
        self.assertFalse(any(op["kind"] == "state_modifying" for op in bridge.controller.operations.values()))
        self.assertNotIn("quiet", str(bridge.controller._user_texts()))

    async def test_distinct_sessions_have_distinct_segment_generations(self):
        first = await self.start([""])
        second = await self.start([""])
        self.assertNotEqual(first[3].stream_generation, second[3].stream_generation)
        for bridge, recognizer, detector, boundary, session, committed in (first, second):
            detector.segment(1)
            recognizer.release_first.set()
            await until(lambda: any(item.text_content == EMPTY_SPEECH_CLARIFICATION for item in committed))
        first_row = next(row for row in first[0].voice_events if row["event"] == "empty_speech_resolved")
        self.assertFalse(await second[0].resolve_empty_speech(first_row["input_sequence"], first_row["segment_id"]))

    async def test_nonempty_shared_vad_path_retains_read_without_duplicate_invocation(self):
        entered, release = threading.Event(), threading.Event()
        def lookup(name, **args):
            entered.set()
            if not release.wait(3): raise TimeoutError("fixture not released")
            return {"status": "success", "tile": "jade"}
        class RetainingPlanner:
            def __init__(self): self.contexts = []
            async def setup(self): pass
            async def close(self): pass
            async def plan(self, context):
                self.contexts.append(deepcopy(context))
                step = {"api_name": "find_tile", "args": {}, "response_template": "Old tile {tile}."}
                if len(self.contexts) == 2:
                    source = next(action for action in context["actions"] if action.get("can_retain_read"))
                    step.update(retain_call_id=source["call_id"], response_template="Brief current tile {tile}.")
                return {"tool_calls": [step]}
        bridge, recognizer, detector, boundary, session, committed = await self.start(
            ["Find a jade tile.", "Keep that search and answer briefly."], registry=SimpleNamespace(call=lookup),
            planner=RetainingPlanner(), controller_llm=True)
        try:
            detector.segment(1)
            recognizer.release_first.set()
            await until(entered.is_set)
            detector.segment(2)
            await until(lambda: any(op.get("retained_from_call_id") for op in bridge.controller.operations.values()))
            release.set()
            await until(lambda: any(item.role == "assistant" and "Brief current tile jade" in (item.text_content or "") for item in committed))
            self.assertEqual(len(bridge.calls), 1)
            self.assertTrue(all(op["status"] == "success" for op in bridge.controller.operations.values()))
            self.assertFalse(any("Old tile" in (item.text_content or "") for item in committed))
            self.assertEqual(len(bridge.controller.planner.contexts), 2)
        finally:
            release.set()

    async def write_fixture(self, second_text):
        calls = []
        class Planner:
            def __init__(self): self.contexts = []
            async def setup(self): pass
            async def close(self): pass
            async def plan(self, context):
                self.contexts.append(deepcopy(context))
                return {"tool_calls": [{"api_name": "set_mode", "args": {"mode": "quiet"},
                    "authorization": {"quote": "Set mode quiet"}, "response_template": "Mode receipt {receipt}."}]}
        def invoke(name, **args):
            calls.append((name, args))
            return {"status": "success", "receipt": "Q-12"}
        values = await self.start(["Set mode quiet.", second_text], registry=SimpleNamespace(call=invoke),
                                  planner=Planner(), controller_llm=True)
        bridge, recognizer = values[:2]
        bridge.controller.tools["set_mode"] = {"kind": "state_modifying", "description": "Set a mode.",
            "args": {"mode": {"type": "string", "required": True}}}
        entered_second, release_second = asyncio.Event(), asyncio.Event()
        recognize = recognizer._recognize_impl
        async def block_second(buffer, **kwargs):
            if int.from_bytes(bytes(buffer.data)[:2], "little") == 2:
                entered_second.set()
                await release_second.wait()
            return await recognize(buffer, **kwargs)
        recognizer._recognize_impl = block_second
        return values, calls, entered_second, release_second

    async def test_stale_nonempty_decode_cannot_execute_before_newer_cancellation_decode(self):
        values, calls, entered_second, release_second = await self.write_fixture("Do not set mode quiet.")
        bridge, recognizer, detector, boundary, session, committed = values
        try:
            detector.segment(1)
            await until(lambda: len(recognizer.started) == 1)
            detector.segment(2)
            await until(lambda: bridge.input_sequence == 2)
            recognizer.release_first.set()
            await asyncio.wait_for(entered_second.wait(), 2)
            await asyncio.sleep(.05)
            self.assertEqual(calls, [])
            self.assertEqual(bridge.controller.planner.contexts, [])
            # Sprint 2: the superseded same-turn decode is kept as context with its own
            # segment provenance; it never plans or authorizes by itself.
            old = next(row for row in bridge.voice_events if row.get("delivery") == "stale_context")
            self.assertEqual(old['text'], "Set mode quiet.")
            self.assertEqual(old['input_sequence'], 1)
            await bridge.synchronize()
            retained = [row for row in bridge.controller.messages if row["payload"].get("context_only")]
            self.assertEqual([row["payload"]["text"] for row in retained], ["Set mode quiet."])
            release_second.set()
            await until(lambda: len(bridge.controller.planner.contexts) == 1)
            await bridge.synchronize()
            self.assertEqual(calls, [])  # The newer cancellation still wins.
        finally:
            release_second.set()

    async def admission_race(self, second_text):
        values, calls, entered_second, release_second = await self.write_fixture(second_text)
        bridge, recognizer, detector, boundary, session, committed = values
        entered_response, release_response = asyncio.Event(), asyncio.Event()
        response = bridge.response
        captured_ids = []
        async def delayed_response(text, **kwargs):
            captured_ids.append(kwargs.get('speech_message_id'))
            if len(captured_ids) == 1:
                entered_response.set()
                await release_response.wait()
            return await response(text, **kwargs)
        bridge.response = delayed_response
        try:
            detector.segment(1)
            recognizer.release_first.set()
            await asyncio.wait_for(entered_response.wait(), 2)
            self.assertTrue(captured_ids[0])
            detector.segment(2)
            await asyncio.wait_for(entered_second.wait(), 2)
            release_response.set()
            await until(lambda: any(row['event'] == 'speech_admission_rejected' for row in bridge.voice_events))
            self.assertEqual(calls, [])
            self.assertEqual(bridge.controller.planner.contexts, [])
            release_second.set()
            await until(lambda: len(bridge.controller.planner.contexts) == 1)
            await bridge.synchronize()
            if second_text == "Set mode quiet.":
                await until(lambda: len(calls) == 1)
            else:
                await asyncio.sleep(.03)
            self.assertEqual(len(set(captured_ids)), 2)
            return calls, bridge
        finally:
            release_response.set()
            release_second.set()

    async def test_new_onset_after_sdk_yield_is_rechecked_at_controller_submission(self):
        calls, bridge = await self.admission_race("Do not set mode quiet.")
        self.assertEqual(calls, [])
        self.assertFalse(any(op['kind'] == 'state_modifying' for op in bridge.controller.operations.values()))

    async def test_repeated_identical_text_keeps_distinct_provenance_and_current_write(self):
        calls, bridge = await self.admission_race("Set mode quiet.")
        self.assertEqual(calls, [("set_mode", {"mode": "quiet"})])
        self.assertEqual(len(bridge.calls), 1)

    async def test_rejected_speech_cannot_drain_new_output_or_change_playback(self):
        bridge, recognizer, detector, boundary, session, committed = await self.start([""])
        old = bridge.speech_started('old-segment')
        self.assertTrue(bridge.bind_speech_message('old-message', 'Old text', [(old, 'old-segment')]))
        bridge.speech_started('new-segment')
        sentinel = {'payload': {'text': 'Keep current output'}}
        bridge.outputs.put_nowait(sentinel)
        bridge.controller.planner.assistant_playback = ['current playback']
        self.assertEqual(await bridge.response('Old text', speech_message_id='old-message'), '')
        self.assertEqual(bridge.outputs.get_nowait(), sentinel)
        self.assertEqual(bridge.controller.planner.assistant_playback, ['current playback'])

    async def test_message_identity_is_single_use_and_submission_keeps_vad_identity(self):
        bridge, recognizer, detector, boundary, session, committed = await self.start([""])
        epoch = bridge.speech_started('current-segment')
        self.assertTrue(bridge.bind_speech_message('current-message', 'Current text', [(epoch, 'current-segment')]))
        self.assertTrue(await bridge.submit('Current text', speech_message_id='current-message'))
        admitted_epoch = bridge.input_sequence
        self.assertTrue(bridge.current_speech_source(epoch, 'current-segment'))
        self.assertFalse(await bridge.submit('Current text', speech_message_id='current-message'))
        self.assertEqual(bridge.input_sequence, admitted_epoch)


if __name__ == "__main__": unittest.main()
