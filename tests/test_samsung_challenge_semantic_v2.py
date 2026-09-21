"""Semantic v2 authoring corrections, frozen before actual-model exposure."""
from copy import deepcopy
import hashlib
import json
import unittest

from evaluation.samsung_challenge.controls import negative_controls
from evaluation.samsung_challenge.generate import ROOT, canon, semantic_case
from evaluation.samsung_challenge.semantic_oracle_v2 import evaluate_case, expanded, v1
from evaluation.samsung_challenge.semantic_preflight import latest_only_counterexample, other_returned_option_counterexample
from evaluation.samsung_challenge.semantic_v2 import cases, revise_case


class SemanticV2Tests(unittest.TestCase):
    def test_frozen_v2_bytes_sources_and_revisions_match(self):
        folder = ROOT / "semantic-v2"
        manifest = json.loads((folder / "FREEZE.json").read_text(encoding="utf-8"))
        self.assertEqual(0, manifest["new_independent_cases"])
        for name, info in manifest["files"].items():
            self.assertEqual(info["sha256"], hashlib.sha256((folder / name).read_bytes()).hexdigest())
        for name, expected in manifest["source_sha256"].items():
            self.assertEqual(expected, hashlib.sha256((ROOT / name).read_bytes()).hexdigest())
        for partition in ("development", "holdout"):
            regenerated = "".join(canon(case) + "\n" for case, _ in cases() if case["partition"] == partition).encode("utf-8")
            self.assertEqual(regenerated, (folder / f"{partition}.jsonl").read_bytes())

    def test_same_eighty_stimuli_and_nonvacuous_positive_negative_controls(self):
        rows = list(cases())
        self.assertEqual(80, len(rows))
        self.assertEqual(20, sum(c["partition"] == "holdout" for c, _ in rows))
        for case, witness in rows:
            with self.subTest(case=case["id"]):
                original, _ = semantic_case(case["family"], case["factors"]["schedule"], case["factors"]["constraint_profile"])
                for key in ("id", "tools", "steps", "tail_ms", "requirements", "injected_plans"):
                    self.assertEqual(original[key], case[key], key)
                self.assertTrue(evaluate_case(case, witness)["passed"])
                self.assertFalse(evaluate_case(case, [])["passed"])
                for defect, bad in negative_controls(case, witness):
                    self.assertFalse(evaluate_case(case, bad)["passed"], defect)
                if any(r["op"] == "grounded_any_option" for r in case["oracle"]):
                    no_results = [row for row in witness if row.get("kind") != "tool_completed"]
                    self.assertFalse(evaluate_case(case, no_results)["passed"])

    def test_latest_only_and_any_returned_option_are_valid(self):
        for schedule in range(4):
            original, trace, _ = latest_only_counterexample(schedule)
            _, witness = semantic_case("semantic_multicorrection", schedule, 0)
            revised = revise_case(original, witness)
            self.assertTrue(evaluate_case(revised, trace)["passed"])
            current = next(row for row in trace if row.get("action") == "tool_call")
            matches = [reply for reply in revised["replies"] if reply["api_name"] == current["api_name"] and v1.subset(current["args"], reply["match_args"])]
            self.assertEqual(1, len(matches))
            actual = next(row["result"] for row in trace if row.get("kind") == "tool_completed")
            self.assertEqual(actual, matches[0]["deliveries"][0]["result"])
        for family in ("semantic_novel_schema", "semantic_result_injection"):
            original, trace, _ = other_returned_option_counterexample(family)
            _, witness = semantic_case(family, 0, 0)
            self.assertTrue(evaluate_case(revise_case(original, witness), trace)["passed"])

    def test_fabricated_stale_and_wrong_constraint_results_are_rejected(self):
        original, trace, _ = latest_only_counterexample()
        _, witness = semantic_case("semantic_multicorrection", 0, 0)
        revised = revise_case(original, witness)
        for defect in ("fabricated", "stale", "different_constraint", "missing_result"):
            bad = deepcopy(trace)
            final = next(row for row in bad if row.get("action") == "final_response")
            if defect == "fabricated":
                final["payload"]["text"] = "Available option NEVER-RETURNED."
            elif defect == "stale":
                rule = next(r for r in revised["oracle"] if r["op"] == "no_stale_option_after_event")
                final["payload"]["text"] = "Available option " + rule["forbidden_values"][0] + "."
            elif defect == "different_constraint":
                call = next(row for row in bad if row.get("action") == "tool_call")
                # Valid schema, wrong explicit party size (development room schema).
                call["args"]["party"]["adults"] += 1
            else:
                bad = [row for row in bad if row.get("kind") != "tool_completed"]
            with self.subTest(defect=defect):
                self.assertFalse(evaluate_case(revised, bad)["passed"])

    def test_actually_pending_calls_still_require_prompt_cancellation(self):
        original, witness = semantic_case("semantic_multicorrection", 0, 0)
        revised = revise_case(original, witness)
        bad = [row for row in witness if row.get("action") != "cancel_tool"]
        result = evaluate_case(revised, bad)
        self.assertFalse(result["passed"])
        self.assertTrue(any(r["id"].endswith("cancel_if_pending") for r in result["failures"]))

    def test_completed_before_correction_call_does_not_require_cancel(self):
        original, witness = semantic_case("semantic_multicorrection", 0, 0)
        revised = revise_case(original, witness)
        first = next(row for row in witness if row.get("action") == "tool_call")
        earlier = [deepcopy(row) for row in witness if not (row.get("action") == "cancel_tool" and row["payload"]["call_id"] == first["call_id"])]
        response = revised["replies"][0]["deliveries"][0]["result"]
        earlier.append({"kind": "tool_completed", "t_ms": first["t_ms"] + 1, "call_id": first["call_id"], "api_name": first["api_name"], "args": first["args"], "status": "success", "result": response})
        earlier.sort(key=lambda row: row["t_ms"])
        self.assertTrue(evaluate_case(revised, earlier)["passed"])

    def test_explicit_selected_chain_keeps_exact_row_obligation(self):
        original, witness = semantic_case("semantic_authorized_chain", 0, 0)
        revised = revise_case(original, witness)
        self.assertEqual(original["oracle"], revised["oracle"])
        self.assertTrue(any(r["op"] == "binding" for r in revised["oracle"]))


if __name__ == "__main__":
    unittest.main()
