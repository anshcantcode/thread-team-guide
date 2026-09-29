import asyncio
import time
from types import SimpleNamespace as NS
import unittest
from thread_agent.fdb3 import wait_until_settled


class CompletionTests(unittest.IsolatedAsyncioTestCase):
    async def test_earlier_reply_does_not_close_during_delayed_final_recognition(self):
        session=NS(user_state='listening',agent_state='listening')
        stt=NS(last_activity_at=0,active_recognitions=1)
        bridge=NS(controller=NS(revision=1,_plan_task=None),last_output_revision=1,
                  blocked_through_revision=0,executions={})
        waiting=asyncio.create_task(wait_until_settled(session,stt,bridge,timeout=1,settle=.01))
        await asyncio.sleep(.08)
        self.assertFalse(waiting.done())
        stt.active_recognitions=0; stt.last_activity_at=time.monotonic()
        bridge.controller.revision=2
        await asyncio.sleep(.08)
        self.assertFalse(waiting.done())
        bridge.last_output_revision=2
        await waiting

    async def test_invalidated_reply_and_user_speech_cannot_finish(self):
        session=NS(user_state='speaking',agent_state='listening')
        stt=NS(last_activity_at=0,active_recognitions=0)
        bridge=NS(controller=NS(revision=1,_plan_task=None),last_output_revision=1,
                  blocked_through_revision=1,executions={})
        with self.assertRaises(TimeoutError):
            await wait_until_settled(session,stt,bridge,timeout=.08,settle=.01)


class AwayUserCompletionTests(unittest.IsolatedAsyncioTestCase):
    async def test_idle_away_user_is_settled_but_speaking_is_not(self):
        # 100-run 20260926T194448Z: a fast answer left the user idle >15 s, the SDK
        # reported "away", and shutdown waited for "listening" until timeout.
        bridge=NS(controller=NS(revision=2,_plan_task=None),last_output_revision=2,
                  blocked_through_revision=1,executions={})
        stt=NS(last_activity_at=0,active_recognitions=0)
        await wait_until_settled(NS(user_state='away',agent_state='listening'),stt,bridge,timeout=1,settle=.01)
        with self.assertRaises(TimeoutError):
            await wait_until_settled(NS(user_state='speaking',agent_state='listening'),stt,bridge,timeout=.08,settle=.01)

