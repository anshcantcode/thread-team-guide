"""Independent transport/protocol failures must remain visible in request accounting."""
import asyncio
import unittest
import httpx
from thread_agent.fdb3 import LocalPlanner


class PlannerAccountingTests(unittest.IsolatedAsyncioTestCase):
    async def run_request(self, handler):
        planner = LocalPlanner("http://127.0.0.1:9/v1", "independent-fixture")
        planner.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(planner.close)
        return planner

    async def test_timeout_is_counted_without_fabricated_usage(self):
        def timeout(request):
            raise httpx.ReadTimeout("fixture", request=request)
        planner = await self.run_request(timeout)
        with self.assertRaises(httpx.ReadTimeout):
            await planner.plan({})
        self.assertEqual(len(planner.requests), 1)
        self.assertEqual(planner.requests[0]["outcome"], "error")
        self.assertNotIn("usage", planner.requests[0])
        self.assertIn("finished_at", planner.requests[0])

    async def test_duplicate_json_fields_fail_closed_and_keep_response(self):
        def duplicate(request):
            if request.url.path=='/apply-template':
                return httpx.Response(200,json={'prompt':'fixture prompt'})
            return httpx.Response(200,json={'content':'{"slots":{},"slots":{}}','stop_type':'eos',
                'tokens_evaluated':5,'tokens_predicted':4})
        planner = await self.run_request(duplicate)
        with self.assertRaises(ValueError):
            await planner.plan({})
        self.assertEqual(planner.requests[0]["usage"]["total_tokens"],9)
        self.assertEqual(planner.requests[0]["outcome"],"error")

    async def test_cancellation_is_counted(self):
        entered = asyncio.Event()
        async def pending(request):
            entered.set()
            await asyncio.Event().wait()
        planner = await self.run_request(pending)
        task = asyncio.create_task(planner.plan({}))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(planner.requests[0]["outcome"],"cancelled")

    async def test_context_truncation_is_rejected_even_if_prefix_is_parseable(self):
        def truncated(request):
            if request.url.path=='/apply-template':
                return httpx.Response(200,json={'prompt':'independent context'})
            return httpx.Response(200,json={'content':'{"intent":"partial","slots":{},"tool_calls":[]}',
                'tokens_evaluated':100,'tokens_predicted':20,'truncated':True,'stop_type':'limit'})
        planner = await self.run_request(truncated)
        with self.assertRaisesRegex(ValueError,'exhausted its context'):
            await planner.plan({})
        self.assertTrue(planner.requests[0]['truncated'])
        self.assertEqual(planner.requests[0]['outcome'],'error')
        self.assertEqual(planner.requests[0]['usage']['total_tokens'],120)
