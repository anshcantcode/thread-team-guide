"""Portable command TTS: real PCM delivery, format conversion, failure and cancellation."""
import asyncio
import json
import math
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest

from thread_agent.fdb3_voice import CommandTTS, speech_backend

SYNTH = r'''
import math, struct, sys, time, wave, os
text_file, output, mode, pid_file = sys.argv[1:5]
open(pid_file, "w").write(str(os.getpid()))
if mode == "slow":
    time.sleep(30)
if mode == "fail":
    sys.stderr.write("engine broke"); sys.exit(3)
words = open(text_file, encoding="utf-8").read().split()
rate, seconds = 22050, 0.25 * len(words)
with wave.open(output, "wb") as audio:
    audio.setnchannels(2); audio.setsampwidth(2); audio.setframerate(rate)
    frames = b"".join(struct.pack("<hh", int(8000 * math.sin(i / 20)), 0) for i in range(int(rate * seconds)))
    audio.writeframes(frames)
'''


class CommandTTSTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        (self.root / "synth.py").write_text(SYNTH, encoding="utf-8")

    def tearDown(self):
        self.directory.cleanup()

    def engine(self, mode):
        return CommandTTS([sys.executable, str(self.root / "synth.py"), "{text_file}", "{output}", mode,
                           str(self.root / "pid.txt")], profile="test-engine", timeout=10)

    async def test_pcm_is_delivered_as_mono_session_rate_frames(self):
        engine = self.engine("ok")
        frames = [event.frame async for event in engine.synthesize("four words of speech")]
        self.assertTrue(frames)
        self.assertEqual({(frame.sample_rate, frame.num_channels) for frame in frames}, {(24000, 1)})
        seconds = sum(frame.samples_per_channel for frame in frames) / 24000
        self.assertAlmostEqual(seconds, 1.0, delta=.05)
        self.assertEqual(engine.records[-1]["outcome"], "success")
        self.assertEqual(engine.records[-1]["profile"], "test-engine")

    async def test_engine_failure_is_recorded_not_spoken(self):
        engine = self.engine("fail")
        with self.assertRaises(Exception):
            async for _ in engine.synthesize("hello there"):
                pass
        self.assertEqual(engine.records[-1]["outcome"], "error")

    async def test_cancellation_kills_the_engine(self):
        engine = self.engine("slow")
        stream = engine.synthesize("hello there")  # The SDK stream starts its task immediately.
        for _ in range(100):
            if (self.root / "pid.txt").exists():
                break
            await asyncio.sleep(.05)
        # The SDK interrupts speech by closing the stream, as on barge-in.
        await stream.aclose()
        self.assertEqual(engine.records[-1]["outcome"], "cancelled")
        pid = int((self.root / "pid.txt").read_text())
        await asyncio.sleep(.3)
        alive = os.popen(f'tasklist /FI "PID eq {pid}"').read() if os.name == "nt" else None
        if os.name == "nt":
            self.assertNotIn(str(pid), alive)
        else:
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_configured_command_is_selected_over_the_windows_profile(self):
        previous = os.environ.get("THREAD_FDB3_TTS_COMMAND")
        os.environ["THREAD_FDB3_TTS_COMMAND"] = json.dumps(["espeak-ng", "-w", "{output}", "-f", "{text_file}"])
        try:
            engine = speech_backend()
            self.assertEqual(engine.command[0], "espeak-ng")
            self.assertNotEqual(engine.profile, "windows-sapi-development")
        finally:
            if previous is None:
                del os.environ["THREAD_FDB3_TTS_COMMAND"]
            else:
                os.environ["THREAD_FDB3_TTS_COMMAND"] = previous


if __name__ == "__main__":
    unittest.main()


class HoldingLineTTSNodeTests(unittest.IsolatedAsyncioTestCase):
    """The fixed holding line is voiced before the answer text exists; other replies are unchanged."""
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        (self.root / "synth.py").write_text(SYNTH, encoding="utf-8")

    def tearDown(self):
        self.directory.cleanup()

    def agent(self):
        from types import SimpleNamespace
        from livekit.agents import APIConnectOptions
        from thread_agent.fdb3_voice import ThreadVoiceAgent
        engine = CommandTTS([sys.executable, str(self.root / "synth.py"), "{text_file}", "{output}", "ok",
                             str(self.root / "pid.txt")], profile="test-engine", timeout=10)
        agent = ThreadVoiceAgent(bridge=None)
        activity = SimpleNamespace(tts=engine, session=SimpleNamespace(conn_options=SimpleNamespace(
            tts_conn_options=APIConnectOptions(max_retry=0))))
        agent._get_activity_or_raise = lambda: activity
        return agent, engine

    async def test_holding_line_frames_arrive_before_the_answer_is_generated(self):
        from thread_agent.fdb3 import ACK_TEXT
        agent, engine = self.agent()
        answer_ready = asyncio.Event()
        async def text():
            yield ACK_TEXT + " "
            await answer_ready.wait()
            yield "Order Q7 is out for delivery."
        frames_before = 0
        frames = agent.tts_node(text(), None)
        async for _ in frames:
            if not answer_ready.is_set():
                frames_before += 1
                if frames_before >= 3:
                    answer_ready.set()
        self.assertGreaterEqual(frames_before, 3)
        self.assertEqual([record["outcome"] for record in engine.records], ["success", "success"])

    async def test_ordinary_reply_is_not_split(self):
        agent, engine = self.agent()
        async def text():
            yield "Order Q7 is out for delivery."
        frames = [frame async for frame in agent.tts_node(text(), None)]
        self.assertTrue(frames)
        self.assertEqual(len(engine.records), 1)
