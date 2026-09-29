"""No SDK, providers, WSL or GPU: selection and read-only comparison failure controls."""
import json
from pathlib import Path
import tempfile
import unittest

from scripts.fdb3_config import load_config
from scripts.fdb3_dispatch_smoke import call_sequence, compare_reference, digest, select_recordings, require_judged_evaluation


class DispatchSmokeGuards(unittest.TestCase):
    def test_zero_requests_or_token_limit_are_not_successful_judging(self):
        evaluation = {'status': 'completed', 'judge_enabled': True,
                      'judge_requests': [{}], 'native_judge_calls': [
                          {'outcome': 'success', 'inference_requests': 1, 'native_response': {'stop_type': 'eos'}}]}
        require_judged_evaluation(evaluation)
        evaluation['native_judge_calls'][0]['native_response']['stop_type'] = 'limit'
        with self.assertRaises(ValueError):
            require_judged_evaluation(evaluation)
        evaluation.update(native_judge_calls=[], judge_requests=[])
        with self.assertRaises(ValueError):
            require_judged_evaluation(evaluation)

    def test_selection_is_first_five_ids_not_manifest_order_or_outcomes(self):
        rows = [{'recording': f'authored-{index:03d}'} for index in reversed(range(100))]
        self.assertEqual([r['recording'] for r in select_recordings({'observed': 100, 'recordings': rows})],
                         [f'authored-{index:03d}' for index in range(5)])
        with self.assertRaises(ValueError):
            select_recordings({'observed': 99, 'recordings': rows[:-1]})
        with self.assertRaises(ValueError):
            select_recordings({'observed': 100, 'recordings': [rows[0]] * 100})

    def test_comparison_retains_order_duplicates_and_exact_arguments(self):
        a = {'function': 'read_shelf', 'args': {'id': 'A-1'}, 'timestamp_end': 1}
        b = {'function': 'read_shelf', 'args': {'id': 'a1'}, 'timestamp_end': 2}
        self.assertEqual(len(call_sequence([a, a])), 2)
        self.assertNotEqual(call_sequence([a, b]), call_sequence([b, a]))
        self.assertNotEqual(call_sequence([a]), call_sequence([b]))
        self.assertEqual(call_sequence([a]), call_sequence([dict(a, timestamp_end=30)]))

    def make_reference(self, root):
        reference, linux = root / 'windows', root / 'linux'
        reference.mkdir(); linux.mkdir()
        identity = {'commit': load_config()['windows_reference_source']}
        (reference / 'identity.json').write_text(json.dumps(identity))
        calls = [{'function': 'authored_lookup', 'args': {'tag': 'cobalt'}}]
        body = {'status': 'completed', 'actual_tool_calls': calls}
        path = reference / 'case-000/inference/result.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(body))
        case = {'recording': 'authored', 'input_sha256': 'input-hash', 'result_sha256': digest(path), 'strict_pass': True}
        baseline = {'status': 'complete_diagnostic', 'identity_sha256': digest(reference / 'identity.json'),
                    'cases': [case] + [dict(case, recording=f'other-{i}') for i in range(99)]}
        (reference / 'report.json').write_text(json.dumps(baseline))
        (linux / 'case-000').mkdir()
        (linux / 'case-000/result.json').write_text(json.dumps(body))
        report = {'cases': [dict(case, directory='case-000')]}
        return reference, linux, report

    def test_comparison_checks_reference_hash_and_does_not_write_to_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            reference, linux, report = self.make_reference(Path(directory))
            before = {str(p): digest(p) for p in reference.rglob('*') if p.is_file()}
            self.assertEqual(compare_reference(report, linux, reference)['exact_ordered_matches'], 1)
            self.assertEqual(before, {str(p): digest(p) for p in reference.rglob('*') if p.is_file()})
            with (reference / 'case-000/inference/result.json').open('a') as file:
                file.write(' ')
            with self.assertRaisesRegex(ValueError, 'verified result hash'):
                compare_reference(report, linux, reference)

    def test_live_or_wrong_source_reference_is_not_a_match(self):
        with tempfile.TemporaryDirectory() as directory:
            reference, linux, report = self.make_reference(Path(directory))
            baseline = json.loads((reference / 'report.json').read_text())
            baseline['status'] = 'running'
            (reference / 'report.json').write_text(json.dumps(baseline))
            with self.assertRaisesRegex(ValueError, 'not completed'):
                compare_reference(report, linux, reference)
            (reference / 'identity.json').write_text('{"commit":"wrong"}')
            baseline['identity_sha256'] = digest(reference / 'identity.json')
            (reference / 'report.json').write_text(json.dumps(baseline))
            with self.assertRaisesRegex(ValueError, 'Wrong Windows reference'):
                compare_reference(report, linux, reference)


if __name__ == '__main__':
    unittest.main()
