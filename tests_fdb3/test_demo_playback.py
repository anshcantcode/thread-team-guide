"""Real SDK PCM sinks with fake devices and stubbed inference: CPU only."""
import argparse
from array import array
import asyncio
import builtins
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import wave

from livekit import rtc
from scripts import fdb3_audio_worker as worker
from thread_agent.fdb3_demo import DemoPlayback, Journal, JournaledEvents, PlaybackMonitor, PlaybackTee
from thread_agent.fdb3_room import LocalRoom
from thread_agent.fdb3_voice import WaveOutput


class Device:
    def __init__(self, **kwargs):
        self.kwargs, self.writes = kwargs, []
        self.started = self.stops = self.closes = 0

    def start(self): self.started += 1
    def write(self, data): self.writes.append(data); return False
    def stop(self): self.stops += 1
    def close(self): self.closes += 1


class PlaybackTests(unittest.IsolatedAsyncioTestCase):
    async def test_file_and_device_receive_identical_pcm_in_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            monitor = PlaybackMonitor(24000, "reply", Journal(root / "playback.jsonl"), stream_factory=Device)
            sink = WaveOutput(root / "reply.wav")
            tee = PlaybackTee(sink, monitor)
            parts = [array('h', [1000, -1000] * 240).tobytes(), bytes(480), array('h', [700] * 960).tobytes()]
            for data in parts:
                await tee.capture_frame(rtc.AudioFrame(data, 24000, 1, len(data) // 2))
            self.assertEqual(tee.frames, sum(len(p) // 2 for p in parts))
            tee.close()
            tee.close()
            with wave.open(str(root / "reply.wav"), "rb") as audio:
                self.assertEqual(audio.readframes(audio.getnframes()), b"".join(monitor.stream.writes))
            self.assertEqual(monitor.stream.writes, parts)
            self.assertEqual(monitor.stream.closes, 1)
            self.assertEqual(monitor.stream.kwargs["device"], None)

    async def test_playback_error_retains_the_frame_in_original_file(self):
        class BrokenDevice(Device):
            def write(self, data): raise OSError("fake disconnected device")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            monitor = PlaybackMonitor(24000, "reply", Journal(root / "playback.jsonl"), stream_factory=BrokenDevice)
            tee = PlaybackTee(WaveOutput(root / "reply.wav"), monitor)
            with self.assertRaises(OSError):
                await tee.capture_frame(rtc.AudioFrame(bytes(960), 24000, 1, 480))
            tee.close()
            with wave.open(str(root / "reply.wav"), "rb") as audio:
                self.assertEqual(audio.getnframes(), 480)
            self.assertIn("playback_error", (root / "playback.jsonl").read_text())

    async def test_input_monitor_gets_same_frames_only_as_room_feeds_them(self):
        frames = [rtc.AudioFrame(bytes(1920), 48000, 1, 960) for _ in range(3)]
        order = []
        async def decoded(path, *, paced):
            self.assertFalse(paced)
            for frame in frames: yield frame
        room = object.__new__(LocalRoom)
        room.stream_start_time = None
        async def capture(frame): order.append(("room", frame))
        async def listen(frame): order.append(("device", frame))
        room.source = SimpleNamespace(capture_frame=capture, wait_for_playout=AsyncMock())
        monitor = SimpleNamespace(capture_frame=listen, drain=AsyncMock())
        with patch("thread_agent.fdb3_room.audio_frames", decoded):
            await room.play("neutral-input.wav", monitor=monitor)
        self.assertEqual(order, [(label, frame) for frame in frames for label in ("room", "device")])
        room.source.wait_for_playout.assert_awaited_once()
        monitor.drain.assert_awaited_once()

    async def test_second_device_open_failure_closes_first_without_starting_it(self):
        devices = []
        def factory(**kwargs):
            if devices:
                raise OSError("second device open failure")
            device = Device(**kwargs)
            devices.append(device)
            return device
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(OSError):
                DemoPlayback(Path(directory), SimpleNamespace(), stream_factory=factory)
        self.assertEqual([d.closes for d in devices], [1])
        self.assertEqual(devices[0].started, 0)

    async def test_cancellation_joins_device_write_before_cleanup_and_records_underflow(self):
        entered, release = threading.Event(), threading.Event()
        class SlowDevice(Device):
            def write(self, data):
                entered.set()
                if not release.wait(3): raise TimeoutError("test failed to release device")
                self.writes.append(data)
                return True
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            monitor = PlaybackMonitor(24000, "reply", Journal(root / "playback.jsonl"), stream_factory=SlowDevice)
            self.assertEqual(monitor.stream.started, 0)
            task = asyncio.create_task(monitor.capture_frame(rtc.AudioFrame(bytes(960), 24000, 1, 480)))
            self.assertTrue(await asyncio.to_thread(entered.wait, 3))
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
            monitor.close()
            self.assertEqual(monitor.frames, 480)
            self.assertEqual(monitor.underflows, 1)
            self.assertIn('device_underflow', (root / "playback.jsonl").read_text())

    async def test_controller_events_are_live_exact_and_failed_journal_does_not_change_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "controller-events.jsonl"
            errors = []
            events = JournaledEvents([], Journal(path), errors)
            hold = {"action": "planning_held", "payload": {"seconds": .4}, "bridge_received_at": 1.2}
            events.append(hold)
            self.assertEqual(json.loads(path.read_text()), hold)
            refused = {"action": "clarification_request", "payload": {"gate": {"reasons": ["authored refusal"]}}}
            with patch.object(events.journal, "append", side_effect=OSError("disk full")):
                events.append(refused)
            self.assertEqual(events, [hold, refused])
            self.assertEqual(errors, ["demo_event_journal: OSError"])


class DefaultWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_default_is_invariant_and_opt_in_assembles_only_observation_tees(self):
        imported = builtins.__import__
        def no_playback(name, *args, **kwargs):
            if name == "sounddevice" or (not flag and name == "thread_agent.fdb3_demo"):
                raise AssertionError("Default worker must never import/start playback")
            return imported(name, *args, **kwargs)
        class Planner:
            requests = []
            def __init__(self, *_args): pass
            async def close(self): pass
        class Bridge:
            def __init__(self, *_args):
                self.calls, self.events, self.voice_events, self.evidence_errors = [], [], [], []
                self.controller = SimpleNamespace(messages=[], operations={})
                self.registry = SimpleNamespace(injector=SimpleNamespace(get_log=lambda: []))
            async def start(self): pass
            async def close(self): pass
        class Recognizer:
            records, attempts = [], []
            def __init__(self, *_args, **_kwargs): pass
            def transcribe(self, *_args, **_kwargs): return "authored reply", []
        class Session:
            def __init__(self): self.tts = SimpleNamespace(records=[])
            def on(self, *_args): pass
            async def aclose(self): pass
        class Room:
            name, stream_start_time = "authored-room", 5.0
            def __init__(self, sink):
                self.sink = sink
                expected = PlaybackTee if flag else WaveOutput
                if type(sink) is not expected: raise AssertionError("Wrong worker sink for opt-in state")
            async def start(self, session, bridge):
                bridge.events.append({"action": "planning_held", "payload": {"seconds": .4}, "bridge_received_at": 10.0})
                bridge.voice_events.append({"event": "authored_voice_event", "at": 10.0})
            async def play(self, path, **kwargs):
                if not flag and kwargs: raise AssertionError("Default room.play arguments changed")
                if flag:
                    monitor = kwargs["monitor"]
                    await monitor.capture_frame(rtc.AudioFrame(bytes(1920), 48000, 1, 960))
                    await monitor.drain()
                await self.sink.capture_frame(rtc.AudioFrame(array('h', [900] * 480).tobytes(), 24000, 1, 480))
                self.sink.completed.set()
            async def close(self): pass
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "input.wav"
            audio.write_bytes(b"authored input: decoder stubbed")
            artifacts = []
            for flag in (None, False, True):
                output = root / str(flag)
                args = argparse.Namespace(output=str(output), audio=str(audio), manual=False, unpaced=False,
                    room=True, endpoint="http://127.0.0.1:9/v1", model="stub", contract="stub", whisper="stub")
                if flag is not None: args.demo = flag
                with patch("thread_agent.fdb3_demo.DemoPlayback", side_effect=lambda output, bridge:
                           DemoPlayback(output, bridge, stream_factory=Device)), \
                     patch("builtins.__import__", no_playback), patch.object(worker, "LocalPlanner", Planner), \
                     patch.object(worker, "ControllerBridge", Bridge), patch.object(worker, "load_contract", return_value={}), \
                     patch.object(worker, "load_registry"), patch.object(worker, "WhisperSTT", Recognizer), \
                     patch.object(worker, "create_session", return_value=Session()), patch.object(worker, "input_prompt"), \
                     patch.object(worker, "trim_trailing_silence", return_value=("stub", 0)), \
                     patch.object(worker, "wait_until_settled", AsyncMock()), patch("thread_agent.fdb3_room.LocalRoom", Room), \
                     patch("time.time", return_value=10.0), patch("time.process_time", return_value=2.0):
                    await worker.run(args)
                artifacts.append({p.name: p.read_bytes() for p in output.iterdir()})
            self.assertEqual(artifacts[0], artifacts[1])
            self.assertEqual(set(artifacts[0]), {"result.json", "spoken.wav"})
            result = json.loads(artifacts[0]["result.json"])
            self.assertEqual(result["status"], "completed")
            self.assertNotIn("demo_playback", result)
            self.assertEqual(result["actual_tool_calls"], [])
            enabled = json.loads(artifacts[2]["result.json"])
            self.assertEqual(enabled["status"], "completed")
            self.assertTrue(enabled["demo_playback"]["enabled"])
            for key in ("controller_events", "voice_events", "actual_tool_calls", "model_requests", "input_transcripts"):
                self.assertEqual(enabled[key], result[key])
            self.assertEqual(artifacts[2]["spoken.wav"], artifacts[0]["spoken.wav"])
            self.assertEqual(json.loads(artifacts[2]["controller-events.jsonl"]), result["controller_events"][0])
            playback = [json.loads(line) for line in artifacts[2]["playback.jsonl"].splitlines()]
            self.assertEqual({row["stream"] for row in playback}, {"input", "reply"})


if __name__ == "__main__":
    unittest.main()
