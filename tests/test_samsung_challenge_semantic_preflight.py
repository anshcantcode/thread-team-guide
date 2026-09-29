"""Known v1 semantic fixture limits, established before any model attempts."""
import unittest

from evaluation.samsung_challenge.generate import all_cases
from evaluation.samsung_challenge.semantic_preflight import latest_only_counterexample, other_returned_option_counterexample


class SemanticPreflightTests(unittest.TestCase):
    def test_e2e_text_never_requires_unspoken_injected_snapshot(self):
        cases = [case for case, _ in all_cases() if case["mode"] == "e2e_text"]
        self.assertEqual(80, len(cases))
        for case in cases:
            self.assertEqual([], case["injected_plans"])
            self.assertEqual([], case["requirements"])
            self.assertFalse(any(rule["op"] == "snapshot" for rule in case["oracle"]), case["id"])

    def test_waiting_through_corrections_reveals_coupled_call_assumption(self):
        for schedule in range(4):
            case, trace, assessment = latest_only_counterexample(schedule)
            self.assertEqual(1, sum(row.get("action") == "tool_call" for row in trace))
            self.assertFalse(assessment["strict_v1"]["passed"])
            failures = {row["id"] for row in assessment["strict_v1"]["failures"]}
            self.assertEqual({"prompt_cancel", "second_cancel", "total_call_budget"}, failures)
            self.assertFalse(assessment["original_first_reply_matches_current_result"])

    def test_general_lookup_does_not_select_a_private_profile_row(self):
        for family in ("semantic_novel_schema", "semantic_result_injection"):
            case, trace, assessment = other_returned_option_counterexample(family)
            self.assertTrue(assessment["alternate_value_is_in_actual_result"])
            self.assertFalse(assessment["strict_v1"]["passed"])
            self.assertEqual({"grounded_read"}, {row["id"] for row in assessment["strict_v1"]["failures"]})


if __name__ == "__main__":
    unittest.main()
