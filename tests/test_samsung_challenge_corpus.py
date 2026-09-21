"""Test corpus integrity/oracles, NOT participant behavior or model accuracy."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

from evaluation.samsung_challenge.controls import negative_controls
from evaluation.samsung_challenge.generate import (FAMILIES, SEMANTIC_FAMILIES, ROOT, all_cases, canon, controller_case,
                                                   runtime_fingerprint, validate_case)
from evaluation.samsung_challenge.oracle import evaluate_case, schema_errors, subset


class ChallengeCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = list(all_cases())

    def test_distinct_cases_have_nonvacuous_oracles(self):
        self.assertEqual(3136, len(self.rows))
        self.assertEqual(2880, sum(c["mode"] == "controller_injected" for c, _ in self.rows))
        self.assertEqual(3136, len({runtime_fingerprint(c) for c, _ in self.rows}))
        self.assertEqual(52, len(FAMILIES) + len(SEMANTIC_FAMILIES))
        for case, witness in self.rows:
            with self.subTest(case=case["id"]):
                self.assertEqual([], validate_case(case, witness))
                self.assertFalse(evaluate_case(case, [])["passed"])

    def test_broken_agent_controls_are_caught(self):
        attempted = Counter()
        for case, witness in self.rows:
            for defect, bad_trace in negative_controls(case, witness):
                with self.subTest(case=case["id"], defect=defect):
                    attempted[defect] += 1
                    self.assertFalse(evaluate_case(case, bad_trace)["passed"], "A negative control escaped the oracle")
        self.assertEqual(3136, attempted["silent_agent"])
        self.assertGreater(attempted["always_clarify"], 1000)
        self.assertGreater(attempted["ignores_interruption_cancellation"], 400)
        self.assertGreater(attempted["duplicates_write_with_new_call_id"], 400)

    def test_exact_frozen_rows_and_hashes(self):
        frozen = ROOT / "frozen"
        manifest = json.loads((frozen / "FREEZE.json").read_text(encoding="utf-8"))
        for name, info in manifest["files"].items():
            raw = (frozen / name).read_bytes()
            self.assertEqual(info["sha256"], hashlib.sha256(raw).hexdigest(), name)
            self.assertEqual(info["bytes"], len(raw), name)
        for partition in ("development", "holdout"):
            generated = "".join(canon(c) + "\n" for c, _ in self.rows if c["partition"] == partition)
            self.assertEqual(generated.encode("utf-8"), (frozen / f"{partition}.jsonl").read_bytes())

    def test_real_model_cases_never_include_injected_answers(self):
        for case, _ in self.rows:
            if case["mode"] != "controller_injected":
                self.assertEqual([], case["injected_plans"], case["id"])
            for step in case["steps"]:
                event = step["event"]
                if not isinstance(event, dict):
                    continue
                self.assertFalse(any(str(k).startswith("_") for k in event))
                if event.get("event_type") == "user_audio_chunk":
                    self.assertNotIn("text", event["payload"])
                    self.assertNotIn("transcript", event["payload"])
                if event.get("event_type") == "video_frame":
                    self.assertNotIn("caption", event["payload"])
                    self.assertNotIn("embedding", event["payload"])

    def test_media_acquisition_is_explicit_not_claimed_executed(self):
        media = [c for c, _ in self.rows if c["mode"] in {"e2e_audio", "e2e_visual"}]
        self.assertEqual(176, len(media))
        self.assertTrue(all(c["requirements"] for c in media))
        pending = [c for c in media if any(r.get("status") == "requires_acquisition" for r in c["requirements"])]
        self.assertEqual(140, len(pending))
        self.assertTrue(all(c["partition"] == "holdout" for c in pending if c["factors"]["content_profile"] == 3))


class OracleBoundaryTests(unittest.TestCase):
    def test_schema_numbers_do_not_confuse_bools_or_overflow_large_integers(self):
        schema = {"args": {"n": {"type": "number", "required": True}}}
        for value in (0, 1, 1.0, 2.5, 10**1000):
            self.assertEqual([], schema_errors(schema, {"n": value}))
        for value in (True, False, "1", float("nan"), float("inf"), float("-inf")):
            self.assertTrue(schema_errors(schema, {"n": value}))
        enum = {"args": {"n": {"type": "number", "enum": [1]}}}
        self.assertEqual([], schema_errors(enum, {"n": 1.0}))
        self.assertTrue(schema_errors(enum, {"n": True}))

    def test_schema_empty_optional_values_are_valid(self):
        schema = {"args": {"s": {"type": "string"}, "n": {"type": "number"}, "b": {"type": "boolean"}, "a": {"type": "array", "items": "number"}}}
        self.assertEqual([], schema_errors(schema, {"s": "", "n": 0, "b": False, "a": []}))
        self.assertEqual([], schema_errors(schema, {}))
        self.assertFalse(subset(True, 1))
        self.assertTrue(subset(1.0, 1))

    def test_numeric_list_members_and_nested_required_are_checked(self):
        schema = {"args": {"points": {"type": "array", "items": {"type": "object", "properties": {
            "xy": {"type": "array", "items": "number", "required": True}}}}}}
        self.assertEqual([], schema_errors(schema, {"points": [{"xy": [0, 1.2]}]}))
        self.assertTrue(schema_errors(schema, {"points": [{"xy": [False]}]}))
        self.assertTrue(schema_errors(schema, {"points": [{}]}))

    def test_later_success_cannot_ground_an_earlier_final(self):
        case, witness = controller_case("read_success", 0, 0, 0)
        final = next(r for r in witness if r.get("action") == "final_response")
        final["t_ms"] = 110
        witness.sort(key=lambda r: r["t_ms"])
        result = evaluate_case(case, witness)
        self.assertFalse(result["passed"])
        self.assertIn("grounded_read", {r["id"] for r in result["failures"]})

    def test_error_status_and_wrong_api_cannot_ground_final(self):
        for mutation in ("error", "wrong_api"):
            case, witness = controller_case("read_success", 0, 0, 0)
            completed = next(r for r in witness if r["kind"] == "tool_completed")
            if mutation == "error":
                completed["status"] = "error"
            else:
                completed["api_name"] = "different_tool"
            self.assertFalse(evaluate_case(case, witness)["passed"])

    def test_corrupt_trace_is_a_failure_not_an_exception_or_pass(self):
        case, _ = controller_case("authorized_chain", 0, 0, 0)
        for bad in ([None], [{"kind": "action", "action": "tool_call", "call_id": []}],
                    [{"kind": "action", "action": "final_response", "payload": [], "state_snapshot": {}}]):
            self.assertFalse(evaluate_case(case, bad)["passed"])

    def test_changed_target_write_fails_even_with_genuine_result_id(self):
        case, witness = controller_case("one_grant_one_effect", 0, 0, 0)
        actual = next(r for r in witness if r.get("action") == "tool_call" and r["api_name"] == "book_flight")
        actual["args"]["flight_id"] = "FL-A7-2"
        self.assertFalse(evaluate_case(case, witness)["passed"])


if __name__ == "__main__":
    unittest.main()
