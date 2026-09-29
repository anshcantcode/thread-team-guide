"""Durable local-planner accounting; transport and abrupt exits are authored fixtures."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import httpx

from thread_agent.fdb3 import LocalPlanner


class PlannerJournalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'requests.jsonl'

    def rows(self):
        return [json.loads(line) for line in self.path.read_text().splitlines()]

    def planner(self, handler):
        planner = LocalPlanner('http://127.0.0.1:9/v1', 'no-provider-fixture', self.path)
        planner.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(planner.close)
        return planner

    @staticmethod
    def completion(content='{"intent":"answer","slots":{},"tool_calls":[]}'):
        return httpx.Response(200, json={'content': content, 'tokens_evaluated': 7,
            'tokens_predicted': 3, 'stop_type': 'eos'})

    async def test_each_http_request_observes_fsynced_intent_and_success_retains_usage(self):
        main_thread = threading.get_ident()
        synced = []
        real_fsync = os.fsync
        def sync(fd):
            self.assertNotEqual(threading.get_ident(), main_thread)
            real_fsync(fd)
            synced.append(fd)
        def handle(request):
            row = self.rows()[-1]
            self.assertEqual(len(synced), len(self.rows()))
            self.assertEqual(row['request']['outcome'], 'pending')
            self.assertFalse(row['request']['tokens_known'])
            self.assertNotIn('usage', row['request'])
            if request.url.path == '/apply-template':
                self.assertEqual(row['phase'], 'template_pending')
                self.assertEqual(row['request']['inference_requests'], 0)
                return httpx.Response(200, json={'prompt': 'authored prompt'})
            self.assertEqual(row['phase'], 'completion_pending')
            self.assertEqual(row['request']['inference_requests'], 1)
            return self.completion()
        planner = self.planner(handle)
        with patch('thread_agent.fdb3.os.fsync', side_effect=sync):
            await planner.plan({})
        rows = self.rows()
        self.assertEqual([r['phase'] for r in rows], ['template_pending', 'completion_pending', 'finished'])
        self.assertEqual(len({r['request']['request_id'] for r in rows}), 1)
        self.assertEqual(rows[-1]['request'], planner.requests[0])
        self.assertEqual(rows[-1]['request']['usage']['total_tokens'], 10)
        self.assertTrue(rows[-1]['request']['tokens_known'])
        self.assertEqual(rows[-1]['request']['outcome'], 'success')

    async def test_failed_template_cannot_create_an_inference_attempt(self):
        planner = self.planner(lambda request: httpx.Response(503, json={'error': 'fixture'}))
        with self.assertRaises(httpx.HTTPStatusError):
            await planner.plan({})
        final = self.rows()[-1]['request']
        self.assertEqual(final['outcome'], 'error')
        self.assertEqual(final['template_requests'], 1)
        self.assertEqual(final['inference_requests'], 0)
        self.assertFalse(final['tokens_known'])

    async def test_malformed_template_does_not_count_unsent_completion(self):
        calls = []
        def handle(request):
            calls.append(request.url.path)
            return httpx.Response(200, json={'prompt': None})
        with self.assertRaises(ValueError):
            await self.planner(handle).plan({})
        self.assertEqual(calls, ['/apply-template'])
        self.assertEqual(self.rows()[-1]['request']['inference_requests'], 0)

    async def test_malformed_native_decision_preserves_returned_tokens_and_failure(self):
        def handle(request):
            if request.url.path == '/apply-template':
                return httpx.Response(200, json={'prompt': 'fixture'})
            return self.completion('{"slots":{},"slots":{}}')
        with self.assertRaises(ValueError):
            await self.planner(handle).plan({})
        final = self.rows()[-1]['request']
        self.assertEqual(final['outcome'], 'error')
        self.assertEqual(final['inference_requests'], 1)
        self.assertEqual(final['usage']['total_tokens'], 10)
        self.assertEqual(final['content'], '{"slots":{},"slots":{}}')

    async def test_cancelled_completion_preserves_unknown_tokens_and_attempt(self):
        entered = asyncio.Event()
        async def handle(request):
            if request.url.path == '/apply-template':
                return httpx.Response(200, json={'prompt': 'fixture'})
            entered.set()
            await asyncio.Event().wait()
        planner = self.planner(handle)
        task = asyncio.create_task(planner.plan({}))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        final = self.rows()[-1]['request']
        self.assertEqual(final['outcome'], 'cancelled')
        self.assertEqual(final['inference_requests'], 1)
        self.assertFalse(final['tokens_known'])
        self.assertNotIn('usage', final)

    async def test_repeated_cancellation_joins_checkpoint_without_blocking_loop(self):
        entered, release = threading.Event(), threading.Event()
        planner = self.planner(lambda request: self.fail('Cancellation must prevent HTTP'))
        original = planner._write_checkpoint
        def delayed(phase, request):
            if phase == 'template_pending':
                entered.set()
                if not release.wait(3):
                    raise AssertionError('Test did not release writer')
            original(phase, request)
        with patch.object(planner, '_write_checkpoint', side_effect=delayed):
            task = asyncio.create_task(planner.plan({}))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                task.cancel()
                await asyncio.sleep(0)
                task.cancel()
                await asyncio.sleep(0)
                self.assertFalse(task.done())
            finally:
                release.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
        self.assertEqual([r['phase'] for r in self.rows()], ['template_pending', 'finished'])
        self.assertEqual(self.rows()[-1]['request']['outcome'], 'cancelled')
        self.assertEqual(self.rows()[-1]['request']['inference_requests'], 0)
        self.assertEqual(self.rows()[-1]['request']['template_requests'], 0)
        self.assertEqual(self.rows()[-1]['request']['template_intents'], 1)

    async def test_cancelled_completion_checkpoint_records_intent_but_no_inference(self):
        entered, release = threading.Event(), threading.Event()
        paths = []
        def handle(request):
            paths.append(request.url.path)
            return httpx.Response(200, json={'prompt': 'fixture'})
        planner = self.planner(handle)
        original = planner._write_checkpoint
        def delayed(phase, request):
            if phase == 'completion_pending':
                entered.set()
                if not release.wait(3):
                    raise AssertionError('Test did not release writer')
            original(phase, request)
        with patch.object(planner, '_write_checkpoint', side_effect=delayed):
            task = asyncio.create_task(planner.plan({}))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                task.cancel()
                await asyncio.sleep(0)
            finally:
                release.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
        self.assertEqual(paths, ['/apply-template'])
        rows = self.rows()
        self.assertEqual(rows[-2]['phase'], 'completion_pending')
        self.assertEqual(rows[-2]['request']['inference_requests'], 1)
        final = rows[-1]['request']
        self.assertEqual(final['outcome'], 'cancelled')
        self.assertEqual(final['inference_requests'], 0)
        self.assertEqual(final['inference_intents'], 1)
        self.assertFalse(final['tokens_known'])
        self.assertNotIn('usage', final)

    async def test_failed_completion_checkpoint_records_no_inference(self):
        paths = []
        def handle(request):
            paths.append(request.url.path)
            return httpx.Response(200, json={'prompt': 'fixture'})
        planner = self.planner(handle)
        original = planner._write_checkpoint
        def fail(phase, request):
            original(phase, request)
            if phase == 'completion_pending':
                raise OSError('authored checkpoint failure after write')
        with patch.object(planner, '_write_checkpoint', side_effect=fail):
            with self.assertRaises(OSError):
                await planner.plan({})
        self.assertEqual(paths, ['/apply-template'])
        final = self.rows()[-1]['request']
        self.assertEqual(final['outcome'], 'error')
        self.assertEqual(final['inference_requests'], 0)
        self.assertEqual(final['inference_intents'], 1)

    async def test_cancellation_during_success_flush_has_a_final_cancelled_record(self):
        entered, release = threading.Event(), threading.Event()
        def handle(request):
            if request.url.path == '/apply-template':
                return httpx.Response(200, json={'prompt': 'fixture'})
            return self.completion()
        planner = self.planner(handle)
        original = planner._write_checkpoint
        def delayed(phase, request):
            if phase == 'finished' and request['outcome'] == 'success':
                entered.set()
                if not release.wait(3):
                    raise AssertionError('Test did not release writer')
            original(phase, request)
        with patch.object(planner, '_write_checkpoint', side_effect=delayed):
            task = asyncio.create_task(planner.plan({}))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                task.cancel()
                await asyncio.sleep(0)
            finally:
                release.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
        final = self.rows()[-1]['request']
        self.assertEqual(final['outcome'], 'cancelled')
        self.assertEqual(final['usage']['total_tokens'], 10)
        self.assertEqual(final, planner.requests[0])

    async def test_failed_initial_durable_write_prevents_http(self):
        planner = self.planner(lambda request: self.fail('Journal failure must prevent HTTP'))
        original = planner._write_checkpoint
        def fail_pending(phase, request):
            if phase == 'template_pending':
                raise OSError('authored disk failure')
            original(phase, request)
        with patch.object(planner, '_write_checkpoint', side_effect=fail_pending):
            with self.assertRaises(OSError):
                await planner.plan({})
        self.assertEqual(self.rows()[-1]['request']['outcome'], 'error')
        self.assertEqual(self.rows()[-1]['request']['inference_requests'], 0)

    async def test_abrupt_worker_exit_leaves_pending_inference_and_unknown_usage(self):
        code = '''import asyncio,os,sys,httpx
from thread_agent.fdb3 import LocalPlanner
async def main():
    def handle(request):
        if request.url.path == '/apply-template':
            return httpx.Response(200,json={'prompt':'fixture'})
        os._exit(23)
    p=LocalPlanner('http://127.0.0.1:9/v1','no-provider-fixture',sys.argv[1])
    p.client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
    await p.plan({})
asyncio.run(main())
'''
        child = await asyncio.to_thread(subprocess.run, [sys.executable, '-c', code, str(self.path)],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=20)
        self.assertEqual(child.returncode, 23, child.stderr)
        final = self.rows()[-1]
        self.assertEqual(final['phase'], 'completion_pending')
        self.assertEqual(final['request']['outcome'], 'pending')
        self.assertEqual(final['request']['inference_requests'], 1)
        self.assertFalse(final['request']['tokens_known'])
        self.assertNotIn('finished_at', final['request'])
        self.assertNotIn('usage', final['request'])


if __name__ == '__main__':
    unittest.main()
