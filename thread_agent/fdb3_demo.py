"""Opt-in local audio monitor and event journal; no selection data or agent policy.

Imported only by the worker's --demo branch. Device writes are off the audio loop
and backpressured (one frame at a time), never an unbounded playback queue.
"""
import asyncio
import json
from pathlib import Path
import threading
import time


class Journal:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def append(self, record):
        with self.lock, self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, default=str) + "\n")
            handle.flush()


class JournaledEvents(list):
    """Preserve the bridge's original list and events; observe, never authorize."""
    def __init__(self, original, journal, errors):
        super().__init__(original)
        self.journal, self.errors = journal, errors

    def append(self, event):
        super().append(event)
        try:
            self.journal.append(event)
        except Exception as exc:
            self.errors.append("demo_event_journal: " + type(exc).__name__)


class PlaybackMonitor:
    def __init__(self, rate, label, journal, *, stream_factory=None):
        if stream_factory is None:
            import sounddevice  # Never imported on the ordinary worker path.
            stream_factory = sounddevice.RawOutputStream
        self.rate, self.label, self.journal = rate, label, journal
        self.frames = self.underflows = 0
        self.closed = self.stopped = self.started = False
        self.stream = stream_factory(samplerate=rate, channels=1, dtype="int16",
                                     device=None, blocksize=0, latency="low")

    def _write(self, data):
        # Opening does not start an empty stream minutes before the first reply.
        if not self.started:
            self.stream.start()
            self.started = True
        return self.stream.write(data)

    async def capture_frame(self, frame):
        if self.closed or self.stopped:
            raise RuntimeError("Playback stream is closed")
        if frame.sample_rate != self.rate or frame.num_channels != 1:
            raise ValueError("Demo monitor requires unchanged mono PCM at the declared rate")
        data = bytes(frame.data)
        cancelled = None
        try:
            task = asyncio.create_task(asyncio.to_thread(self._write, data))
            # Shutdown cannot close a device while its owned blocking write runs.
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError as exc:
                    cancelled = exc
            underflow = task.result()
        except Exception as exc:
            self.journal.append({"event": "playback_error", "stream": self.label,
                                 "at": time.time(), "error_type": type(exc).__name__})
            raise
        if not self.frames:
            self.journal.append({"event": "device_write_started", "stream": self.label,
                                 "at": time.time(), "sample_rate": self.rate,
                                 "scope": "device submission, not proof of human hearing"})
        self.frames += frame.samples_per_channel
        if underflow:
            self.underflows += 1
            self.journal.append({"event": "device_underflow", "stream": self.label,
                                 "at": time.time(), "underflows": self.underflows})
        if cancelled is not None:
            raise cancelled

    async def drain(self):
        if self.started and not self.stopped and not self.closed:
            await asyncio.to_thread(self.stream.stop)
            self.stopped = True

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            if self.started and not self.stopped:
                self.stream.stop()
        finally:
            self.stream.close()
        self.journal.append({"event": "device_closed", "stream": self.label,
                             "at": time.time(), "frames_submitted": self.frames,
                             "underflows": self.underflows})


class PlaybackTee:
    """The original file sink receives the exact frame before device submission."""
    def __init__(self, sink, monitor):
        self.sink, self.monitor = sink, monitor

    def __getattr__(self, name):
        return getattr(self.sink, name)

    async def capture_frame(self, frame):
        await self.sink.capture_frame(frame)
        await self.monitor.capture_frame(frame)

    def close(self):
        try:
            self.sink.close()
        finally:
            self.monitor.close()


class DemoPlayback:
    def __init__(self, output, bridge, *, stream_factory=None):
        journal = Journal(output / "playback.jsonl")
        self.input = PlaybackMonitor(48000, "input", journal, stream_factory=stream_factory)
        try:
            self.reply = PlaybackMonitor(24000, "reply", journal, stream_factory=stream_factory)
        except BaseException:
            self.input.close()
            raise
        bridge.events = JournaledEvents(bridge.events, Journal(output / "controller-events.jsonl"),
                                       bridge.evidence_errors)
        bridge.voice_events = JournaledEvents(bridge.voice_events, Journal(output / "voice-events.jsonl"),
                                             bridge.evidence_errors)

    def tee(self, sink):
        return PlaybackTee(sink, self.reply)

    def close(self):
        try:
            self.input.close()
        finally:
            self.reply.close()
