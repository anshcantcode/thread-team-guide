"""Evaluator must execute the frozen source and preserve failed child evidence."""
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from scripts.fdb3_run import evaluate_snapshot, latency_snapshot


class SnapshotEvaluationTests(unittest.TestCase):
    def test_child_uses_snapshot_and_explicit_local_judge(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); output=root/'evaluation.json'
            def child(command,**kwargs):
                self.assertEqual(command[1],str(root/'source/scripts/fdb3_evaluate.py'))
                self.assertEqual(kwargs['cwd'],root/'source')
                self.assertEqual(command[-4:],['--judge-endpoint','http://127.0.0.1:9/v1','--judge-identity','fixture-model'])
                output.write_text(json.dumps({'strict':{'passed':False}}))
                return SimpleNamespace(returncode=0)
            with patch('scripts.fdb3_run.subprocess.run',side_effect=child):
                report=evaluate_snapshot(root/'source',root/'upstream',root/'metadata.json',
                    root/'result.json',output,'http://127.0.0.1:9/v1','fixture-model')
            self.assertIs(report['strict']['passed'],False)

    def test_failed_child_cannot_be_rescued_by_raw_true(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); output=root/'evaluation.json'
            output.write_text('{"strict":{"passed":true}}')
            with patch('scripts.fdb3_run.subprocess.run',return_value=SimpleNamespace(returncode=1)):
                with self.assertRaisesRegex(ValueError,'failed'):
                    evaluate_snapshot(root,root,root/'gold',root/'result',output)
            self.assertTrue(json.loads(output.read_text())['strict']['passed'])

    def test_timeout_is_reported_and_log_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); output=root/'evaluation.json'
            with patch('scripts.fdb3_run.subprocess.run',side_effect=subprocess.TimeoutExpired('fixture',600)):
                with self.assertRaisesRegex(ValueError,'deadline'):
                    evaluate_snapshot(root,root,root/'gold',root/'result',output)
            self.assertTrue(output.with_suffix('.log').is_file())

    def test_latency_missing_child_report_and_nonzero_complete_claim_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); output=root/'latency.json'
            with patch('scripts.fdb3_run.subprocess.run',return_value=SimpleNamespace(returncode=1)):
                summary=latency_snapshot(root,root,root/'result',root/'audio',root/'model',output)
            self.assertEqual(summary['status'],'infrastructure_error')
            self.assertTrue(output.exists())
            output.write_text('{"status":"complete_diagnostic"}')
            with patch('scripts.fdb3_run.subprocess.run',return_value=SimpleNamespace(returncode=1)):
                summary=latency_snapshot(root,root,root/'result',root/'audio',root/'model',output)
            self.assertEqual(summary['status'],'infrastructure_error')
