"""Offline controls for evaluator-only receipt comparison; no model requests."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from participant.agent import ParticipantAgent
from scripts.fdb3_compare_answers import check_lock, judge_function, render_case, summarize


class ComparisonTests(unittest.TestCase):
    def test_lock_guard_fails_closed_for_full_heldout_or_malformed_locks(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "gpu.lock"
            check_lock(path)
            for purpose in ("full100", "FULL run", "held-out-12", "held out", "held_out", None):
                path.write_text(json.dumps({"purpose": purpose}), encoding="utf-8")
                with self.subTest(purpose=purpose), self.assertRaises(RuntimeError):
                    check_lock(path)
            path.write_text("broken", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                check_lock(path)
            path.write_text(json.dumps({"purpose": "component inspection"}), encoding="utf-8")
            check_lock(path)

    def test_reconstruction_does_not_promote_failed_results_or_duplicate_retained_reads(self):
        base = {"api_name": "track_order", "args": {"order_id": "DEV82"}, "step": {},
                "kind": "read_only", "status": "success", "revision": 1,
                "result": {"status": "success", "order_id": "DEV82", "shipping_status": "unknown"}}
        result = {"operations": [{**base, "call_id": "a"},
                   {**base, "call_id": "b", "retained_from_call_id": "a", "revision": 2},
                   {**base, "call_id": "c", "status": "error", "result": {"status": "error", "error": "not_found"}}]}
        text, calls = render_case(ParticipantAgent, result, {})
        self.assertEqual(calls, ["b", "c"])
        self.assertEqual(text.count("DEV82"), 1)
        self.assertIn("shipping status: unknown", text)
        self.assertIn("do not have a successful tool result", text)
        self.assertNotIn("Done", text)

    def test_no_receipt_preserves_recorded_refusal_instead_of_fabricating_completion(self):
        result = {"controller_events": [{"action": "clarification_request", "payload": {"text": "Which destination?"}}]}
        self.assertEqual(render_case(ParticipantAgent, result, {}), ("Which destination?", []))

    def test_exact_upstream_judge_functions_do_not_execute_top_level_side_effects(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "judge.py"
            path.write_text('raise RuntimeError("must not load top-level configuration")\n'
                            'def _strip_json_fences(text): return text\n'
                            'def llm_judge_response(expected_intent, actual_transcript):\n'
                            '    return _get_openai_client()(expected_intent, actual_transcript)\n', encoding="utf-8")
            judge = judge_function(path, lambda intent, actual: (intent, actual))
            self.assertEqual(judge("intent", "actual"), ("intent", "actual"))

    def test_invalid_or_unpaired_scores_cannot_improve_the_mean(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)
            prepared = {"scope": "test", "runs": [{"path": "dev-run"}], "cases": [
                {"run": "dev-run", "case": "first", "recording": "dev-first"},
                {"run": "dev-run", "case": "second", "recording": "dev-second"}]}
            for index, side, score, valid in ((0, "old", 1, True), (0, "new", 0, True), (1, "new", None, False)):
                (path / f"{index:03d}-{side}.json").write_text(json.dumps({"score": score, "valid": valid,
                    "seconds": 2, "native_calls": [{}], "explanation": "authored control"}), encoding="utf-8")
            summary = summarize(prepared, path)
            group = summary["groups"]["dev-run"]
            self.assertEqual((group["paired_valid"], group["old_mean"], group["new_mean"]), (1, 1, 0))
            self.assertEqual(group["invalid_arms"], 1)
            self.assertEqual([row["case"] for row in group["regressions"]], ["first"])


if __name__ == "__main__":
    unittest.main()
