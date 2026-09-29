"""Actual pinned evaluators against independent controls; no provider/network calls.

Requires the explicit FDB checkout prerequisite and the isolated FDB environment.
Run: .venv-fdb3/Scripts/python -m unittest discover -s tests_fdb3 -q
"""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import httpx
from scripts.fdb3_evaluate import evaluate, checkpoint_json, main
from thread_agent.fdb3_judge_transport import NativeJudgeTransport

ROOT=Path(__file__).resolve().parents[1]
UPSTREAM=ROOT/'.runtime/Full-Duplex-Bench/v3'
SCENARIO={'id':'authored-control','domain':'independent','difficulty':'fixture','title':'Locker lookup',
    'expected_tool_calls':[{'function':'find_locker','args':{'tag':'M12'}}],
    'dialogue':[{'ai':'Reports the locker lookup result.'}]}


class EvaluatorControls(unittest.TestCase):
    def evaluate(self, calls, *, first_template_fails=False, invalid_json=False, record_callback=None):
        count=0
        def local_server(request):
            nonlocal count
            if request.url.path=='/apply-template':
                count+=1
                if count==1 and first_template_fails: return httpx.Response(500)
                return httpx.Response(200,json={'prompt':json.dumps(json.loads(request.content)['messages'])})
            correct='Z45' not in json.loads(request.content)['prompt']
            content='malformed' if invalid_json else json.dumps({'correct':correct,'explanation':'Independent control'})
            return httpx.Response(200,json={'content':content,'model':'in-memory-fixture',
                'tokens_evaluated':10,'tokens_predicted':5,'stop_type':'eos'})
        def transport(endpoint, events, **kwargs):
            return NativeJudgeTransport(endpoint,events,transport=httpx.MockTransport(local_server), **kwargs)
        with patch('scripts.fdb3_evaluate.NativeJudgeTransport',side_effect=transport):
            return evaluate(UPSTREAM,SCENARIO,{'actual_tool_calls':calls,'transcript':'Locker M12 is available.'},
                'http://127.0.0.1:9/v1','in-memory-fixture', record_callback=record_callback)

    def test_positive_control_is_valid_but_explicitly_not_qualification(self):
        result=self.evaluate(SCENARIO['expected_tool_calls'])
        self.assertTrue(result['strict']['passed'])
        self.assertNotIn('infrastructure_error',result)
        self.assertFalse(result['qualification_eligible'])

    def test_partial_transport_failure_cannot_hide_behind_exact_match_fallback(self):
        result=self.evaluate(SCENARIO['expected_tool_calls'],first_template_fails=True)
        self.assertTrue(result['strict']['passed'])  # Upstream's unchanged fallback.
        self.assertIn('infrastructure_error',result)
        self.assertEqual(result['native_judge_calls'][0]['outcome'],'error')

    def test_malformed_judge_output_is_never_valid_evidence(self):
        self.assertIn('infrastructure_error',self.evaluate(SCENARIO['expected_tool_calls'],invalid_json=True))

    def test_no_tools_wrong_args_and_extra_tools_all_fail(self):
        for calls in ([],[{'function':'find_locker','args':{'tag':'Z45'}}],
                      SCENARIO['expected_tool_calls']*2):
            with self.subTest(calls=calls):
                self.assertFalse(self.evaluate(calls)['strict']['passed'])

    def test_disk_checkpoint_precedes_native_io_and_preserves_response_hooks(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'evaluation.json'; observed = []
            def server(request):
                report = json.loads(output.read_text())
                self.assertEqual(report['status'], 'infrastructure_error')
                self.assertIn('infrastructure_error', report)
                call = report['native_judge_calls'][-1]
                observed.append((request.url.path, call['outcome'], call['inference_requests']))
                # A later request must see every earlier validated hook on disk.
                previous = len(report['native_judge_calls']) - 1
                self.assertEqual(len(report['judge_requests']), previous)
                self.assertTrue(all(item['valid'] for item in report['judge_requests']))
                if request.url.path == '/apply-template':
                    return httpx.Response(200, json={'prompt': 'fixture'})
                return httpx.Response(200, json={'content': '{"correct":true,"explanation":"fixture"}',
                    'model': 'fixture', 'tokens_evaluated': 10, 'tokens_predicted': 5, 'stop_type': 'eos'})
            def transport(endpoint, events, **kwargs):
                return NativeJudgeTransport(endpoint, events, transport=httpx.MockTransport(server), **kwargs)
            with patch('scripts.fdb3_evaluate.NativeJudgeTransport', side_effect=transport):
                report = evaluate(UPSTREAM, SCENARIO, {'actual_tool_calls':SCENARIO['expected_tool_calls'],
                    'transcript':'Locker M12 is available.'}, 'http://127.0.0.1:9/v1', 'fixture',
                    record_callback=lambda body: checkpoint_json(output, body))
            self.assertGreaterEqual(len(observed), 2)
            self.assertEqual(observed, [('/apply-template','pending',0), ('/completion','pending',1)] * (len(observed)//2))
            self.assertEqual(json.loads(output.read_text()), report)
            self.assertEqual(report['status'], 'completed')
            self.assertNotIn('infrastructure_error', report)

    def test_interrupt_after_strict_pass_keeps_incomplete_quality_and_cannot_turn_green(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'evaluation.json'
            strict = SimpleNamespace(evaluate_scenario_pass=lambda *args, **kwargs: {'passed':True, 'failure_reason':None})
            def interrupt(*args, **kwargs):
                persisted = json.loads(output.read_text())
                self.assertTrue(persisted['strict']['passed'])
                self.assertIn('infrastructure_error', persisted)
                raise KeyboardInterrupt('authored interruption')
            quality = SimpleNamespace(evaluate_scenario=interrupt)
            with patch('scripts.fdb3_evaluate.load', side_effect=[strict, quality]):
                with self.assertRaises(KeyboardInterrupt):
                    evaluate(UPSTREAM, {}, {}, record_callback=lambda body: checkpoint_json(output, body))
            report = json.loads(output.read_text())
            self.assertTrue(report['strict']['passed'])
            self.assertIsNone(report['quality'])
            self.assertEqual(report['status'], 'infrastructure_error')
            self.assertEqual(report['error_type'], 'KeyboardInterrupt')

    def test_cli_initialization_failure_has_durable_nongreen_report_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=root/'result.json'; output=root/'evaluation.json'
            source.write_text('malformed JSON')
            argv=['evaluate', '--upstream', str(UPSTREAM), '--metadata', str(root/'gold.json'),
                  '--result', str(source), '--output', str(output)]
            with patch('sys.argv', argv):
                with self.assertRaises(ValueError): main()
            before=output.read_bytes(); report=json.loads(before)
            self.assertEqual(report['status'], 'infrastructure_error')
            self.assertFalse(report['strict']['passed'])
            self.assertEqual(report['native_judge_calls'], [])
            with patch('sys.argv', argv), patch('sys.stderr'):
                with self.assertRaises(SystemExit): main()
            self.assertEqual(output.read_bytes(), before)

    def test_malformed_response_failure_and_raw_content_are_durable(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'evaluation.json'
            report=self.evaluate(SCENARIO['expected_tool_calls'], invalid_json=True,
                record_callback=lambda body: checkpoint_json(output, body))
            self.assertEqual(json.loads(output.read_text()), report)
            self.assertEqual(report['status'], 'infrastructure_error')
            self.assertTrue(report['native_judge_calls'])
            self.assertTrue(report['judge_requests'])
            self.assertTrue(all(item['content']=='malformed' and not item['valid']
                                for item in report['judge_requests']))
