import asyncio
import unittest

from participant.agent import ParticipantAgent


class BoundStringSourceAuthorityTests(unittest.TestCase):
    def dispatch(self, command, returned_mode):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": command}}]
        agent.revision = 1
        agent.operations["lookup"] = {
            "status": "success", "result": {"mode": returned_mode}, "revision": 1,
            "key": "lookup-key", "request_start": 0, "kind": "read_only",
        }
        agent.tools["set_mode"] = {
            "kind": "state_modifying",
            "description": "Set a mode for a customer.",
            "args": {"customer": {"type": "string"}, "mode": {"type": "string"}},
        }
        quote = command.rsplit("Set ", 1)[-1]
        quote = "Set " + quote
        agent._dispatch({
            "api_name": "set_mode",
            "args": {"customer": "Nia", "mode": returned_mode},
            "authorization": {"quote": quote, "message_index": 0},
            "result_bindings": {"mode": {"call_id": "lookup", "path": "mode"}},
        })
        return [agent.out_queue.get_nowait() for _ in range(agent.out_queue.qsize())]

    def test_result_cannot_override_adjective_before_mode(self):
        events = self.dispatch("Check Nia's profile. Set the low power mode for Nia.", "high power")

        self.assertEqual([event["action"] for event in events], ["clarification_request"])

    def test_exact_adjective_before_mode_match_is_allowed(self):
        events = self.dispatch("Check Nia's profile. Set the low power mode for Nia.", "low power")

        self.assertEqual([event["action"] for event in events], ["tool_call"])
        self.assertEqual(events[0]["payload"]["args"]["mode"], "low power")

    def test_unspecified_mode_can_still_be_delegated_to_the_selected_result(self):
        events = self.dispatch("Set mode based on the selected result for Nia.", "high power")

        self.assertEqual([event["action"] for event in events], ["tool_call"])
        self.assertEqual(events[0]["payload"]["args"]["mode"], "high power")

    def test_unrelated_selected_result_clause_does_not_delegate_the_mode(self):
        events = self.dispatch("Check the selected result. Set mode for Nia.", "high power")

        self.assertEqual([event["action"] for event in events], ["clarification_request"])


if __name__ == "__main__":
    unittest.main()
