import asyncio
import unittest

from participant.agent import ParticipantAgent


class BoundContainerLeafScopeTests(unittest.TestCase):
    def dispatch(self, command, settings, settings_schema):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": command}}]
        agent.revision = 1
        agent.operations["lookup"] = {
            "kind": "read_only", "status": "success", "revision": 1,
            "key": "lookup-key", "result": {"settings": settings},
        }
        agent.tools["set_settings"] = {
            "kind": "state_modifying", "description": "Set settings for a customer.", "args": {
                "settings": settings_schema,
                "customer": {"type": "string", "required": True},
            },
        }
        agent._dispatch({
            "api_name": "set_settings", "args": {"settings": settings, "customer": "Nia"},
            "authorization": {"quote": command, "message_index": 0},
            "result_bindings": {"settings": {"call_id": "lookup", "path": "settings"}},
        })
        return [agent.out_queue.get_nowait() for _ in range(agent.out_queue.qsize())]

    def test_leaf_request_does_not_authorize_other_returned_object_fields(self):
        command = "Read the profile for Nia. Then Set settings.mode=safe for Nia."
        schema = {"type": "object", "properties": {
            "mode": {"type": "string"}, "limit": {"type": "integer"}, "enabled": {"type": "boolean"},
        }}
        events = self.dispatch(command, {"mode": "safe", "limit": 2000, "enabled": False}, schema)

        self.assertEqual([event["action"] for event in events], ["clarification_request"])

    def test_mode_only_bound_object_is_allowed(self):
        command = "Read the profile for Nia. Then Set settings.mode=safe for Nia."
        schema = {"type": "object", "properties": {"mode": {"type": "string"}}}
        events = self.dispatch(command, {"mode": "safe"}, schema)

        self.assertEqual([event["action"] for event in events], ["tool_call"])

    def test_explicit_whole_result_delegation_allows_all_object_leaves(self):
        schema = {"type": "object", "properties": {
            "mode": {"type": "string"}, "limit": {"type": "integer"}, "enabled": {"type": "boolean"},
        }}
        events = self.dispatch("Set the selected result for Nia.",
                               {"mode": "safe", "limit": 2000, "enabled": False}, schema)

        self.assertEqual([event["action"] for event in events], ["tool_call"])

    def test_indexed_leaf_request_does_not_authorize_other_array_elements(self):
        schema = {"type": "object", "properties": {"rules": {
            "type": "array", "items": {"type": "object", "properties": {"limit": {"type": "integer"}}},
        }}}
        events = self.dispatch("Set settings.rules[0].limit=2 for Nia.",
                               {"rules": [{"limit": 2}, {"limit": 2000}]}, schema)

        self.assertEqual([event["action"] for event in events], ["clarification_request"])

    def test_explicitly_authorized_array_indices_are_allowed(self):
        schema = {"type": "object", "properties": {"rules": {
            "type": "array", "items": {"type": "object", "properties": {"limit": {"type": "integer"}}},
        }}}
        events = self.dispatch("Set settings.rules[0].limit=2 and settings.rules[1].limit=2000 for Nia.",
                               {"rules": [{"limit": 2}, {"limit": 2000}]}, schema)

        self.assertEqual([event["action"] for event in events], ["tool_call"])


if __name__ == "__main__":
    unittest.main()
