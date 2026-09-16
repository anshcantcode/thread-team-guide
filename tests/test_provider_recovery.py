"""Bounded pure-generation retry, interruption and per-session diagnostics."""
import asyncio
import json
import unittest
from unittest.mock import patch

import httpx

from thread_agent.engine import Session
from thread_agent.planner import ModelPlanner, ProviderError, provider_trace
from thread_agent.protocol import InputEvent


SCHEMA = {'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok']}


def response(value):
    return httpx.Response(200, json={'candidates':[{'content':{'parts':[{'text':json.dumps(value)}]}}]})


class ProviderRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.config = patch('thread_agent.planner.settings', return_value={
            'provider':'gemini','model':'gemini-3.5-flash-lite','key':'test-only'})
        self.config.start()
        self.planner = ModelPlanner()
        await self.planner.client.aclose()
        self.calls = 0

    async def asyncTearDown(self):
        await self.planner.close()
        self.config.stop()

    def transport(self, handler):
        self.planner.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def test_transient_timeout_then_success_retains_both_attempts(self):
        async def handle(request):
            self.calls += 1
            if self.calls == 1: raise httpx.ReadTimeout('raw secret-bearing transport text must not be recorded')
            return response({'ok':True})
        self.transport(handle)
        records = []
        with provider_trace(records.append):
            self.assertEqual(await self.planner.generate([{'text':'test'}], SCHEMA), {'ok':True})
        self.assertEqual([r['outcome'] for r in records], ['ReadTimeout','http_200'])
        self.assertEqual([r['will_retry'] for r in records], [True,False])
        self.assertEqual(records[0]['request_id'], records[1]['request_id'])
        self.assertGreaterEqual(records[-1]['elapsed_ms'], 240)
        self.assertNotIn('secret-bearing', json.dumps(records))

    async def test_quota_refusal_is_not_retried(self):
        async def handle(request):
            self.calls += 1
            return httpx.Response(429)
        self.transport(handle)
        with self.assertRaisesRegex(ProviderError, 'quota'):
            await self.planner.generate([{'text':'test'}], SCHEMA)
        self.assertEqual(self.calls, 1)

    async def test_total_deadline_cancels_a_nonresponding_request(self):
        cancelled = asyncio.Event()
        async def handle(request):
            self.calls += 1
            try: await asyncio.Event().wait()
            finally: cancelled.set()
        self.transport(handle)
        records = []
        with patch('thread_agent.planner.PROVIDER_BUDGET_SECONDS', .04), provider_trace(records.append):
            with self.assertRaises(ProviderError):
                await asyncio.wait_for(self.planner.generate([{'text':'test'}], SCHEMA), .3)
        self.assertTrue(cancelled.is_set())
        self.assertEqual(self.calls, 1)
        self.assertEqual(records[-1]['outcome'], 'TimeoutError')
        self.assertFalse(records[-1]['will_retry'])

    async def test_pause_during_backoff_stops_retry_and_cannot_apply_intent(self):
        attempted = asyncio.Event()
        async def handle(request):
            self.calls += 1
            attempted.set()
            raise httpx.ConnectTimeout('controlled timeout')
        self.transport(handle)
        session = Session(self.planner, external=True, evaluation=True, manifests={})
        try:
            await session.accept(InputEvent(id='request',type='text',text='Tell me the current task.'))
            await attempted.wait()
            await session.accept(InputEvent(id='pause',type='control',data={'action':'pause'}))
            await asyncio.wait_for(session.inputs.join(), .2)
            await asyncio.sleep(.3)
            self.assertEqual(self.calls, 1)
            self.assertFalse(any(e['type']=='intent_interpreted' for e in session.trace))
            self.assertFalse(any(e['type']=='tool_call' and e['effect']=='write' for e in session.trace))
            records = [e for e in session.trace if e['type']=='provider_attempt']
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]['input_id'], 'request')
        finally: await session.close()

    async def test_inflight_cancellation_is_recorded_and_never_retried(self):
        started = asyncio.Event()
        async def handle(request):
            self.calls += 1
            started.set()
            await asyncio.Event().wait()
        self.transport(handle)
        records = []
        with provider_trace(records.append):
            task = asyncio.create_task(self.planner.generate([{'text':'test'}], SCHEMA))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual(self.calls, 1)
        self.assertEqual(records[-1]['outcome'], 'cancelled')
        self.assertFalse(records[-1]['will_retry'])

    async def test_shared_planner_diagnostics_stay_with_the_requesting_task(self):
        async def handle(request):
            content = json.loads(request.content)['contents'][0]['parts'][0]['text']
            await asyncio.sleep(.01 if content == 'first' else .02)
            return response({'ok':True})
        self.transport(handle)
        rows = {'first':[], 'second':[]}
        async def run(label):
            with provider_trace(rows[label].append):
                await self.planner.generate([{'text':label}], SCHEMA)
        await asyncio.gather(run('first'), run('second'))
        self.assertEqual([len(rows[k]) for k in rows], [1,1])
        self.assertNotEqual(rows['first'][0]['request_id'], rows['second'][0]['request_id'])

    async def test_persistent_transport_failure_stops_after_three_attempts(self):
        async def handle(request):
            self.calls += 1
            raise httpx.ConnectError('controlled unavailable provider')
        self.transport(handle)
        records = []
        with provider_trace(records.append), self.assertRaises(ProviderError):
            await self.planner.generate([{'text':'test'}], SCHEMA)
        self.assertEqual(self.calls, 3)
        self.assertEqual([r['attempt'] for r in records], [1,2,3])
        self.assertFalse(records[-1]['will_retry'])

    async def test_swallowed_cancellation_cannot_apply_late_success_after_replacement(self):
        started = asyncio.Event()
        async def handle(request):
            self.calls += 1
            if self.calls == 1:
                started.set()
                try: await asyncio.Event().wait()
                except asyncio.CancelledError: pass
            return response({'intent':'acknowledge'})
        self.transport(handle)
        session = Session(self.planner, external=True, evaluation=True, manifests={})
        try:
            await session.accept(InputEvent(id='old',type='text',text='Tell me the current task.'))
            await started.wait()
            await session.accept(InputEvent(id='new',type='text',text='Actually, just listen.'))
            await asyncio.wait_for(session.inputs.join(), .5)
            interpreted = [e['input_id'] for e in session.trace if e['type']=='intent_interpreted']
            self.assertEqual(interpreted, ['new'])
            old = [e for e in session.trace if e['type']=='provider_attempt' and e['input_id']=='old']
            self.assertEqual(old[-1]['outcome'], 'cancelled')
            self.assertEqual(self.calls, 2)
        finally: await session.close()

    async def test_swallowed_deadline_cannot_accept_late_success(self):
        async def handle(request):
            self.calls += 1
            try: await asyncio.Event().wait()
            except asyncio.CancelledError: return response({'ok':True})
        self.transport(handle)
        records = []
        with patch('thread_agent.planner.PROVIDER_BUDGET_SECONDS', .04), provider_trace(records.append):
            with self.assertRaises(ProviderError):
                await asyncio.wait_for(self.planner.generate([{'text':'test'}], SCHEMA), .3)
        self.assertEqual(self.calls, 1)
        self.assertEqual(records[-1]['outcome'], 'TimeoutError')
        self.assertFalse(records[-1]['will_retry'])

    async def test_bad_http_decoding_is_contained_and_next_input_still_works(self):
        async def handle(request):
            self.calls += 1
            if self.calls == 1:
                raise httpx.DecodingError('raw private transport details')
            return response({'intent':'acknowledge'})
        self.transport(handle)
        session = Session(self.planner, external=True, evaluation=True, manifests={})
        try:
            await session.accept(InputEvent(id='bad-response',type='text',text='Tell me the task.'))
            await asyncio.wait_for(session.inputs.join(), .3)
            self.assertTrue(any(e['type']=='provider_error' for e in session.trace))
            self.assertNotIn('raw private transport details', json.dumps(session.trace))
            await session.accept(InputEvent(id='next-request',type='text',text='Just listen.'))
            await asyncio.wait_for(session.inputs.join(), .3)
            self.assertEqual(self.calls, 2)  # decoding failure was not retried
            self.assertTrue(any(e['type']=='intent_interpreted' and e['input_id']=='next-request' for e in session.trace))
        finally: await session.close()

    async def test_expired_timeout_is_authoritative_even_before_clock_comparison(self):
        # Windows can schedule a timeout within one clock tick before its nominal
        # deadline. A swallowed cancellation must still retire the timed-out result.
        class ExpiredBudget:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return False
            def expired(self): return True
        async def handle(request):
            self.calls += 1
            return response({'ok': True})
        self.transport(handle)
        with patch('thread_agent.planner.asyncio.timeout', return_value=ExpiredBudget()), patch('thread_agent.planner.PROVIDER_BUDGET_SECONDS', .04):
            with self.assertRaises(ProviderError): await self.planner.generate([{'text': 'test'}], SCHEMA)
        self.assertEqual(self.calls, 1)
