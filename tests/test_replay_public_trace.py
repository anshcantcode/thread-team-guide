"""Offline smoke test for the public trace diagnostic."""

import hashlib
import json
import os
import unittest
from unittest.mock import patch

from scripts import replay_public_trace


class ReplayPublicTraceTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_case_keeps_three_attempt_traces_and_scores_without_credentials(self):
        secret = "synthetic-secret-for-report-test"

        class OfflinePlanner:
            model = "gemini-offline-test"
            audio_mode = "single_call_reads"

        class OfflineAgent:
            def __init__(self, in_q, out_q):
                self.in_q, self.out_q = in_q, out_q
                self.planner = OfflinePlanner()

            async def run(self):
                while True:
                    event = await self.in_q.get()
                    if event.get("event_type") == "user_speech_chunk":
                        await self.out_q.put({
                            "action": "final_response",
                            "payload": {"text": f"I can help. {secret}"},
                            "state_snapshot": {"intent": "help", "slots": {}},
                        })

        actual_harness = replay_public_trace.EvaluationHarness

        def fast_harness(*args, **kwargs):
            # Keep a short tail so the harness can consume the final action.
            return actual_harness(*args, tail_ms=200, **kwargs)

        with patch.object(replay_public_trace, "EvaluationHarness", side_effect=fast_harness), \
                patch.dict(os.environ, {"THREAD_API_KEY": secret}):
            # The official harness default tail is six virtual seconds; shorten
            # only that test delay while exercising the same harness and scorer.
            report = await replay_public_trace.replay_public_scenario(
                "pub_04_text_no_tool",
                agent_factory=lambda in_q, out_q: OfflineAgent(in_q, out_q),
            )

        self.assertEqual(report["repetitions"], 3)
        self.assertEqual(report["time_scale"], 1.0)
        self.assertEqual(len(report["attempts"]), 3)
        for attempt in report["attempts"]:
            self.assertGreater(attempt["score"]["total"], 0)
            self.assertTrue(any(row.get("action") == "final_response" for row in attempt["trace"]))
            self.assertTrue(all("t_ms" in row for row in attempt["trace"]))
            self.assertEqual(attempt["planner_records"], [])
            self.assertEqual(attempt["participant_runtime"], {
                "model": "gemini-offline-test", "audio_mode": "single_call_reads",
            })
        self.assertNotIn(secret, json.dumps(report))
        self.assertNotIn("ground_truth", report)

        identity = report["identity"]
        participant_modules = identity["participant_runtime_modules"]
        evaluator_modules = identity["official_evaluator"]["modules"]
        participant_by_import = {row["import_path"]: row for row in participant_modules}
        evaluator_by_import = {row["import_path"]: row for row in evaluator_modules}
        self.assertEqual(participant_by_import["participant.agent"]["path"], "participant/agent.py")
        self.assertEqual(evaluator_by_import["harness.runner"]["path"],
                         "theme5_kit/participant-kit/participant-kit/harness/runner.py")
        self.assertEqual(evaluator_by_import["harness.scorer"]["path"],
                         "theme5_kit/participant-kit/participant-kit/harness/scorer.py")
        for module in [*participant_modules, *evaluator_modules]:
            source = replay_public_trace.ROOT / module["path"]
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), module["sha256"])

        scenario_path = replay_public_trace.ROOT / identity["scenario"]["path"]
        scenario_bytes = scenario_path.read_bytes()
        self.assertEqual(hashlib.sha256(scenario_bytes).hexdigest(), identity["scenario"]["sha256"])
        self.assertEqual(identity["scenario"]["sha256"], report["scenario_sha256"])
        tool_manifest = json.loads(scenario_bytes).get("tool_manifest", {})
        manifest_bytes = json.dumps(tool_manifest, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")
        self.assertEqual(hashlib.sha256(manifest_bytes).hexdigest(),
                         identity["scenario_tool_manifest"]["sha256"])


if __name__ == "__main__":
    unittest.main()
