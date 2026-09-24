import asyncio
import unittest

from participant.agent import ParticipantAgent


class WriteStringBindingTests(unittest.TestCase):
    def agent(self, text):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": text}}]
        return agent

    def dispatch(self, agent, name, args, text, tool):
        agent.tools[name] = tool
        agent._dispatch({"api_name": name, "args": args, "authorization": {
            "quote": text, "message_index": 0}})
        return [agent.out_queue.get_nowait() for _ in range(agent.out_queue.qsize())]

    def test_target_cannot_be_borrowed_from_a_later_clause(self):
        text = "Set limit=2 for Nia. Tell Omar about it."
        agent = self.agent(text)
        events = self.dispatch(agent, "set_limit", {"limit": 2, "customer": "Omar"},
                               "Set limit=2 for Nia", {
            "kind": "state_modifying", "description": "Set a limit for a customer.", "args": {
                "limit": {"type": "integer"}, "customer": {"type": "string"}}})

        self.assertEqual([event["action"] for event in events], ["clarification_request"])
        self.assertIn("customer", events[0]["payload"]["text"])
        self.assertFalse(agent.operations)

    def test_enum_default_cannot_override_the_commanded_string(self):
        text = "Set mode safe for Nia."
        agent = self.agent(text)
        events = self.dispatch(agent, "set_mode", {"mode": "dangerous", "customer": "Nia"}, text, {
            "kind": "state_modifying", "description": "Set a mode for a customer.", "args": {
                "mode": {"type": "string", "enum": ["safe", "dangerous"], "default": "dangerous"},
                "customer": {"type": "string"}}})

        self.assertEqual([event["action"] for event in events], ["clarification_request"])
        self.assertIn("mode", events[0]["payload"]["text"])
        self.assertFalse(agent.operations)

    def test_explicit_enum_value_overrides_a_different_schema_default(self):
        text = "Set mode safe for Nia."
        agent = self.agent(text)
        events = self.dispatch(agent, "set_mode", {"mode": "safe", "customer": "Nia"}, text, {
            "kind": "state_modifying", "description": "Set a mode for a customer.", "args": {
                "mode": {"type": "string", "enum": ["safe", "dangerous"], "default": "dangerous"},
                "customer": {"type": "string"}}})

        self.assertEqual([event["action"] for event in events], ["tool_call"])
        self.assertEqual(events[0]["payload"]["args"]["mode"], "safe")

    def test_current_successful_result_can_supply_an_unmentioned_string(self):
        agent = self.agent("Update the selected record for Nia.")
        agent.revision = 1
        agent.operations["lookup-1"] = {
            "status": "success", "result": {"id": "record-7"}, "revision": 1}
        tool = {"kind": "state_modifying", "args": {
            "record_id": {"type": "string", "description": "Returned record identifier."}}}
        step = {"result_bindings": {"record_id": {"call_id": "lookup-1", "path": "id"}}}

        self.assertEqual(agent._binding_error(step, tool, {"record_id": "record-7"},
                                             "update the selected record for nia"), "")

    def test_descriptive_free_text_remains_allowed(self):
        agent = self.agent("Set limit=2 for Nia. Add the note: birthday surprise.")
        tool = {"kind": "state_modifying", "args": {
            "note": {"type": "string", "description": "Free text note to include."}}}
        step = {"result_bindings": {}}

        self.assertEqual(agent._binding_error(step, tool, {"note": "birthday surprise"},
                                             "set limit=2 for nia"), "")


if __name__ == "__main__":
    unittest.main()
