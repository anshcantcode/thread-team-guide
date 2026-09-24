import asyncio
import unittest

from participant.agent import ParticipantAgent


class WriteNumericBindingTests(unittest.TestCase):
    def agent(self, text):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": text}}]
        return agent

    def step(self, agent, bindings=None):
        return {"authorization": {"quote": agent.messages[0]["payload"]["text"]},
                "result_bindings": bindings or {}}

    def test_supplied_quantity_two_does_not_authorize_default_enum_2000(self):
        agent = self.agent("Hold 2 units of ITEM-82 for Nia.")
        tool = {"kind": "state_modifying", "description": "Hold inventory for a customer.", "args": {
            "item": {"type": "string"}, "customer": {"type": "string"},
            "quantity": {"type": "integer", "enum": [2000], "default": 2000}}}
        args = {"item": "ITEM-82", "customer": "Nia", "quantity": 2000}

        self.assertIn("quantity", agent._binding_error(self.step(agent), tool, args))

    def test_nested_amount_requires_its_exact_numeric_literal(self):
        agent = self.agent("Charge 50 for Nia.")
        tool = {"kind": "state_modifying", "description": "Charge a customer.", "args": {
            "payment": {"type": "object", "properties": {
                "amount": {"type": "integer", "required": True},
                "customer": {"type": "string", "required": True}}}}}
        args = {"payment": {"amount": 5000, "customer": "Nia"}}

        self.assertIn("payment.amount", agent._binding_error(self.step(agent), tool, args))

    def test_boolean_value_cannot_contradict_explicit_instruction_or_use_default(self):
        agent = self.agent("Set alerts to true for Nia.")
        tool = {"kind": "state_modifying", "description": "Set notification alerts.", "args": {
            "customer": {"type": "string"},
            "enabled": {"type": "boolean", "enum": [False], "default": False}}}
        args = {"customer": "Nia", "enabled": False}

        self.assertIn("enabled", agent._binding_error(self.step(agent), tool, args))

    def test_exact_explicit_quantity_is_allowed(self):
        agent = self.agent("Hold 2 units of ITEM-82 for Nia.")
        tool = {"kind": "state_modifying", "description": "Hold inventory for a customer.", "args": {
            "item": {"type": "string"}, "customer": {"type": "string"},
            "quantity": {"type": "integer", "default": 2000}}}
        args = {"item": "ITEM-82", "customer": "Nia", "quantity": 2}

        self.assertEqual(agent._binding_error(self.step(agent), tool, args), "")

    def test_verified_result_binding_supplies_numeric_value(self):
        agent = self.agent("Hold the available quantity of ITEM-82 for Nia.")
        agent.revision = 3
        agent.operations = {"lookup-1": {"status": "success", "result": {"quantity": 2000}, "revision": 3}}
        tool = {"kind": "state_modifying", "description": "Hold inventory for a customer.", "args": {
            "item": {"type": "string"}, "customer": {"type": "string"},
            "quantity": {"type": "integer", "required": True}}}
        step = self.step(agent, {"quantity": {"call_id": "lookup-1", "path": "quantity"}})
        args = {"item": "ITEM-82", "customer": "Nia", "quantity": 2000}

        self.assertEqual(agent._binding_error(step, tool, args), "")

    def test_exact_boolean_literal_is_allowed(self):
        agent = self.agent("Set alerts to false for Nia.")
        tool = {"kind": "state_modifying", "description": "Set notification alerts.", "args": {
            "customer": {"type": "string"}, "enabled": {"type": "boolean"}}}
        args = {"customer": "Nia", "enabled": False}

        self.assertEqual(agent._binding_error(self.step(agent), tool, args), "")


if __name__ == "__main__":
    unittest.main()
