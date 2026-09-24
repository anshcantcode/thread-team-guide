"""Camera transport ownership/backpressure tests; no device, network or evaluator changes."""
import asyncio
import base64
import io
import json
import time
import unittest
from unittest.mock import AsyncMock

from PIL import Image
from thread_agent.engine import Session
from thread_agent.live import LiveConversation


class Client:
    def __init__(self): self.packets = asyncio.Queue(); self.events = []
    async def receive(self): return await self.packets.get()
    async def send_json(self, data): self.events.append(data)


class CameraTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.session = Session(object(), external=True, evaluation=True)
        self.client = Client()
        self.live = LiveConversation(self.session, self.client, android=True)
        self.live.upstream = type('Upstream', (), {'send': AsyncMock()})()
        self.receiver = asyncio.create_task(self.live.receive_browser())
        await self.packet(type='camera_start', stream_id='stream')
        await self.until(lambda: bool(self.live.camera_stream))

    async def asyncTearDown(self):
        self.receiver.cancel()
        await asyncio.gather(self.receiver, return_exceptions=True)
        if self.live.camera_task:
            self.live.camera_task.cancel()
            await asyncio.gather(self.live.camera_task, return_exceptions=True)
        await self.session.close()

    async def until(self, predicate):
        async def wait():
            while not predicate(): await asyncio.sleep(.001)
        await asyncio.wait_for(wait(), 2)

    async def packet(self, **data):
        await self.client.packets.put({'type': 'websocket.receive', 'text': json.dumps(data)})

    def frame(self, seq=1, size=(640, 480), **changes):
        buffer = io.BytesIO(); Image.new('RGB', size, 'green').save(buffer, format='JPEG')
        return dict(type='camera_frame', stream_id='stream', sequence=seq,
                    context_token=self.live.camera_token, client_input_id=self.live.client_input_id,
                    captured_at_ms=time.time()*1000,
                    data={'mime': 'image/jpeg', 'base64': base64.b64encode(buffer.getvalue()).decode()}, **changes)

    def videos(self):
        return [json.loads(call.args[0]) for call in self.live.upstream.send.call_args_list
                if 'video' in json.loads(call.args[0]).get('realtimeInput', {})]

    async def test_frame_reaches_live_provider_without_persistence_or_turn_side_effects(self):
        before = (self.live.input_epoch, self.session.revision, self.live.action_state())
        frame = self.frame()
        await self.live.camera_frame(frame)
        self.assertEqual(len(self.videos()), 1)
        self.assertEqual(self.videos()[0]['realtimeInput']['video']['data'], frame['data']['base64'])
        self.assertEqual(before, (self.live.input_epoch, self.session.revision, self.live.action_state()))
        self.assertFalse(self.session.media)
        self.assertNotIn(frame['data']['base64'], json.dumps(self.session.trace))
        self.assertTrue(self.client.events[-1]['accepted'])

    async def test_stop_rejects_pending_capture_and_old_stream_after_restart(self):
        old = self.frame()
        await self.packet(type='camera_stop', stream_id='stream')
        await self.until(lambda: not self.live.camera_stream)
        await self.live.camera_frame(old)
        await self.packet(type='camera_start', stream_id='new-stream')
        await self.until(lambda: self.live.camera_stream == 'new-stream')
        await self.live.camera_frame(old)
        self.assertEqual(self.videos(), [])

    async def test_typed_and_spoken_corrections_reject_old_frame_but_accept_fresh_context(self):
        for kind in ('text', 'speech_start'):
            old = self.frame()
            await self.packet(type=kind, text='Look at this instead', client_input_id=kind)
            await self.until(lambda: self.live.client_input_id == kind)
            await self.live.camera_frame(old)
            self.assertFalse(self.client.events[-1]['accepted'])
            self.live.camera_last_sent = float('-inf')
            await self.live.camera_frame(self.frame(seq=2 if kind == 'text' else 3))
            self.assertTrue(self.client.events[-1]['accepted'])
        self.assertEqual(len(self.videos()), 2)

    async def test_provider_interrupt_invalidates_a_frame_waiting_for_send_lock(self):
        frame = self.frame()
        await self.live.send_lock.acquire()
        pending = asyncio.create_task(self.live.camera_frame(frame))
        await asyncio.sleep(.01)
        async def incoming(): yield json.dumps({'serverContent': {'interrupted': True}})
        class Provider:
            def __aiter__(self): return incoming()
        sender = self.live.upstream
        self.live.upstream = Provider()
        await self.live.receive_provider()
        self.live.upstream = sender
        self.live.send_lock.release()
        await pending
        self.assertEqual(self.videos(), [])
        self.assertFalse(self.client.events[-1]['accepted'])

    async def test_stop_is_processed_while_camera_waits_without_blocking_microphone(self):
        await self.live.send_lock.acquire()
        await self.packet(**self.frame())
        await self.until(lambda: self.live.camera_task is not None)
        await self.packet(type='camera_stop', stream_id='stream')
        await self.until(lambda: not self.live.camera_stream)
        self.live.send_lock.release()
        await self.live.camera_task
        self.assertEqual(self.videos(), [])

    async def test_payload_rate_sequence_and_age_limits(self):
        for invalid in (
            {'captured_at_ms': time.time()*1000 - 6000}, {'captured_at_ms': float('nan')},
            {'data': {'mime': 'image/jpeg', 'base64': 'x'*174765}},
            {'data': {'mime': 'image/jpeg', 'base64': 'not jpeg'}},
            {'client_input_id': 'old'}, {'context_token': 'old'}, {'sequence': True},
        ):
            frame = self.frame(seq=self.live.camera_sequence + 1); frame.update(invalid)
            await self.live.camera_frame(frame)
            self.assertFalse(self.client.events[-1]['accepted'])
        await self.live.camera_frame(self.frame(seq=100, size=(769, 480)))
        self.assertEqual(self.videos(), [])
        await self.live.camera_frame(self.frame(seq=101))
        await self.live.camera_frame(self.frame(seq=102))
        self.live.camera_last_sent = float('-inf')
        await self.live.camera_frame(self.frame(seq=101))
        self.assertEqual(len(self.videos()), 1)

    async def test_only_one_camera_delivery_task_and_end_invalidates_pending_frame(self):
        await self.live.send_lock.acquire()
        await self.packet(**self.frame())
        await self.until(lambda: self.live.camera_task is not None)
        task = self.live.camera_task
        await self.packet(**self.frame(seq=2))
        await self.until(lambda: any(e.get('sequence') == 2 for e in self.client.events))
        self.assertIs(self.live.camera_task, task)
        await self.packet(type='end')
        await self.receiver
        self.live.send_lock.release()
        await task
        self.assertEqual(self.videos(), [])


if __name__ == '__main__': unittest.main()
