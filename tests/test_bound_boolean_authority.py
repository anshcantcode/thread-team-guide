import asyncio
import unittest

from participant.agent import ParticipantAgent


class BoundBooleanAuthorityTests(unittest.TestCase):
    def binding_error(self, command, returned_value):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": command}}]
        agent.revision = 1
        agent.operations = {"lookup": {"status": "success", "result": {"enabled": returned_value},
                                         "revision": 1}}
        step = {"result_bindings": {"enabled": {"call_id": "lookup", "path": "enabled"}}}
        tool = {"kind": "state_modifying", "args": {"enabled": {"type": "boolean"}}}
        return agent._binding_error(step, tool, {"enabled": returned_value}, command)

    def test_result_boolean_cannot_override_an_explicit_conflicting_choice(self):
        error = self.binding_error("Set enabled to true for Nia.", False)

        self.assertIn("explicit user value", error)

    def test_exact_explicit_boolean_choice_matches_the_result(self):
        error = self.binding_error("Set enabled to false for Nia.", False)

        self.assertEqual(error, "")

    def test_returned_boolean_can_supply_an_unspecified_choice(self):
        error = self.binding_error("Use the lookup result to set enabled for Nia.", False)

        self.assertEqual(error, "")


if __name__ == "__main__":
    unittest.main()
