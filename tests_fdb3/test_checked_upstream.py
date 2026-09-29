"""Run pinned upstream CLIs with real wrappers and authored in-memory judges."""
from contextlib import nullcontext, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import httpx

from scripts.fdb3_checked_upstream import main
from scripts.fdb3_verify_released import summarize
from thread_agent.fdb3_judge_transport import NativeJudgeTransport

UPSTREAM = Path(__file__).resolve().parents[1] / '.runtime/Full-Duplex-Bench/v3'


class CheckedUpstreamTests(unittest.TestCase):
    def exercise(self, root, behavior, *, mode='hosted', count=3, real_native=False):
        root = Path(root)
        scenarios = []
        for index in range(count):
            identity = f'authored-{index}'
            calls = [{'function': 'find_locker', 'args': {'tag': f'K{index}'}}]
            scenarios.append({'id': identity, 'domain': 'independent', 'difficulty': 'fixture',
                              'title': 'Locker lookup', 'expected_tool_calls': calls,
                              'dialogue': [{'ai': 'Reports the locker lookup result.'}]})
            directory = root / identity
            directory.mkdir()
            (directory / 'input.wav').write_bytes(b'authored accounting fixture')
            (directory / 'result_thread.json').write_text(json.dumps({
                'example_id': identity, 'status': 'completed', 'actual_tool_calls': calls,
                'transcript': 'Locker is available.', 'asr_chunks': [{'text': 'Locker is available.'}]}))
        benchmark = root / 'benchmark.json'
        benchmark.write_text(json.dumps({'benchmark_name': 'Authored wrapper controls', 'scenarios': scenarios}))
        receipts = []
        codes = []
        for script in ('evaluate_pass_rate', 'evaluate_tool_calls'):
            output = root / f'{script}.json'
            evidence = root / f'{script}-receipts.json'
            def create(**kwargs):
                persisted = json.loads(evidence.read_text())
                self.assertEqual(persisted['judge_requests'][-1]['outcome'], 'pending')
                if behavior == 'raise':
                    raise ConnectionError('Authored judge outage')
                content = ('malformed' if behavior == 'malformed' else
                           json.dumps({'correct': True, 'explanation': 'Authored judge control'}))
                return SimpleNamespace(model='in-memory-fixture', choices=[SimpleNamespace(
                    message=SimpleNamespace(content=content), finish_reason='length' if behavior == 'truncated' else 'stop')])
            client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=lambda: None)
            def local_server(request):
                if request.url.path == '/apply-template':
                    return httpx.Response(200, json={'prompt': 'Authored judge control'})
                return httpx.Response(200, json={'content': json.dumps({'correct': True, 'explanation': 'Authored native control'}),
                    'model': 'in-memory-native-fixture', 'tokens_evaluated': 10, 'tokens_predicted': 5, 'stop_type': 'eos'})
            def transport(endpoint, calls, **kwargs):
                return NativeJudgeTransport(endpoint, calls, transport=httpx.MockTransport(local_server), **kwargs)
            argv = ['checked', '--upstream', str(UPSTREAM), '--script', script, '--evidence', str(evidence),
                    '--judge-mode', mode, '--judge-identity', 'in-memory-fixture',
                    '--judge-endpoint', 'http://127.0.0.1:9/v1', '--', '--benchmark', str(benchmark),
                    '--results-dir', str(root), '--provider', 'thread', '--output', str(output), '--use-llm']
            client_patch = nullcontext() if real_native else patch('openai.OpenAI', return_value=client)
            transport_patch = patch('scripts.fdb3_checked_upstream.NativeJudgeTransport', side_effect=transport) if real_native else nullcontext()
            with patch('sys.argv', argv), client_patch, transport_patch, patch.dict('os.environ', {
                    'THREAD_FDB3_HOSTED_JUDGE_AUTHORIZED': '1', 'OPENAI_API_KEY': 'authored-not-a-real-key'}), redirect_stdout(io.StringIO()):
                codes.append(main())
            receipts.append(evidence)
        summary = summarize(root, 'thread', root / 'evaluate_pass_rate.json', count, receipts)
        return codes, summary, receipts

    def test_valid_judge_receipts_bind_both_outputs_and_inputs(self):
        with tempfile.TemporaryDirectory() as root:
            codes, summary, receipts = self.exercise(root, 'success')
            self.assertEqual(codes, [0, 0])
            self.assertEqual(summary['exit_code'], 0)
            self.assertTrue(summary['judge_verified'])
            self.assertFalse(summary['qualification_eligible'])
            before = Path(root, 'evaluate_pass_rate.json').read_bytes()
            Path(root, 'evaluate_pass_rate.json').write_bytes(before + b' ')
            self.assertEqual(summarize(root, 'thread', Path(root, 'evaluate_pass_rate.json'), 3, receipts)['exit_code'], 2)

    def test_hundred_perfect_exact_matches_cannot_hide_all_failed_judgments(self):
        with tempfile.TemporaryDirectory() as root:
            codes, summary, receipts = self.exercise(root, 'raise', count=100)
            self.assertEqual(codes, [2, 2])
            self.assertEqual(summary['strict_passed'], 100)  # Pinned upstream fallback, unchanged.
            self.assertEqual(summary['exit_code'], 2)
            self.assertFalse(summary['complete'])
            self.assertFalse(summary['judge_verified'])
            self.assertEqual(sum(len(json.loads(p.read_text())['judge_requests']) for p in receipts), 300)

    def test_invalid_or_truncated_judgments_are_incomplete(self):
        for behavior in ('malformed', 'truncated'):
            with self.subTest(behavior=behavior), tempfile.TemporaryDirectory() as root:
                codes, summary, _ = self.exercise(root, behavior)
                self.assertEqual(codes, [2, 2])
                self.assertEqual(summary['exit_code'], 2)

    def test_local_mode_requires_real_native_transport_receipts(self):
        with tempfile.TemporaryDirectory() as root:
            codes, summary, _ = self.exercise(root, 'success', mode='local')
            self.assertEqual(codes, [2, 2])
            self.assertEqual(summary['exit_code'], 2)

    def test_local_native_transport_has_successful_durable_receipts(self):
        with tempfile.TemporaryDirectory() as root:
            codes, summary, receipts = self.exercise(root, 'success', mode='local', real_native=True)
            self.assertEqual(codes, [0, 0])
            self.assertTrue(summary['judge_verified'])
            self.assertEqual(summary['exit_code'], 0)
            for path in receipts:
                report = json.loads(path.read_text())
                self.assertEqual(len(report['judge_requests']), len(report['native_judge_calls']))
                self.assertTrue(all(row['outcome'] == 'success' and row['inference_requests'] == 1
                                    for row in report['native_judge_calls']))

    def test_missing_judge_receipt_is_incomplete(self):
        with tempfile.TemporaryDirectory() as root:
            _, _, receipts = self.exercise(root, 'success')
            receipts[0].unlink()
            self.assertEqual(summarize(root, 'thread', Path(root, 'evaluate_pass_rate.json'), 3, receipts)['exit_code'], 2)
