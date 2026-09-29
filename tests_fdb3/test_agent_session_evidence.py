"""Dispatched job lifecycle receipts without starting models or a LiveKit server."""
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import fdb3_agent


class SessionEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_ready_and_closed_receipts_keep_all_errors_and_actual_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            callbacks = []
            ctx = SimpleNamespace(room=SimpleNamespace(name='authored-random-room'),
                                  add_shutdown_callback=callbacks.append)
            planner = SimpleNamespace(requests=[{'outcome': 'error', 'request_id': 'attempt-1'}])
            class Bridge:
                calls = [{'function': 'inspect_cabinet', 'args': {}, 'outcome': 'unknown'}]
                evidence_errors = ['authored lost effect receipt']
                async def start(self): pass
                async def close(self): pass
            class Session:
                def on(self, name, callback): self.error_callback = callback
                async def start(self, **kwargs): pass
                async def aclose(self): raise RuntimeError('authored cleanup failure')
            recognizer = SimpleNamespace(device='cuda', compute_type='float16', records=[], attempts=[])
            with patch.dict(os.environ, {'THREAD_FDB3_CONTRACT': str(root),
                    'THREAD_FDB3_JOURNAL_DIR': str(root / 'journals'),
                    'THREAD_FDB3_TELEMETRY': str(root / 'collector'),
                    'THREAD_FDB3_ENDPOINT': 'http://127.0.0.1:9/v1',
                    'THREAD_FDB3_MODEL': 'no-model-loaded', 'THREAD_FDB3_WHISPER': str(root)}), \
                 patch.object(fdb3_agent, 'load_contract', return_value={}), \
                 patch.object(fdb3_agent, 'load_registry', return_value=object()), \
                 patch.object(fdb3_agent, 'input_prompt', return_value=None), \
                 patch.object(fdb3_agent, 'verify_whisper', return_value={'name': 'authored-mock'}), \
                 patch.object(fdb3_agent, 'LocalPlanner', return_value=planner), \
                 patch.object(fdb3_agent, 'CollectingBridge', return_value=Bridge()), \
                 patch.object(fdb3_agent, 'WhisperSTT', return_value=recognizer), \
                 patch.object(fdb3_agent, 'create_session', return_value=Session()), \
                 patch.object(fdb3_agent, 'ThreadVoiceAgent', return_value=object()):
                await fdb3_agent.entrypoint(ctx)
                path, = (root / 'journals').glob('*.session.json')
                self.assertEqual(json.loads(path.read_text())['status'], 'ready')
                await callbacks[0]()
                receipt = json.loads(path.read_text())
                self.assertEqual(receipt['status'], 'closed')
                self.assertEqual(receipt['actual_tool_calls'], Bridge.calls)
                self.assertEqual(receipt['model_requests'], planner.requests)
                self.assertIn('authored lost effect receipt', receipt['errors'])
                self.assertIn('Session cleanup: RuntimeError', receipt['errors'])
                self.assertEqual(receipt['whisper_device'], 'cuda')
                self.assertEqual(receipt['whisper'], {'name': 'authored-mock'})

    async def test_wrong_model_fails_before_planner_or_recognizer_start(self):
        with patch.dict(os.environ, {'THREAD_FDB3_WHISPER': 'authored-absent-model'}), \
             patch.object(fdb3_agent, 'verify_whisper', side_effect=ValueError('SHA-256 mismatch')), \
             patch.object(fdb3_agent, 'LocalPlanner') as planner, \
             patch.object(fdb3_agent, 'WhisperSTT') as recognizer:
            with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                await fdb3_agent.entrypoint(SimpleNamespace())
            planner.assert_not_called()
            recognizer.assert_not_called()


if __name__ == '__main__':
    unittest.main()
