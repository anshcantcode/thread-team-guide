import asyncio
import unittest

from participant.agent import ParticipantAgent


class WriteSettingClauseAuthorityTests(unittest.TestCase):
    def dispatch(self, text, mode):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": text}}]
        agent.tools["set_mode"] = {
            "kind": "state_modifying",
            "description": "Set a mode for a customer.",
            "args": {
                "mode": {"type": "string", "required": True, "description": "Operational mode."},
                "customer": {"type": "string", "required": True},
            },
        }
        agent._dispatch({
            "api_name": "set_mode",
            "args": {"mode": mode, "customer": "Nia"},
            "authorization": {"quote": text, "message_index": 0},
        })
        events = [agent.out_queue.get_nowait() for _ in range(agent.out_queue.qsize())]
        return agent, events

    def test_value_from_explanatory_clause_cannot_override_setting(self):
        agent, events = self.dispatch(
            "Set mode safe for Nia and explain dangerous mode.", "dangerous")

        self.assertEqual([event["action"] for event in events], ["clarification_request"])
        self.assertFalse(agent.operations)

    def test_explicit_setting_value_still_dispatches(self):
        _, events = self.dispatch("Set mode safe for Nia.", "safe")

        self.assertEqual([event["action"] for event in events], ["tool_call"])
        self.assertEqual(events[0]["payload"]["args"]["mode"], "safe")

    def test_compound_setting_value_still_dispatches(self):
        _, events = self.dispatch("Set mode quiet and safe for Nia.", "quiet and safe")

        self.assertEqual([event["action"] for event in events], ["tool_call"])
        self.assertEqual(events[0]["payload"]["args"]["mode"], "quiet and safe")


if __name__ == "__main__":
    unittest.main()
