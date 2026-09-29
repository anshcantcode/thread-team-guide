"""Device playback receipts, using the installed SDK with synthetic PCM only."""
import asyncio
import unittest

from livekit import rtc
from thread_agent.fdb3_client import audio_sink


class ClientAudioOutputTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.messages = []

        async def send(message):
            self.messages.append(message)

        self.sink = audio_sink(send)
        self.playback_events = []
        self.sink.on("playback_finished", self.playback_events.append)

    async def asyncTearDown(self):
        self.sink.clear_buffer()
        self.sink.close()
        await asyncio.sleep(0)

    async def segment(self):
        await self.sink.capture_frame(rtc.AudioFrame(b"\0\0" * 480, 24000, 1, 480))
        identity = self.messages[-1]["message_id"]
        self.sink.flush()
        await asyncio.sleep(0)
        return identity

    async def assert_pending(self, waiter):
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(waiter), .025)

    async def test_empty_flush_cannot_mark_unheard_pending_audio_as_finished(self):
        identity = await self.segment()
        waiter = asyncio.create_task(self.sink.wait_for_playout())
        try:
            self.sink.flush()
            await self.assert_pending(waiter)
            self.sink.acknowledge({"message_id": identity, "seconds": .02, "interrupted": False, "status": "played"})
            result = await asyncio.wait_for(waiter, 1)
            self.assertFalse(result.interrupted)
            self.assertAlmostEqual(result.playback_position, .02)
        finally:
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)

    async def test_out_of_order_receipts_finish_segments_in_capture_order(self):
        first = await self.segment()
        first_waiter = asyncio.create_task(self.sink.wait_for_playout())
        await asyncio.sleep(0)  # Bind the SDK waiter to the first captured segment.
        second = await self.segment()
        try:
            self.sink.acknowledge({"message_id": second, "seconds": .02, "interrupted": False, "status": "played"})
            await self.assert_pending(first_waiter)
            self.sink.acknowledge({"message_id": first, "seconds": .01, "interrupted": True, "status": "interrupted"})
            await asyncio.wait_for(first_waiter, 1)
            await asyncio.wait_for(self.sink.wait_for_playout(), 1)
            self.assertEqual([(event.playback_position, event.interrupted) for event in self.playback_events],
                             [(.01, True), (.02, False)])
        finally:
            first_waiter.cancel()
            await asyncio.gather(first_waiter, return_exceptions=True)

    async def test_late_ack_for_cleared_audio_cannot_finish_the_next_segment(self):
        obsolete = await self.segment()
        self.sink.clear_buffer()
        await asyncio.sleep(0)
        current = await self.segment()
        waiter = asyncio.create_task(self.sink.wait_for_playout())
        try:
            self.sink.acknowledge({"message_id": obsolete, "seconds": .02, "interrupted": False, "status": "played"})
            await self.assert_pending(waiter)
            self.sink.acknowledge({"message_id": current, "seconds": .02, "interrupted": False, "status": "played"})
            result = await asyncio.wait_for(waiter, 1)
            self.assertFalse(result.interrupted)
            self.assertAlmostEqual(result.playback_position, .02)
        finally:
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)

    async def test_intermediate_playback_statuses_are_not_completion_receipts(self):
        identity = await self.segment()
        waiter = asyncio.create_task(self.sink.wait_for_playout())
        try:
            for status in ("playing", "paused", "resumed"):
                self.sink.acknowledge({"message_id": identity, "seconds": .02, "interrupted": False, "status": status})
                await self.assert_pending(waiter)
            self.sink.acknowledge({"message_id": identity, "seconds": .02, "interrupted": False, "status": "played"})
            await asyncio.wait_for(waiter, 1)
        finally:
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
