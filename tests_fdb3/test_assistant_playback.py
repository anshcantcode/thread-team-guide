"""Pinned LiveKit adapter tests: no server, VAD/model load, microphone or TTS."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from livekit.agents import llm, vad
from thread_agent.fdb3_voice import ControllerStream, create_session


class PlaybackAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_passes_sdk_context_without_manufacturing_playback_commit(self):
        calls, emitted = [], []
        chat = llm.ChatContext()
        chat.add_message(role="assistant", id="spoken-prefix", content="The available locker", interrupted=True)
        chat.add_message(role="user", id="current-user-turn", content="Please continue")
        class Bridge:
            speech_provenance_required = False
            async def response(self, text, *, chat_items, speech_message_id=None):
                calls.append((text, chat_items, speech_message_id))
                return "A new proposed reply"
        stream = object.__new__(ControllerStream)
        stream._chat_ctx = chat
        stream._llm = SimpleNamespace(bridge=Bridge())
        stream._event_ch = SimpleNamespace(send_nowait=emitted.append)
        await stream._run()
        self.assertEqual(calls[0][0], "Please continue")
        self.assertIs(calls[0][1], chat.items)
        self.assertEqual(calls[0][1][0].text_content, "The available locker")
        self.assertTrue(calls[0][1][0].interrupted)
        self.assertEqual(emitted[0].delta.content, "A new proposed reply")
        self.assertIsNone(calls[0][2])

        # Enabling speech provenance forwards the actual current SDK user ID,
        # while retaining the same committed playback context and new reply.
        stream._llm.bridge.speech_provenance_required = True
        await stream._run()
        self.assertEqual(calls[1][2], "current-user-turn")
        self.assertIs(calls[1][1], chat.items)
        self.assertTrue(calls[1][1][0].interrupted)
        self.assertEqual(emitted[1].delta.content, "A new proposed reply")

    async def test_session_records_only_conversation_commit_event_for_playback(self):
        callbacks, committed = {}, []
        class Session:
            def __init__(self, **kwargs): pass
            def on(self, event):
                def register(callback):
                    callbacks[event] = callback
                    return callback
                return register
        bridge = SimpleNamespace(voice_events=[], record_assistant_playback=committed.append)
        detector = SimpleNamespace(capabilities=vad.VADCapabilities(update_interval=.032),
                                   on=lambda event, callback: None)
        with patch("thread_agent.fdb3_voice.AgentSession", Session), patch("thread_agent.fdb3_voice.silero.VAD.load", return_value=detector):
            create_session(bridge, object())
        prefix = llm.ChatMessage(role="assistant", id="partial", content=["Only this prefix"], interrupted=True)
        callbacks["conversation_item_added"](SimpleNamespace(item=prefix))
        self.assertEqual(committed, [prefix])
        self.assertEqual(bridge.voice_events, [])


if __name__ == "__main__": unittest.main()
