"""Independent mocked HTTP controls; no provider, model, or benchmark execution."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

from scripts import fdb3_judge_probe as probe
from thread_agent.fdb3_judge_transport import NativeJudgeTransport


def evaluator():
    module = SimpleNamespace()
    def judge(expected, actual, name):
        reply = module._openai_client.chat.completions.create(
            model="independent-fixture", messages=[{"role": "user", "content": json.dumps(actual)}],
            temperature=0, max_tokens=100)
        value = json.loads(reply.choices[0].message.content)
        return value["correct"], value["explanation"]
    module.llm_judge_argument = judge
    return module


class ProbeCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name) / "judge-controls.json"
        self.paths, self.before_http = [], []
        self.completions = 0

    def server(self, request):
        self.paths.append(request.url.path)
        saved = json.loads(self.output.read_text())
        self.before_http.append(saved)
        self.assertFalse(saved["passed"])
        self.assertEqual(saved["status"], "in_progress")
        call = saved["native_calls"][-1]
        self.assertEqual(call["outcome"], "pending")
        field = "template_requests" if request.url.path == "/apply-template" else "inference_requests"
        self.assertEqual(call[field], 1)
        if request.url.path == "/apply-template":
            return httpx.Response(200, json={"prompt": "independent fixture"})
        self.completions += 1
        return httpx.Response(200, json={"content": json.dumps({"correct": self.completions == 1,
            "explanation": "independent fixture judgment"}), "model": "fixture-local",
            "tokens_evaluated": 12, "tokens_predicted": 8, "stop_type": "eos"})

    def run_probe(self, server=None, module=None):
        def transport(endpoint, calls, **kwargs):
            return NativeJudgeTransport(endpoint, calls, transport=httpx.MockTransport(server or self.server), **kwargs)
        with patch.object(probe, "load", return_value=module or evaluator()), patch.object(probe, "NativeJudgeTransport", side_effect=transport):
            return probe.run_probe(Path(self.directory.name), self.output)

    def test_success_checkpoints_before_http_and_keeps_final_report_fields(self):
        report = self.run_probe()
        self.assertTrue(report["passed"])
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["valid_json"], [True, True])
        self.assertEqual(self.paths, ["/apply-template", "/completion"] * 2)
        saved = json.loads(self.output.read_text())
        self.assertEqual(saved["native_calls"], report["native_calls"])
        self.assertTrue(all(call["outcome"] == "success" for call in saved["native_calls"]))
        self.assertEqual(len(saved["cases"]), 2)
        self.assertEqual(len(saved["raw"]), 2)
        self.assertEqual(saved["paid_requests"], 0)
        self.assertIs(saved["qualification"], False)

    def test_interruption_preserves_completed_first_call_and_second_attempt(self):
        def interrupted(request):
            if self.completions == 1:
                saved = json.loads(self.output.read_text())
                self.assertEqual(len(saved["native_calls"]), 2)
                self.assertEqual(saved["native_calls"][0]["outcome"], "success")
                self.assertEqual(saved["native_calls"][1]["outcome"], "pending")
                self.assertEqual(saved["native_calls"][1]["template_requests"], 1)
                self.assertEqual(len(saved["cases"]), 1)
                raise KeyboardInterrupt("authored interruption")
            return self.server(request)
        with self.assertRaises(KeyboardInterrupt):
            self.run_probe(interrupted)
        saved = json.loads(self.output.read_text())
        self.assertFalse(saved["passed"])
        self.assertEqual(saved["status"], "in_progress")
        self.assertEqual([row["outcome"] for row in saved["native_calls"]], ["success", "error"])
        self.assertEqual(saved["native_calls"][1]["inference_requests"], 0)
        self.assertEqual(self.completions, 1)

    def test_initial_write_failure_aborts_before_evaluator_or_provider(self):
        with patch.object(probe, "checkpoint_json", side_effect=OSError("disk unavailable")), patch.object(probe, "load") as load:
            with self.assertRaises(OSError):
                probe.run_probe(Path(self.directory.name), self.output)
            load.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_pre_submission_checkpoint_failure_stops_that_http_request(self):
        real_write = probe.checkpoint_json
        def failing(path, report):
            calls = report["native_calls"]
            if calls and calls[-1]["outcome"] == "pending" and calls[-1]["inference_intents"]:
                raise OSError("authored pre-inference checkpoint failure")
            real_write(path, report)
        with patch.object(probe, "checkpoint_json", side_effect=failing):
            with self.assertRaises(Exception):
                self.run_probe()
        self.assertEqual(self.paths, ["/apply-template"])
        saved = json.loads(self.output.read_text())
        self.assertFalse(saved["passed"])
        self.assertEqual(saved["native_calls"][0]["inference_requests"], 0)
        # Failed storage cannot persist the latest intent/error; retain the last
        # durable pending attempt instead of fabricating a finished report.
        self.assertEqual(saved["native_calls"][0]["outcome"], "pending")

    def test_swallowed_checkpoint_failure_cannot_start_second_control_or_retry(self):
        real_write = probe.checkpoint_json
        failed = False
        def failing_once(path, report):
            nonlocal failed
            calls = report["native_calls"]
            if not failed and calls and calls[-1]["inference_intents"]:
                failed = True
                raise OSError("transient disk failure")
            real_write(path, report)
        module = evaluator()
        judge = module.llm_judge_argument
        evaluator_calls = []
        def swallowed(*args):
            evaluator_calls.append(args)
            for _ in range(2):  # An evaluator retry still cannot submit after failure.
                try:
                    return judge(*args)
                except Exception:
                    pass
            return False, "SDK error swallowed by evaluator"
        module.llm_judge_argument = swallowed
        with patch.object(probe, "checkpoint_json", side_effect=failing_once):
            with self.assertRaisesRegex(OSError, "transient disk failure"):
                self.run_probe(module=module)
        self.assertEqual(len(evaluator_calls), 1)
        self.assertEqual(self.paths, ["/apply-template"])
        self.assertFalse(json.loads(self.output.read_text())["passed"])

    def test_existing_output_is_not_overwritten(self):
        self.output.write_text("previous evidence")
        with self.assertRaises(FileExistsError):
            self.run_probe()
        self.assertEqual(self.output.read_text(), "previous evidence")


if __name__ == "__main__":
    unittest.main()
