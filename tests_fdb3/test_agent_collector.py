"""Actual bridge collector controls; no model, speech, network or device calls."""
import asyncio
import json
from pathlib import Path
import tempfile
import threading
import unittest

from scripts.fdb3_agent import CollectingBridge


class Planner:
    async def setup(self): pass
    async def close(self): pass
    async def plan(self, context):
        return {'intent': 'cabinet', 'slots': {}, 'tool_calls': [{
            'api_name': 'inspect_cabinet', 'args': {}, 'response_template': '{detail}'}]}


class CollectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_receipt_published_before_response_without_shutdown_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'collector.jsonl'
            entered, release = threading.Event(), threading.Event()
            class Registry:
                def call(self, name, **args):
                    entered.set()
                    if not release.wait(3):
                        raise RuntimeError('Test executor was not released')
                    return {'status': 'success', 'detail': 'Cabinet contains a cobalt bowl.'}
            bridge = CollectingBridge({'inspect_cabinet': {'kind': 'read_only', 'args': {}}},
                                      Registry(), Planner(), room_name='authored-room', telemetry_path=path)
            bridge.tool_journal = Path(directory) / 'journal.jsonl'
            await bridge.start()
            task = asyncio.create_task(bridge.response('Inspect the cabinet.', timeout=4))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                self.assertFalse(path.exists(), 'Dispatch intent is not a completed invocation')
                release.set()
                self.assertEqual(await task, 'Cabinet contains a cobalt bowl.')
                rows = [json.loads(line) for line in path.read_text().splitlines()]
                self.assertEqual(rows, [{'room': 'authored-room', 'call': bridge.calls[0]}])
                self.assertEqual(rows[0]['call']['outcome'], 'success')
                self.assertIsNotNone(rows[0]['call']['timestamp_end'])
            finally:
                release.set()
                await asyncio.gather(task, return_exceptions=True)
                await bridge.close()
            self.assertEqual(len(path.read_text().splitlines()), 1)

    async def test_backend_exception_remains_unknown_in_actual_call_log(self):
        with tempfile.TemporaryDirectory() as directory:
            class Registry:
                def call(self, name, **args):
                    raise RuntimeError('Independent lost receipt')
            path = Path(directory) / 'collector.jsonl'
            bridge = CollectingBridge({'inspect_cabinet': {'kind': 'read_only', 'args': {}}},
                                      Registry(), Planner(), room_name='uncertain-room', telemetry_path=path)
            bridge.tool_journal = Path(directory) / 'journal.jsonl'
            await bridge.start()
            try:
                await bridge.response('Inspect the cabinet.', timeout=2)
                rows = [json.loads(line) for line in path.read_text().splitlines()]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['call']['outcome'], 'unknown')
                self.assertEqual(rows[0]['call']['error_type'], 'RuntimeError')
                self.assertNotIn('result', rows[0]['call'])
            finally:
                await bridge.close()

    async def test_not_submitted_intent_never_appears_in_collector(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'collector.jsonl'
            bridge = CollectingBridge({}, object(), Planner(), room_name='retired-room', telemetry_path=path)
            bridge.tool_journal = Path(directory) / 'journal.jsonl'
            record = {'call_id': 'authored-1', 'outcome': 'unknown'}
            await asyncio.to_thread(bridge._journal_tool, 'dispatch_intent', record)
            record['outcome'] = 'not_submitted'
            await asyncio.to_thread(bridge._journal_tool, 'not_submitted', record)
            self.assertFalse(path.exists())
            self.assertEqual(len(bridge.tool_journal.read_text().splitlines()), 2)
