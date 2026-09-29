"""Untouched upstream latency logic with independent clocks and mocked local judge."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import httpx

from scripts.fdb3_latency import align_result, evaluate_latency, first_turn_end, transcribe_input, main, LATENCY_SCHEMA, checkpoint_json
from thread_agent.fdb3_judge_transport import NativeJudgeTransport

UPSTREAM = Path(__file__).resolve().parents[1] / '.runtime/Full-Duplex-Bench/v3'
INPUT = {'status': 'completed', 'input_sha256': 'a' * 64, 'model_identity': 'local ASR fixture',
         'chunks': [{'text': 'Find locker.', 'timestamp': [0.5, 2.0]},
                    {'text': 'A later correction.', 'timestamp': [4.5, 5.0]}]}
RESULT = {'status': 'completed', 'input_sha256': 'a' * 64,
          'stream_start_time': 1000.0, 'output_audio_start_time': 1000.5,
          'asr_chunks': [{'text': 'Checking.', 'timestamp': [2.5, 3.0]},
                         {'text': 'Locker M12 is available.', 'timestamp': [4.0, 5.0]}],
          'actual_tool_calls': [{'function': 'find_locker', 'args': {'tag': 'M12'},
                                'timestamp_start': 1002.126, 'timestamp_end': 1004.0}]}
JUDGMENT = {'filler_sentence': 'Checking.', 'filler_start_time': 3.0, 'filler_end_time': 3.5,
            'key_info_sentence': 'Locker M12 is available.', 'key_info_start_time': 4.5,
            'key_info_end_time': 5.5}


class TimingControls(unittest.TestCase):
    def test_first_turn_uses_strict_greater_than_two_second_gap(self):
        self.assertEqual(first_turn_end(INPUT['chunks']), 2.0)
        chunks = deepcopy(INPUT['chunks'])
        chunks[1]['timestamp'][0] = 4.0  # Exactly two seconds is not a new turn.
        self.assertEqual(first_turn_end(chunks), 5.0)
        with self.assertRaises(ValueError): first_turn_end([])

    def test_distinct_audio_origins_and_epoch_tools_align_without_mutating_sources(self):
        original = deepcopy(RESULT)
        aligned = align_result(RESULT, INPUT)
        self.assertEqual(aligned['user_speech_end_rel'], 2.0)
        self.assertEqual(aligned['asr_chunks'][0]['timestamp'], [3.0, 3.5])
        self.assertEqual(aligned['actual_tool_calls'][0]['timestamp_start'], 2.13)
        self.assertEqual(RESULT, original)

    def test_missing_clocks_invalid_timestamps_and_mismatched_input_fail_closed(self):
        for field, value in [('stream_start_time', None), ('output_audio_start_time', None),
                             ('stream_start_time', float('nan')), ('output_audio_start_time', True)]:
            result = deepcopy(RESULT); result[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError): align_result(result, INPUT)
        source = deepcopy(INPUT); source['input_sha256'] = 'wrong'
        with self.assertRaises(ValueError): align_result(RESULT, source)
        source = deepcopy(INPUT); source['chunks'][0]['timestamp'] = [2, 1]
        with self.assertRaises(ValueError): align_result(RESULT, source)

    def test_negative_latency_is_preserved_not_clamped_or_filtered(self):
        result = deepcopy(RESULT); result['output_audio_start_time'] = 996
        result['actual_tool_calls'][0]['timestamp_start'] = 999
        aligned = align_result(result, INPUT)
        self.assertEqual(aligned['asr_chunks'][0]['timestamp'][0], -1.5)
        self.assertEqual(aligned['actual_tool_calls'][0]['timestamp_start'], -1)


class UpstreamLatencyControls(unittest.TestCase):
    def evaluate(self, *, failure=None, judgment=None, result=None):
        paths = []
        def server(request):
            paths.append(request.url.path)
            if request.url.path == '/apply-template':
                if failure == 'transport': return httpx.Response(500)
                messages = json.loads(request.content)['messages']
                self.assertIn('USER_SPEECH_END_REL: 2.0', messages[1]['content'])
                self.assertIn('key_info_start_time', messages[0]['content'])
                return httpx.Response(200, json={'prompt': 'unchanged upstream prompt'})
            body = json.loads(request.content)
            self.assertEqual(body['json_schema'], LATENCY_SCHEMA)
            self.assertEqual(body['n_predict'], 500)
            content = 'malformed JSON' if failure == 'json' else json.dumps(judgment or JUDGMENT)
            return httpx.Response(200, json={'content': content, 'model': 'local-latency-fixture',
                'tokens_evaluated': 11, 'tokens_predicted': 9, 'stop_type': 'eos', 'truncated': failure == 'context'})
        def factory(endpoint, calls, **kwargs):
            return NativeJudgeTransport(endpoint, calls, transport=httpx.MockTransport(server), **kwargs)
        with patch('scripts.fdb3_latency.NativeJudgeTransport', side_effect=factory):
            report = evaluate_latency(UPSTREAM, result or RESULT, INPUT,
                'http://127.0.0.1:9/v1', 'local-latency-fixture', output_asr_identity='local output ASR fixture')
        return report, paths

    def test_actual_upstream_metrics_use_aligned_inputs_and_one_declared_local_judgment(self):
        report, paths = self.evaluate()
        self.assertEqual(report['status'], 'complete_diagnostic')
        self.assertFalse(report['qualification_eligible'])
        self.assertFalse(report['timing']['official_latency'])
        self.assertEqual(report['metrics']['first_response_latency_s'], 1.0)
        self.assertEqual(report['metrics']['tool_call_latency_s'], 0.13)
        self.assertEqual(report['metrics']['task_completion_latency_s'], 2.5)
        self.assertEqual(paths, ['/apply-template', '/completion'])
        self.assertEqual(report['judge_requests'][0]['returned_model'], 'local-latency-fixture')
        self.assertEqual(report['judge_requests'][0]['usage']['total_tokens'], 20)

    def test_failed_judge_preserves_attempts_and_available_metrics_without_green_status(self):
        for failure in ('transport', 'json', 'context'):
            with self.subTest(failure=failure):
                report, _ = self.evaluate(failure=failure)
                self.assertEqual(report['status'], 'infrastructure_error')
                self.assertIn('infrastructure_error', report)
                self.assertEqual(len(report['native_judge_calls']), 1)
                self.assertEqual(report['metrics']['first_response_latency_s'], 1.0)
                self.assertIsNone(report['metrics']['task_completion_latency_s'])

    def test_unobserved_judge_timestamp_cannot_become_completion_latency(self):
        judgment = deepcopy(JUDGMENT); judgment['key_info_start_time'] = 3.8
        report, _ = self.evaluate(judgment=judgment)
        self.assertEqual(report['status'], 'infrastructure_error')
        self.assertFalse(report['judge_requests'][0]['valid'])

    def test_no_identified_completion_is_partial_not_failed_model_or_completed_evidence(self):
        judgment = deepcopy(JUDGMENT)
        judgment.update(key_info_sentence='', key_info_start_time=None, key_info_end_time=None)
        report, _ = self.evaluate(judgment=judgment)
        self.assertEqual(report['status'], 'partial_diagnostic')
        self.assertNotIn('infrastructure_error', report)
        self.assertIsNone(report['metrics']['task_completion_latency_s'])

    def test_absent_clock_prevents_even_a_mock_judge_request(self):
        result = deepcopy(RESULT); del result['stream_start_time']
        report, paths = self.evaluate(result=result)
        self.assertEqual(report['status'], 'infrastructure_error')
        self.assertEqual(paths, [])

    def test_disabled_judge_is_explicitly_partial(self):
        report = evaluate_latency(UPSTREAM, RESULT, INPUT, output_asr_identity='local ASR fixture')
        self.assertEqual(report['status'], 'partial_diagnostic')
        self.assertFalse(report['judge_enabled'])
        self.assertEqual(report['judge_requests'], [])

    def test_no_tool_trace_cannot_report_all_latency_metrics_complete(self):
        result = deepcopy(RESULT); result['actual_tool_calls'] = []
        report, _ = self.evaluate(result=result)
        self.assertEqual(report['status'], 'partial_diagnostic')
        self.assertIsNone(report['metrics']['tool_call_latency_s'])


class InputASREvidenceTests(unittest.TestCase):
    def test_completed_asr_survives_termination_before_judge_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root/'result.json'; output = root/'latency.json'
            source.write_text(json.dumps(RESULT))
            evidence = dict(INPUT, request_count=1, requests=[{'outcome': 'success'}])
            argv = ['latency', '--upstream', str(UPSTREAM), '--result', str(source),
                    '--input-audio', str(root/'audio.wav'), '--whisper', str(root/'model'),
                    '--output-asr-identity', 'local fixture', '--output', str(output)]
            with patch('sys.argv', argv), patch('scripts.fdb3_latency.transcribe_input', return_value=evidence), \
                    patch('scripts.fdb3_latency.evaluate_latency', side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt): main()
            record = json.loads(output.read_text())
            self.assertEqual(record['status'], 'infrastructure_error')
            self.assertEqual(record['input_asr_evidence']['request_count'], 1)
            self.assertEqual(json.loads(output.with_suffix('.input-asr.json').read_text()), evidence)
            from scripts.fdb3_run import latency_snapshot
            with patch('scripts.fdb3_run.subprocess.run', side_effect=subprocess.TimeoutExpired('fixture', 180)):
                summary = latency_snapshot(root, root, source, root/'audio.wav', root, output)
            self.assertEqual(summary['status'], 'infrastructure_error')
            self.assertEqual(summary['exit_code'], 124)
            self.assertEqual(json.loads(output.read_text())['input_asr_evidence']['request_count'], 1)

    def test_native_attempt_is_durable_before_each_io_and_after_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'latency.json'
            observed = []
            def server(request):
                report = json.loads(output.read_text())
                call = report['native_judge_calls'][0]
                observed.append((request.url.path, call['outcome'], call['inference_requests']))
                self.assertEqual(report['status'], 'infrastructure_error')
                self.assertEqual(report['input_asr_evidence']['request_count'], 1)
                if request.url.path == '/apply-template':
                    return httpx.Response(200, json={'prompt': 'fixture'})
                raise httpx.ReadTimeout('authored judge timeout')
            def factory(endpoint, calls, **kwargs):
                return NativeJudgeTransport(endpoint, calls, transport=httpx.MockTransport(server), **kwargs)
            with patch('scripts.fdb3_latency.NativeJudgeTransport', side_effect=factory):
                report = evaluate_latency(UPSTREAM, RESULT, dict(INPUT, request_count=1),
                    'http://127.0.0.1:9/v1', 'fixture', output_asr_identity='local fixture',
                    record_callback=lambda body: checkpoint_json(output, body))
            self.assertEqual(observed, [('/apply-template', 'pending', 0), ('/completion', 'pending', 1)])
            persisted = json.loads(output.read_text())
            self.assertEqual(persisted, report)
            self.assertEqual(persisted['native_judge_calls'][0]['outcome'], 'error')
            self.assertEqual(persisted['native_judge_calls'][0]['inference_requests'], 1)
            self.assertIn('finished_at', persisted['native_judge_calls'][0])

    def test_input_asr_attempt_is_durable_before_decode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); audio = root/'audio.wav'; audio.write_bytes(b'fixture')
            model = root/'model'; model.mkdir(); output = root/'asr.json'
            def decode(*args, **kwargs):
                record = json.loads(output.read_text())
                self.assertEqual(record['request_count'], 1)
                self.assertEqual(record['requests'][0]['outcome'], 'pending')
                raise RuntimeError('authored failure')
            with patch('thread_agent.fdb3_voice.WhisperSTT') as constructor:
                constructor.return_value.transcribe.side_effect = decode
                record = transcribe_input(audio, model, record_callback=lambda body: checkpoint_json(output, body))
            self.assertEqual(json.loads(output.read_text()), record)
            self.assertEqual(record['requests'][0]['outcome'], 'error')

    def test_cli_missing_clocks_does_not_start_asr_and_saves_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root/'result.json'; output = root/'latency.json'
            source.write_text(json.dumps({'status': 'completed'}))
            argv = ['latency', '--upstream', str(UPSTREAM), '--result', str(source),
                    '--input-audio', str(root/'missing.wav'), '--whisper', str(root/'missing-model'),
                    '--output-asr-identity', 'local fixture', '--output', str(output)]
            with patch('sys.argv', argv), patch('scripts.fdb3_latency.transcribe_input') as asr, patch('builtins.print'):
                self.assertEqual(main(), 1)
                asr.assert_not_called()
            record = json.loads(output.read_text())
            self.assertEqual(record['status'], 'infrastructure_error')
            self.assertEqual(record['input_asr_requests'], 0)

    def test_local_asr_failure_keeps_attempt_cpu_and_identity_without_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); audio = root/'audio.wav'; audio.write_bytes(b'independent fixture')
            model = root/'model'; model.mkdir(); (model/'config.json').write_text('{}')
            with patch('thread_agent.fdb3_voice.WhisperSTT') as constructor:
                constructor.return_value.transcribe.side_effect = RuntimeError('authored ASR failure')
                record = transcribe_input(audio, model)
            self.assertEqual(record['status'], 'infrastructure_error')
            self.assertEqual(record['request_count'], 1)
            self.assertEqual(record['requests'][0]['outcome'], 'error')
            self.assertIn('input_sha256', record)
            self.assertIn('config.json', record['model_identity']['asset_hashes'])
            self.assertGreaterEqual(record['cpu_seconds'], 0)
            self.assertFalse(record['model_identity']['official_asr'])


if __name__ == '__main__': unittest.main()
