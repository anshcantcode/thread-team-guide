import asyncio
import unittest

from participant.agent import ParticipantAgent


class BoundStringAuthorityTests(unittest.TestCase):
    def agent(self, command, result, bindings):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": command}}]
        agent.revision = 1
        agent.operations = {"lookup": {"status": "success", "result": result, "revision": 1,
                                         "key": "read-key", "request_start": 0, "kind": "read_only"}}
        step = {"result_bindings": bindings}
        return agent, step

    def test_bound_customer_and_mode_cannot_override_explicit_target_and_value(self):
        command = "Set mode safe for Nia."
        bindings = {
            "customer": {"call_id": "lookup", "path": "customer"},
            "mode": {"call_id": "lookup", "path": "mode"},
        }
        agent, step = self.agent(command, {"customer": "Omar", "mode": "dangerous"}, bindings)
        tool = {"kind": "state_modifying", "args": {
            "customer": {"type": "string"}, "mode": {"type": "string"}}}

        agent.tools["set_mode"] = {**tool, "description": "Set a mode for a customer."}
        step.update({"api_name": "set_mode", "args": {"customer": "Omar", "mode": "dangerous"},
                     "authorization": {"quote": command, "message_index": 0}})
        agent._dispatch(step)
        actions = [agent.out_queue.get_nowait()["action"] for _ in range(agent.out_queue.qsize())]

        self.assertEqual(actions, ["clarification_request"])
        self.assertFalse(any(op.get("kind") == "state_modifying" for op in agent.operations.values()))

    def test_matching_explicit_string_target_and_value_are_allowed(self):
        command = "Set mode safe for Nia."
        bindings = {
            "customer": {"call_id": "lookup", "path": "customer"},
            "mode": {"call_id": "lookup", "path": "mode"},
        }
        agent, step = self.agent(command, {"customer": "Nia", "mode": "safe"}, bindings)
        tool = {"kind": "state_modifying", "args": {
            "customer": {"type": "string"}, "mode": {"type": "string"}}}

        self.assertEqual(agent._binding_error(step, tool, {"customer": "Nia", "mode": "safe"}, command), "")

    def test_bound_target_cannot_override_the_explicit_customer(self):
        command = "Set mode safe for Nia."
        bindings = {"customer": {"call_id": "lookup", "path": "customer"}}
        agent, step = self.agent(command, {"customer": "Omar"}, bindings)
        tool = {"kind": "state_modifying", "args": {"customer": {"type": "string"}}}

        self.assertIn("explicit user value", agent._binding_error(
            step, tool, {"customer": "Omar"}, command))

    def test_bound_value_cannot_override_an_explicit_mode(self):
        command = "Set mode safe for Nia."
        bindings = {"mode": {"call_id": "lookup", "path": "mode"}}
        agent, step = self.agent(command, {"mode": "dangerous"}, bindings)
        tool = {"kind": "state_modifying", "args": {"mode": {"type": "string"}}}

        self.assertIn("explicit user value", agent._binding_error(
            step, tool, {"mode": "dangerous"}, command))

    def test_selected_result_identifier_is_allowed_when_not_named_by_command(self):
        command = "Dispatch the selected option to Nia."
        bindings = {"choice_id": {"call_id": "lookup", "path": "offers.0.id"}}
        agent, step = self.agent(command, {"offers": [{"id": "express-4"}]}, bindings)
        tool = {"kind": "state_modifying", "args": {
            "choice_id": {"type": "string", "description": "Returned offer identifier."}}}

        self.assertEqual(agent._binding_error(step, tool, {"choice_id": "express-4"}, command), "")

    def test_named_field_can_still_be_supplied_by_a_result_when_its_value_is_unspecified(self):
        command = "Set mode based on the selected result for Nia."
        bindings = {"mode": {"call_id": "lookup", "path": "mode"}}
        agent, step = self.agent(command, {"mode": "safe"}, bindings)
        tool = {"kind": "state_modifying", "args": {"mode": {"type": "string"}}}

        self.assertEqual(agent._binding_error(step, tool, {"mode": "safe"}, command), "")


if __name__ == "__main__":
    unittest.main()
