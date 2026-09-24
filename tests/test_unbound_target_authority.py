import asyncio
import unittest

from participant.agent import ParticipantAgent


class UnboundTargetAuthorityTests(unittest.TestCase):
    def dispatch(self, text, quote, customer, mode):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": text}}]
        agent.tools["set_mode"] = {
            "kind": "state_modifying",
            "description": "Set a mode for a customer.",
            "args": {"customer": {"type": "string"}, "mode": {"type": "string"}},
        }
        agent._dispatch({
            "api_name": "set_mode",
            "args": {"customer": customer, "mode": mode},
            "authorization": {"quote": quote, "message_index": 0},
        })
        return [agent.out_queue.get_nowait() for _ in range(agent.out_queue.qsize())]

    def test_target_from_an_unrelated_clause_cannot_be_borrowed(self):
        events = self.dispatch(
            "Set mode safe for Nia and tell Omar about it.",
            "Set mode safe for Nia", "Omar", "safe")

        self.assertEqual([event["action"] for event in events], ["clarification_request"])
        self.assertIn("customer", events[0]["payload"]["text"])

    def test_first_clause_target_and_mode_still_dispatch(self):
        events = self.dispatch(
            "Set mode safe for Nia and tell Omar about it.",
            "Set mode safe for Nia and tell Omar about it.", "Nia", "safe")

        self.assertEqual([event["action"] for event in events], ["tool_call"])
        self.assertEqual(events[0]["payload"]["args"], {"customer": "Nia", "mode": "safe"})

    def test_compound_string_value_in_the_authorized_clause_still_dispatches(self):
        events = self.dispatch(
            "Set mode quiet and safe for Nia and tell Omar about it.",
            "Set mode quiet and safe for Nia and tell Omar about it.", "Nia", "quiet and safe")

        self.assertEqual([event["action"] for event in events], ["tool_call"])
        self.assertEqual(events[0]["payload"]["args"]["mode"], "quiet and safe")

    def test_full_quote_does_not_authorize_a_target_from_a_coordinated_clause(self):
        text = "Set mode safe for Nia and tell Omar about it."
        events = self.dispatch(text, text, "Omar", "safe")

        self.assertEqual([event["action"] for event in events], ["clarification_request"])
        self.assertIn("customer", events[0]["payload"]["text"])


if __name__ == "__main__":
    unittest.main()
