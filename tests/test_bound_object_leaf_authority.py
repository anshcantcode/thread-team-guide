import asyncio
import unittest

from participant.agent import ParticipantAgent


class BoundObjectLeafAuthorityTests(unittest.TestCase):
    def dispatch(self, command):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": command}}]
        agent.revision = 1
        agent.operations["lookup"] = {
            "kind": "read_only", "status": "success", "revision": 1, "key": "lookup-key",
            "result": {"settings": {"limit": 2000, "enabled": False, "mode": "dangerous"}},
        }
        agent.tools["set_settings"] = {
            "kind": "state_modifying", "description": "Set settings for a customer.", "args": {
                "settings": {"type": "object", "required": True, "properties": {
                    "limit": {"type": "integer", "required": True},
                    "enabled": {"type": "boolean", "required": True},
                    "mode": {"type": "string", "required": True},
                }},
                "customer": {"type": "string", "required": True},
            },
        }
        agent._dispatch({
            "api_name": "set_settings",
            "args": {"settings": {"limit": 2000, "enabled": False, "mode": "dangerous"}, "customer": "Nia"},
            "authorization": {"quote": command, "message_index": 0},
            "result_bindings": {"settings": {"call_id": "lookup", "path": "settings"}},
        })
        events = [agent.out_queue.get_nowait() for _ in range(agent.out_queue.qsize())]
        return agent, events

    def test_bound_object_cannot_override_explicit_numeric_and_boolean_leaves(self):
        _, events = self.dispatch("Set settings.limit=2 and settings.enabled=true for Nia.")

        self.assertEqual([event["action"] for event in events], ["clarification_request"])

    def test_bound_object_cannot_override_an_explicit_string_leaf(self):
        _, events = self.dispatch("Set settings.mode=safe for Nia.")

        self.assertEqual([event["action"] for event in events], ["clarification_request"])

    def test_exact_matching_returned_object_is_allowed(self):
        _, events = self.dispatch("Set settings.limit=2000 and settings.enabled=false and settings.mode=dangerous for Nia.")

        self.assertEqual([event["action"] for event in events], ["tool_call"])

    def test_selected_result_object_is_allowed_when_leaves_are_unspecified(self):
        _, events = self.dispatch("Set the selected result for Nia.")

        self.assertEqual([event["action"] for event in events], ["tool_call"])


if __name__ == "__main__":
    unittest.main()
