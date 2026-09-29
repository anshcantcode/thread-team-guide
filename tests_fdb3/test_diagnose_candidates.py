"""Candidate root-cause localization is evidence-labelled, never a verdict."""
import unittest

from scripts.fdb3_diagnose_layers import MODES, mode_candidates, paired_candidates


def clarification(text):
    return {"rejections_and_clarifications": [{"action": "clarification_request", "payload": {"text": text}}]}


class CandidateTests(unittest.TestCase):
    def test_cross_mode_localizes_recognition_and_streaming_losses(self):
        modes = {"text": {"status": "completed", "strict_pass": True},
                 "asr_text": {"status": "completed", "strict_pass": False},
                 "live_audio": {"status": "completed", "strict_pass": False}}
        report = paired_candidates(modes, {})
        self.assertEqual([row["layer"] for row in report["cross_mode"]], ["recognition"])
        modes["asr_text"]["strict_pass"] = True
        report = paired_candidates(modes, {})
        self.assertEqual([row["layer"] for row in report["cross_mode"]], ["fragment_admission|transport|synthesis_output"])
        self.assertIn("review required", report["status"])

    def test_within_mode_evidence_maps_to_layers(self):
        self.assertEqual([row["layer"] for row in mode_candidates(clarification(
            "Please explicitly confirm the action and its target before I change anything."))],
            ["authorization_false_rejection"])
        self.assertEqual([row["layer"] for row in mode_candidates(clarification(
            "I need valid details before acting: args.quantity: expected 'integer'"))], ["planner_schema"])
        self.assertEqual([row["layer"] for row in mode_candidates({"voice_admission_events": [
            {"event": "speech_segment_recognition", "delivery": "stale_dropped"}]})], ["fragment_admission"])
        self.assertEqual(mode_candidates({"voice_admission_events": [
            {"event": "speech_segment_recognition", "delivery": "stale_context"}]}), [])

    def test_passing_modes_have_no_candidates(self):
        modes = {mode: {"status": "completed", "strict_pass": True} for mode in MODES}
        self.assertEqual(paired_candidates(modes, {})["within_mode"], {})


if __name__ == "__main__":
    unittest.main()
