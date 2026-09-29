import unittest
import json
from pathlib import Path
import tempfile
from scripts.fdb3_accounting import request_rows, usage, reconcile


class AccountingTests(unittest.TestCase):
    def test_reproduction_preflight_counts_native_pending_and_final_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); service=root/'services-authored';service.mkdir()
            (service/'judge-controls.json').write_text(json.dumps({'passed':False,
                'raw':[{'usage':{'total_tokens':99}}], 'native_calls':[
                    {'outcome':'success','inference_requests':1,'native_response':{
                        'tokens_evaluated':17,'tokens_predicted':3}},
                    {'outcome':'pending','inference_requests':1}]}))
            totals=reconcile(root)['totals']
            self.assertEqual(totals['judge_attempt_records'],2)
            self.assertEqual(totals['reported_inference_requests'],2)
            self.assertEqual(totals['observed_prompt_tokens'],17)
            self.assertEqual(totals['observed_completion_tokens'],3)
            self.assertEqual(totals['attempts_without_token_usage'],1)

    def test_failed_empty_stt_control_retains_real_attempt_accounting(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); control=root/'live-empty-stt001/empty_stt';control.mkdir(parents=True)
            (control/'result.json').write_text(json.dumps({'status':'failed_local_scripted_control',
                'model_requests':0, 'stt_attempts':[{'outcome':'success'},{'outcome':'success'}],
                'actual_tool_calls':[{'call_id':'read-1'}], 'fixture_tts_requests':[{}, {}, {}]}))
            totals=reconcile(root)['totals']
            self.assertEqual(totals['stt_attempt_records'],2)
            self.assertEqual(totals['actual_tool_invocations'],1)
            self.assertEqual(totals['fixture_tts_attempt_records'],3)
            self.assertEqual(totals['declared_model_requests_without_records'],0)

    def test_post_inference_native_verification_is_counted_without_mirrors(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); extension=root/'extension-audio001';extension.mkdir()
            call={'request_id':'r1'}
            (extension/'result.json').write_text(json.dumps({'actual_tool_calls':[call], 'device_commands':[call]}))
            (extension/'verification.json').write_text(json.dumps({'verification_device_commands':[{'request_id':'r2'}]}))
            (extension/'readback-diagnosis.json').write_text(json.dumps({'device_calls':[{'request_id':'r3'}],
                'commands':[{'returncode':0}]}))
            totals=reconcile(root)['totals']
            self.assertEqual(totals['actual_tool_invocations'],1)
            self.assertEqual(totals['native_diagnostic_tool_attempt_records'],2)
            self.assertEqual(totals['native_transport_command_records'],1)

    def test_declared_counts_and_usage_summaries_are_not_request_records(self):
        self.assertEqual(list(request_rows({'model_requests':0})),[])
        self.assertEqual(list(request_rows({'usage':{'local_model_requests':3}})),[])
        self.assertEqual(list(request_rows({'model_requests':2,'judge_requests':[{'outcome':'error'}]})),
                         [('judge',{'outcome':'error'})])
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); control=root/'live-controls001/barge';control.mkdir(parents=True)
            (control/'result.json').write_text(json.dumps({'model_requests':2,
                'stt_attempts':[{'outcome':'success'}], 'tts_requests':[{'outcome':'success'}],
                'fixture_tts_requests':[{'outcome':'success'},{'outcome':'success'}]}))
            totals=reconcile(root)['totals']
            self.assertEqual(totals['declared_model_requests_without_records'],2)
            self.assertNotIn('observed_prompt_tokens',totals)
            self.assertEqual(totals['stt_attempt_records'],1)
            self.assertEqual(totals['tts_attempt_records'],1)
            self.assertEqual(totals['fixture_tts_attempt_records'],2)

    def test_native_call_and_response_mirror_are_one_attempt(self):
        rows = list(request_rows({'judge_requests': [{'usage': {'total_tokens': 123}}],
            'native_judge_calls': [{'outcome': 'success', 'native_response': {
                'tokens_predicted': 13, 'tokens_evaluated': 110}}]}))
        self.assertEqual(len(rows), 1)
        self.assertEqual(usage(rows[0][1]), {'prompt_tokens': 110, 'completion_tokens': 13})

    def test_failed_attempt_with_missing_usage_is_not_zero_tokens(self):
        rows = list(request_rows({'model_requests': [{'outcome': 'error'}]}))
        self.assertEqual(len(rows), 1)
        self.assertIsNone(usage(rows[0][1]))

    def test_killed_worker_journals_count_once_without_a_final_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); worker=root/'run/case-000/inference';worker.mkdir(parents=True)
            rows=[{'request':{'request_id':'m1','outcome':'pending','inference_requests':0}},
                  {'request':{'request_id':'m1','outcome':'pending','inference_requests':1}}]
            (worker/'model-requests.jsonl').write_text('\n'.join(json.dumps(x) for x in rows))
            (worker/'stt-requests.jsonl').write_text(json.dumps({'request_id':'s1','outcome':'pending'}))
            (worker/'tool-calls.jsonl').write_text(json.dumps({'phase':'dispatch_intent','call':{'call_id':'c1','outcome':'unknown'}}))
            totals=reconcile(root)['totals']
            self.assertEqual(totals['planner_attempt_records'],1)
            self.assertEqual(totals['reported_inference_requests'],1)
            self.assertEqual(totals['attempts_without_token_usage'],1)
            self.assertEqual(totals['stt_attempt_records'],1)
            self.assertEqual(totals['possible_unconfirmed_tool_invocations'],1)
            self.assertEqual(totals['actual_tool_invocations'],0)
            (worker/'result.json').write_text('{"status":"infrastructure_')
            recovered=reconcile(root)
            self.assertEqual(recovered['totals'],totals)
            self.assertTrue(any(r.get('unreadable') for r in recovered['artifacts']))
