from array import array
import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
from livekit import rtc
from thread_agent.fdb3_voice import WaveOutput
from thread_agent.fdb3_room import LocalRoom


class ReceivedSignalTests(unittest.IsolatedAsyncioTestCase):
    async def test_silent_rtp_frame_is_not_reported_as_audible_signal(self):
        with tempfile.TemporaryDirectory() as directory:
            sink=WaveOutput(Path(directory)/'speech.wav')
            try:
                await sink.capture_frame(rtc.AudioFrame(bytes(960),24000,1,480))
                self.assertIsNotNone(sink.first_frame_at)
                self.assertIsNone(sink.first_signal_at)
                await sink.capture_frame(rtc.AudioFrame(array('h',[1000,-1000]*240).tobytes(),24000,1,480))
                self.assertIsNotNone(sink.first_signal_at)
                self.assertEqual(sink.first_signal_offset_seconds,.02)
            finally:
                sink.close()

    async def test_room_clock_starts_at_first_capture_after_decode(self):
        room=object.__new__(LocalRoom)
        room.stream_start_time=None
        captures=[]
        class Source:
            async def capture_frame(self,frame):
                captures.append(room.stream_start_time)
            async def wait_for_playout(self):
                captures.append('drained')
        room.source=Source()
        async def decoded(path,*,paced):
            self.assertIsNone(room.stream_start_time)
            yield object()
            yield object()
        with patch('thread_agent.fdb3_room.audio_frames',decoded),patch('thread_agent.fdb3_room.time.time',return_value=123.5):
            await room.play('fixture.wav')
        self.assertEqual(captures,[123.5,123.5,'drained'])

    async def test_partial_waveform_cannot_hide_receive_failure(self):
        class BrokenStream:
            def __aiter__(self): return self
            async def __anext__(self):
                if not getattr(self, 'sent', False):
                    self.sent = True
                    return SimpleNamespace(frame=rtc.AudioFrame(bytes(960),24000,1,480))
                raise ConnectionError('independent dropped capture')
            async def aclose(self): pass
        with tempfile.TemporaryDirectory() as directory:
            sink=WaveOutput(Path(directory)/'partial.wav')
            room=object.__new__(LocalRoom)
            room.sink,room.closed,room.receiver_errors=sink,False,[]
            room.source=SimpleNamespace(aclose=AsyncMock())
            room.user=SimpleNamespace(disconnect=AsyncMock())
            room.agent=SimpleNamespace(disconnect=AsyncMock())
            try:
                with patch('thread_agent.fdb3_room.rtc.AudioStream',return_value=BrokenStream()):
                    task=asyncio.create_task(room.receive(object()))
                    room.receivers=[task]
                    await asyncio.wait([task])
                self.assertEqual(sink.frames,480)
                with self.assertRaisesRegex(RuntimeError,'WebRTC audio capture failed: ConnectionError'):
                    await room.close()
                self.assertIsInstance(room.receiver_errors[0],ConnectionError)
                room.source.aclose.assert_awaited_once()
                room.user.disconnect.assert_awaited_once()
                room.agent.disconnect.assert_awaited_once()
            finally:
                sink.close()

    async def test_normal_capture_cancellation_and_cleanup_failure_are_distinct(self):
        for failed in (False,True):
            room=object.__new__(LocalRoom)
            room.closed,room.receiver_errors=False,[]
            room.receivers=[asyncio.create_task(asyncio.Event().wait())]
            room.source=SimpleNamespace(aclose=AsyncMock(side_effect=OSError('source close') if failed else None))
            room.user=SimpleNamespace(disconnect=AsyncMock())
            room.agent=SimpleNamespace(disconnect=AsyncMock())
            if failed:
                with self.assertRaisesRegex(OSError,'source close'):
                    await room.close()
            else:
                await room.close()
            self.assertEqual(room.receiver_errors,[])
            room.user.disconnect.assert_awaited_once()
            room.agent.disconnect.assert_awaited_once()
