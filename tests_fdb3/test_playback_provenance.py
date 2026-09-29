"""Actual pinned SDK interruption; no server, model, microphone, STT, or TTS."""
import asyncio
from copy import deepcopy
import time
from types import SimpleNamespace
import unittest

from livekit import rtc
from livekit.agents import Agent, AgentSession
from livekit.agents.voice import io

from thread_agent.fdb3 import ControllerBridge


FULL_TEXT = "I found a locker and reserved it for you."


class PartialAudioOutput(io.AudioOutput):
    def __init__(self):
        super().__init__(label="independent partial playback fixture", sample_rate=24000,
                         capabilities=io.AudioOutputCapabilities(pause=False))
        self.started = asyncio.Event()

    async def capture_frame(self, frame):
        await super().capture_frame(frame)
        self.on_playback_started(created_at=time.time())
        self.started.set()

    def flush(self):
        super().flush()

    def clear_buffer(self):
        super().flush()
        self.on_playback_finished(playback_position=.02, interrupted=True)


async def interrupted_sdk_item():
    """Use the SDK's real say/interrupt/commit path with an unsynchronized sink."""
    async def audio():
        yield rtc.AudioFrame(b"\x10\x10" * 480, 24000, 1, 480)
        await asyncio.Event().wait()

    output = PartialAudioOutput()
    session = AgentSession(turn_detection="manual", resume_false_interruption=False)
    session.output.audio = output
    items = []
    session.on("conversation_item_added", lambda event: items.append(event.item))
    try:
        await session.start(agent=Agent(instructions="Independent provider-free fixture"))
        speech = session.say(FULL_TEXT, audio=audio())
        await asyncio.wait_for(output.started.wait(), 2)
        await asyncio.sleep(.05)  # Text forwarding finishes while audio is suspended.
        await asyncio.wait_for(speech.interrupt(), 2)
        return next(item for item in items if item.role == "assistant")
    finally:
        await session.aclose()


class PlaybackProvenanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_sdk_unsaid_suffix_is_not_represented_as_played_to_planner(self):
        item = await interrupted_sdk_item()
        # The pinned SDK falls back to full forwarded text without synchronization.
        self.assertEqual(item.text_content, FULL_TEXT)
        self.assertTrue(item.interrupted)

        class Planner:
            contexts = []
            async def setup(self): pass
            async def close(self): pass
            async def plan(self, context):
                self.contexts.append(deepcopy(self.assistant_playback))
                return {"response": "I cannot verify which words were played."}

        planner = Planner()
        bridge = ControllerBridge({}, SimpleNamespace(), planner)
        await bridge.start()
        try:
            bridge.record_assistant_playback(item)
            await bridge.response("What did you say?", chat_items=[item], timeout=2)
            self.assertNotIn(FULL_TEXT, str(planner.contexts[-1]))
            self.assertNotIn("reserved it", str(planner.contexts[-1]))
            # Raw SDK data remains retained for diagnosis, not discarded.
            self.assertIn(FULL_TEXT, str(bridge.voice_events))
        finally:
            await bridge.close()


if __name__ == "__main__":
    unittest.main()
