"""Provider/device-free lifecycle controls using explicit runtime stand-ins."""
import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.fdb3_extension_run import run


class Runtime:
    """No LiveKit, Whisper, model endpoint, subprocess or adb is invoked."""
    waveform = b"test-only waveform fixture bytes"

    def __init__(self):
        self.calls = []
        self.failures = {}
        self.transcript = "The generated speech says check Clock manually."
        self.sink_closed = False
        owner = self

        class Planner:
            def __init__(self, *args):
                owner.stage("planner.init")
                self.requests = [{"outcome": "success", "usage": {"prompt_tokens": 7, "completion_tokens": 3}},
                                 {"outcome": "success"}]
            async def close(self): owner.stage("planner.close")

        class Registry:
            def __init__(self, *args, **kwargs):
                owner.stage("registry.init")
                self.session_id = "a" * 32
                self.records = [{"tool": "read_checklist", "result": {"status": "success"}}]

        class Bridge:
            def __init__(self, *args):
                owner.stage("bridge.init")
                self.calls = [{"function": "read_checklist"}]
                self.events = [{"action": "final_response", "payload": {"text": "Different planned text"}}]
                self.controller = SimpleNamespace(operations={"call-1": {"status": "success"}})
                self.voice_events = [{"event": "user_state", "new": "speaking", "at": 4.0}]
            async def start(self): owner.stage("bridge.start")
            async def close(self): owner.stage("bridge.close")

        class Recognizer:
            def __init__(self, *args, prompt=None):
                owner.stage("recognizer.init")
                self.prompt = prompt
                self.records = [{"text": "Read the checklist"}]
            def transcribe(self, path, *, filter_silence=False):
                owner.stage("recognizer.transcribe")
                if not owner.sink_closed or not filter_silence:
                    raise AssertionError("Output must be finalized and silence-filtered")
                if Path(path).read_bytes() != owner.waveform:
                    raise AssertionError("Transcription must use the actual waveform")
                return owner.transcript, [{"text": owner.transcript, "timestamp": [0, 1]}]

        class Sink:
            def __init__(self, path):
                owner.stage("sink.init")
                Path(path).write_bytes(owner.waveform)
                self.frames = 24000
                self.completed = asyncio.Event()
                self.completed.set()
                self.first_frame_at = 11.0
                self.first_signal_at = 11.3
                self.first_signal_offset_seconds = .3
            def close(self):
                owner.stage("sink.close")
                owner.sink_closed = True

        class Session:
            def __init__(self, *args):
                owner.stage("session.init")
                self.input, self.output = SimpleNamespace(), SimpleNamespace()
                self.tts = SimpleNamespace(records=[{"text": "Actual synthesis request"}])
                self.pump = None
            def on(self, event, callback): pass
            async def start(self, **kwargs):
                owner.stage("session.start")
                async def consume():
                    async for _ in self.input.audio.frames: pass
                self.pump = asyncio.create_task(consume())
            async def aclose(self):
                if self.pump:
                    self.pump.cancel()
                    await asyncio.gather(self.pump, return_exceptions=True)
                owner.stage("session.close")

        async def audio_frames(*args, **kwargs):
            owner.stage("audio.frames")
            yield b"test-only input frame"

        async def settled(*args): owner.stage("session.settled")

        class Room:
            def __init__(self, sink):
                owner.stage("room.init")
                self.name = "test-only-room"
            async def start(self, session, bridge): owner.stage("room.start")
            async def play(self, path): owner.stage("room.play")
            async def close(self): owner.stage("room.close")

        self.modules = {}
        for name, attributes in {
            "thread_agent.fdb3": {"ControllerBridge": Bridge, "sha256": lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest(), "wait_until_settled": settled},
            "thread_agent.fdb3_extension": {"EmulatorRegistry": Registry, "ExtensionPlanner": Planner, "TOOLS": {}},
            "thread_agent.fdb3_voice": {"WhisperSTT": Recognizer, "ThreadVoiceAgent": lambda bridge: bridge,
                "WaveOutput": Sink, "FrameInput": lambda frames: SimpleNamespace(frames=frames),
                "audio_frames": audio_frames, "create_session": Session, "input_prompt": lambda *args, **kwargs: None},
            "thread_agent.fdb3_room": {"LocalRoom": Room},
        }.items():
            module = ModuleType(name)
            module.__dict__.update(attributes)
            self.modules[name] = module

    def stage(self, name):
        self.calls.append(name)
        if name in self.failures:
            raise self.failures[name]


class ExtensionRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        audio = self.root / "input.wav"
        audio.write_bytes(b"authored-input-fixture")
        self.args = SimpleNamespace(serial="emulator-5554", adb="never-invoked", output=str(self.root / "output"),
            audio=str(audio), endpoint="http://127.0.0.1:8097/v1", model="test-fixture", whisper="never-loaded")

    async def asyncTearDown(self): self.temporary.cleanup()

    def result(self): return json.loads((Path(self.args.output) / "result.json").read_text(encoding="utf-8"))

    async def test_success_records_actual_waveform_transcript_hash_timing_and_usage(self):
        runtime = Runtime()
        with patch.dict("sys.modules", runtime.modules): await run(self.args)
        result = self.result()
        self.assertEqual(result["status"], "diagnostic_completed")
        self.assertEqual(result["transcript"], runtime.transcript)
        self.assertEqual(result["spoken_sha256"], hashlib.sha256(runtime.waveform).hexdigest())
        self.assertTrue(result["output_waveform_finalized"])
        self.assertEqual(result["first_audio_at"], 11.0)
        self.assertEqual(result["output_signal"]["first_signal_offset_seconds"], .3)
        self.assertFalse(result["output_signal"]["official_latency"])
        self.assertEqual(result["voice_events"][0]["new"], "speaking")
        self.assertLessEqual(result["input_finished_at"], result["finished_at"])
        self.assertLessEqual(result["output_transcription_started_at"], result["output_transcription_finished_at"])
        self.assertEqual(result["usage"]["model_reported_usage"], [{"prompt_tokens": 7, "completion_tokens": 3}, None])
        self.assertEqual(result["usage"]["input_stt_requests"], 1)
        self.assertEqual(result["usage"]["output_stt_requests"], 1)
        self.assertEqual(result["usage"]["tts_requests"], 1)
        self.assertEqual(result["usage"]["paid_requests"], 0)
        self.assertEqual(result["failures"], [])
        self.assertEqual(runtime.calls[-5:], ["session.close", "bridge.close", "planner.close", "sink.close", "recognizer.transcribe"])
        self.assertEqual(result["output_audio_origin"], "direct synthesis PCM; no measured playout")

    async def test_room_uses_existing_transport_and_records_received_waveform(self):
        self.args.room = True
        runtime = Runtime()
        with patch.dict("sys.modules", runtime.modules): await run(self.args)
        result = self.result()
        self.assertEqual(result["status"], "diagnostic_completed")
        self.assertEqual(result["room"], "test-only-room")
        self.assertEqual(result["output_audio_origin"], "received WebRTC PCM")
        self.assertIn("room.start", runtime.calls)
        self.assertIn("room.play", runtime.calls)
        self.assertIn("room.close", runtime.calls)
        self.assertNotIn("audio.frames", runtime.calls)
        self.assertNotIn("session.start", runtime.calls)
        self.assertLess(runtime.calls.index("room.close"), runtime.calls.index("sink.close"))

    async def test_room_start_failure_attempts_all_component_cleanup(self):
        self.args.room = True
        runtime = Runtime()
        original = RuntimeError("room connection failed")
        runtime.failures = {"room.start": original, "room.close": OSError("room close failed")}
        with patch.dict("sys.modules", runtime.modules), self.assertRaises(RuntimeError) as caught:
            await run(self.args)
        self.assertIs(caught.exception, original)
        self.assertEqual(self.result()["error"], "room connection failed")
        for name in ("session.close", "bridge.close", "room.close", "planner.close", "sink.close"):
            self.assertIn(name, runtime.calls)

    async def test_each_constructor_failure_preserves_evidence_and_cleans_previous_resources(self):
        for name, required_cleanup in [
            ("registry.init", []), ("planner.init", []), ("bridge.init", ["planner.close"]),
            ("recognizer.init", ["bridge.close", "planner.close"]),
            ("sink.init", ["bridge.close", "planner.close"]),
            ("session.init", ["bridge.close", "planner.close", "sink.close"]),
        ]:
            with self.subTest(stage=name):
                self.args.output = str(self.root / name)
                runtime = Runtime()
                original = RuntimeError(name)
                runtime.failures[name] = original
                with patch.dict("sys.modules", runtime.modules), self.assertRaises(RuntimeError) as caught:
                    await run(self.args)
                self.assertIs(caught.exception, original)
                result = self.result()
                self.assertEqual(result["status"], "infrastructure_error")
                self.assertEqual(result["error"], name)
                for stage in required_cleanup: self.assertIn(stage, runtime.calls)

    async def test_startup_and_all_cleanup_failures_keep_original_exception_and_ledger(self):
        runtime = Runtime()
        original = RuntimeError("original startup failure")
        runtime.failures = {"session.start": original, "session.close": ValueError("session close"),
            "bridge.close": OSError("bridge close"), "planner.close": RuntimeError("planner close"),
            "sink.close": RuntimeError("sink close")}
        with patch.dict("sys.modules", runtime.modules), self.assertRaises(RuntimeError) as caught:
            await run(self.args)
        self.assertIs(caught.exception, original)
        result = self.result()
        self.assertEqual(result["error"], "original startup failure")
        self.assertEqual([f["stage"] for f in result["failures"]], ["runtime", "cleanup.session", "cleanup.bridge", "cleanup.planner", "cleanup.sink"])
        self.assertEqual(result["operations"], [{"status": "success"}])
        self.assertFalse(result["output_waveform_finalized"])
        self.assertEqual(result["spoken_sha256"], hashlib.sha256(runtime.waveform).hexdigest())
        self.assertNotIn("recognizer.transcribe", runtime.calls)

    async def test_cleanup_only_failure_is_nonzero_but_still_records_generated_speech(self):
        runtime = Runtime()
        original = RuntimeError("session close failed")
        runtime.failures["session.close"] = original
        with patch.dict("sys.modules", runtime.modules), self.assertRaises(RuntimeError) as caught:
            await run(self.args)
        self.assertIs(caught.exception, original)
        result = self.result()
        self.assertEqual(result["error_stage"], "cleanup.session")
        self.assertEqual(result["transcript"], runtime.transcript)
        self.assertIn("sink.close", runtime.calls)

    async def test_output_transcription_failure_preserves_waveform_and_complete_cleanup(self):
        runtime = Runtime()
        runtime.failures["recognizer.transcribe"] = ValueError("output recognition failed")
        with patch.dict("sys.modules", runtime.modules), self.assertRaises(ValueError): await run(self.args)
        result = self.result()
        self.assertEqual(result["error_stage"], "evidence.output_transcription")
        self.assertEqual(result["usage"]["output_stt_requests"], 1)
        self.assertTrue(result["spoken_sha256"])
        self.assertTrue(result["output_waveform_finalized"])

    async def test_empty_spoken_transcript_is_not_success(self):
        runtime = Runtime()
        runtime.transcript = "   "
        with patch.dict("sys.modules", runtime.modules), self.assertRaises(RuntimeError): await run(self.args)
        self.assertEqual(self.result()["status"], "infrastructure_error")
        self.assertEqual(self.result()["transcript"], "   ")

    async def test_cancellation_is_preserved_even_if_cleanup_also_fails(self):
        runtime = Runtime()
        original = asyncio.CancelledError("user stop")
        runtime.failures = {"bridge.start": original, "session.close": RuntimeError("close failed")}
        with patch.dict("sys.modules", runtime.modules), self.assertRaises(asyncio.CancelledError) as caught:
            await run(self.args)
        self.assertIs(caught.exception, original)
        self.assertEqual(self.result()["error_type"], "CancelledError")
        self.assertEqual(self.result()["output_transcription_skipped"], "run_cancelled")
        self.assertNotIn("recognizer.transcribe", runtime.calls)
        self.assertIn("planner.close", runtime.calls)
        self.assertIn("sink.close", runtime.calls)

    async def test_missing_optional_runtime_dependency_still_writes_result(self):
        runtime = Runtime()
        runtime.modules["thread_agent.fdb3_voice"] = None
        with patch.dict("sys.modules", runtime.modules), self.assertRaises(ModuleNotFoundError): await run(self.args)
        self.assertEqual(self.result()["status"], "infrastructure_error")
        self.assertEqual(runtime.calls, [])

    async def test_missing_input_is_recorded_before_any_runtime_constructor(self):
        runtime = Runtime()
        self.args.audio = str(self.root / "missing.wav")
        with patch.dict("sys.modules", runtime.modules), self.assertRaises(FileNotFoundError): await run(self.args)
        self.assertEqual(self.result()["error_type"], "FileNotFoundError")
        self.assertEqual(runtime.calls, [])

    async def test_existing_run_directory_is_never_overwritten(self):
        output = Path(self.args.output)
        output.mkdir()
        (output / "result.json").write_text("prior evidence", encoding="utf-8")
        with self.assertRaises(FileExistsError): await run(self.args)
        self.assertEqual((output / "result.json").read_text(encoding="utf-8"), "prior evidence")


if __name__ == "__main__": unittest.main()
