import asyncio
import unittest
from unittest.mock import patch

from participant.agent import ParticipantAgent


class WriteExpiryContinuationTests(unittest.TestCase):
    def make_agent(self, delay_range_ms=(0, 10)):
        text = "Create a note saying hello. Then create another note saying extra."
        tool = {"kind": "state_modifying", "description": "Create a note.",
                "args": {"text": {"type": "string", "required": True}},
                "delay_range_ms": list(delay_range_ms)}
        step = {"api_name": "create_note", "args": {"text": "hello"},
                "authorization": {"quote": "Create a note saying hello"},
                "after_result": {"api_name": "create_note", "args": {"text": "extra"},
                                 "authorization": {"quote": "create another note saying extra"}}}
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.tools = {"create_note": tool}
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": text}, "revision": 0}]
        with patch("participant.agent.time.monotonic", return_value=100):
            self.assertTrue(agent._dispatch(step))
        call = agent.out_queue.get_nowait()
        self.assertEqual(call["action"], "tool_call")
        return agent, call

    def expire_at(self, agent, deadline):
        with patch("participant.agent.time.monotonic", return_value=deadline):
            agent._expire_writes()

    def reconcile_late_success(self, agent, call):
        agent._result({"call_id": call["payload"]["call_id"], "api_name": "create_note",
                       "status": "success", "result": {"status": "success", "receipt_id": "LATE-42"}})

        operation = agent.operations[call["payload"]["call_id"]]
        self.assertEqual(operation["status"], "success")
        self.assertEqual(operation["result"]["receipt_id"], "LATE-42")
        self.assertEqual(agent.snapshot()["slots"]["receipt_id"], "LATE-42")
        self.assertEqual(len(agent.operations), 1)

    def test_expiry_retires_continuation_before_unknown_notice(self):
        agent, call = self.make_agent()
        deadline = agent.operations[call["payload"]["call_id"]]["deadline"]

        self.expire_at(agent, deadline)

        operation = agent.operations[call["payload"]["call_id"]]
        self.assertEqual(operation["status"], "unknown")
        self.assertTrue(operation["continuation_retired"])
        notice = agent.out_queue.get_nowait()
        self.assertEqual(notice["action"], "final_response")
        self.assertIn("could not confirm", notice["payload"]["text"])

        self.reconcile_late_success(agent, call)
        self.assertTrue(agent.out_queue.empty())

    def test_scenario_end_shortened_deadline_retires_continuation(self):
        agent, call = self.make_agent((30000, 30000))
        operation = agent.operations[call["payload"]["call_id"]]
        original_deadline = operation["deadline"]

        with patch("participant.agent.time.monotonic", return_value=100):
            agent._handle({"event_type": "scenario_end", "payload": {}})
        self.assertLess(operation["deadline"], original_deadline)
        self.expire_at(agent, operation["deadline"])
        notice = agent.out_queue.get_nowait()
        self.assertEqual(notice["action"], "final_response")
        self.assertEqual(operation["status"], "unknown")
        self.assertTrue(operation["continuation_retired"])

        self.reconcile_late_success(agent, call)
        self.assertTrue(agent.out_queue.empty())

    def test_late_success_after_ambiguous_error_stays_reconciled_only(self):
        agent, call = self.make_agent()
        agent._result({"call_id": call["payload"]["call_id"], "api_name": "create_note",
                       "status": "error", "result": {"status": "error", "error": "timeout"}})
        self.assertEqual(agent.operations[call["payload"]["call_id"]]["status"], "unknown")
        self.assertEqual(agent.out_queue.get_nowait()["action"], "final_response")

        self.reconcile_late_success(agent, call)
        self.assertTrue(agent.out_queue.empty())


if __name__ == "__main__":
    unittest.main()
