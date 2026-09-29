"""Bounded local TTS -> WAV -> CPU Whisper smoke; never benchmark evidence.

Uses THREAD's real portable speech backend and pinned recognizer assets. The
sentence is independently authored synthetic speech, not a benchmark example.
No planner, judge, GPU, hosted API, or existing service is contacted.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def smoke(whisper, output):
    from scripts.fdb3_config import verify_whisper
    whisper_identity = verify_whisper(whisper)
    from faster_whisper import WhisperModel
    from thread_agent.fdb3_voice import speech_backend

    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "STARTED", "full_reproduction": False,
              "scope": "cpu_component_only_not_candidate_cuda_or_agentserver_dispatch",
              "synthetic_authored_speech": True, "benchmark_recordings": 0,
              "paid_requests": 0, "device": "cpu", "compute_type": "int8", "cpu_threads": 2,
              "whisper": whisper_identity}
    sentence = "The blue cup is on the table."
    report["input_text"] = sentence
    started = time.monotonic()
    try:
        backend = speech_backend()
        try:
            frames = [event.frame async for event in backend.synthesize(sentence)]
        finally:
            await backend.aclose()
        if not frames:
            raise RuntimeError("Portable TTS delivered no audio frames")
        if {(frame.sample_rate, frame.num_channels) for frame in frames} != {(24000, 1)}:
            raise RuntimeError("Unexpected TTS PCM format")
        audio = output / "synthetic-speech.wav"
        with wave.open(str(audio), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(24000)
            handle.writeframes(b"".join(bytes(frame.data) for frame in frames))
        recognizer = WhisperModel(str(whisper), device="cpu", compute_type="int8",
                                  cpu_threads=2, num_workers=1, local_files_only=True)
        segments, _ = recognizer.transcribe(str(audio), language="en", beam_size=5,
                                            condition_on_previous_text=False)
        text = " ".join(segment.text.strip() for segment in segments)
        recovered = {word: word in text.casefold() for word in ("blue", "cup", "table")}
        report.update(transcript=text, recovered_words=recovered,
                      speech_profile=backend.profile, audio_frames=len(frames),
                      audio_seconds=sum(frame.samples_per_channel for frame in frames) / 24000,
                      audio_sha256=hashlib.sha256(audio.read_bytes()).hexdigest())
        if not all(recovered.values()):
            raise RuntimeError("CPU recognizer did not recover all three authored content words")
        report["status"] = "PASSED_LOCAL_COMPONENT_SMOKE"
    except Exception as exc:
        report.update(status="FAILED", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        report["elapsed_seconds"] = time.monotonic() - started
        (output / "smoke.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--whisper", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("This diagnostic must execute on Linux")
    # This historical component control intentionally remains CPU-only. Use
    # fdb3_dispatch_smoke.py for the separately preregistered five-recording GPU probe.
    os.environ.setdefault("THREAD_FDB3_TTS_COMMAND", '["espeak-ng","-w","{output}","-f","{text_file}"]')
    os.environ.setdefault("THREAD_FDB3_TTS_PROFILE", "espeak-ng")
    asyncio.run(smoke(args.whisper, args.output))


if __name__ == "__main__":
    main()
