"""Window-faithful scoring mirrors the pinned upstream capture window."""
from pathlib import Path
import tempfile
import unittest
import wave

from thread_agent.fdb3_evidence import audio_duration_seconds, upstream_window


def call(end, name="track_order"):
    return {"function": name, "args": {}, "call_id": f"c{end}", "timestamp_end": end}


class UpstreamWindowTests(unittest.TestCase):
    def test_calls_split_at_stream_start_plus_input_duration(self):
        result = {"stream_start_time": 100.0, "actual_tool_calls": [call(130.0), call(140.0), call(141.5)],
                  "output_signal": {"first_signal_at": 139.0}}
        window = upstream_window(result, 40.0)
        self.assertEqual(window["window_end"], 140.0)
        self.assertEqual([c["timestamp_end"] for c in window["calls_in_window"]], [130.0, 140.0])
        self.assertEqual(window["late_call_seconds"], [1.5])
        self.assertTrue(window["first_output_signal_in_window"])

    def test_unfinished_call_is_never_counted_inside(self):
        result = {"stream_start_time": 0.0, "actual_tool_calls": [{"function": "x", "call_id": "u", "timestamp_end": None}]}
        window = upstream_window(result, 10.0)
        self.assertEqual(window["calls_in_window"], [])
        self.assertEqual(window["late_call_seconds"], [None])

    def test_replay_without_stream_clock_is_not_applicable(self):
        self.assertIsNone(upstream_window({"actual_tool_calls": [call(1.0)]}, 10.0))

    def test_duration_reads_a_pcm_wav(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "a.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)
                audio.writeframes(b"\0\0" * 24000)
            self.assertAlmostEqual(audio_duration_seconds(path), 1.5)


if __name__ == "__main__":
    unittest.main()
