"""Offline smoke test for the public trace diagnostic."""

import json
import os
import unittest
from unittest.mock import patch

from scripts import replay_public_trace


class ReplayPublicTraceTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_case_keeps_three_attempt_traces_and_scores_without_credentials(self):
        secret = "synthetic-secret-for-report-test"

        class OfflineAgent:
            def __init__(self, in_q, out_q):
                self.in_q, self.out_q = in_q, out_q

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
        self.assertNotIn(secret, json.dumps(report))
        self.assertNotIn("ground_truth", report)


if __name__ == "__main__":
    unittest.main()
