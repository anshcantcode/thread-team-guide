"""The wrapper must bind its report to the exact bytes it evaluated."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class EvaluationProvenanceTests(unittest.TestCase):
    def test_cli_records_input_inference_metadata_and_evaluator_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            upstream = root / "upstream"
            upstream.mkdir()
            (upstream / "evaluate_pass_rate.py").write_text(
                'def evaluate_scenario_pass(*args, **kwargs):\n'
                '    return {"passed": True, "failure_reason": ""}\n', encoding="utf-8")
            (upstream / "evaluate_tool_calls.py").write_text(
                'def evaluate_scenario(*args, **kwargs):\n    return {}\n', encoding="utf-8")
            (upstream / "analyze_tool_latency.py").write_text("# test evaluator fixture\n", encoding="utf-8")
            result = root / "result.json"
            result.write_text(json.dumps({"status": "completed", "input_sha256": "a" * 64,
                                          "actual_tool_calls": [], "transcript": "Authored control."}), encoding="utf-8")
            metadata = root / "metadata.json"
            metadata.write_text('{"expected_tool_calls": []}', encoding="utf-8")
            output = root / "evaluation.json"
            command = [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts/fdb3_evaluate.py"),
                       "--upstream", str(upstream), "--metadata", str(metadata), "--result", str(result), "--output", str(output)]
            process = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["inference_sha256"], hashlib.sha256(result.read_bytes()).hexdigest())
            self.assertEqual(report["metadata_sha256"], hashlib.sha256(metadata.read_bytes()).hexdigest())
            self.assertEqual(report["input_sha256"], "a" * 64)
            self.assertEqual(report["evaluator_sha256"], {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                                        for p in upstream.glob("*.py")})
            self.assertFalse(report["qualification_eligible"])
