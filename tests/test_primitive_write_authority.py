import asyncio
import unittest

from participant.agent import ParticipantAgent


class PrimitiveWriteAuthorityTests(unittest.TestCase):
    def agent(self, *texts):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": text}}
                          for text in texts]
        return agent

    def step(self, name, args, text, index=0, quote=None):
        return {"api_name": name, "args": args, "authorization": {
            "quote": text if quote is None else quote, "message_index": index}}

    def events(self, agent):
        result = []
        while not agent.out_queue.empty():
            result.append(agent.out_queue.get_nowait())
        return result

    def test_partial_quote_cannot_bind_a_number_to_the_wrong_field(self):
        text = "Set limit 2 and threshold 50 for Nia."
        agent = self.agent(text)
        agent.tools["set_threshold"] = {"kind": "state_modifying", "description": "Set a customer's threshold.",
                                         "args": {"threshold": {"type": "integer", "required": True},
                                                  "customer": {"type": "string", "required": True}}}

        agent._dispatch(self.step("set_threshold", {"threshold": 2, "customer": "Nia"}, text,
                                  quote="Set limit 2"))

        events = self.events(agent)
        self.assertEqual([event["action"] for event in events], ["clarification_request"])
        self.assertIn("threshold=2", events[0]["payload"]["text"])
        self.assertFalse(agent.operations)

    def test_partial_quote_cannot_bind_a_boolean_to_the_wrong_field(self):
        text = "Set alerts true and backup false for Nia."
        agent = self.agent(text)
        agent.tools["set_backup"] = {"kind": "state_modifying", "description": "Set a customer's backup flag.",
                                     "args": {"backup": {"type": "boolean", "required": True},
                                              "customer": {"type": "string", "required": True}}}

        agent._dispatch(self.step("set_backup", {"backup": True, "customer": "Nia"}, text,
                                  quote="Set alerts true"))

        events = self.events(agent)
        self.assertEqual([event["action"] for event in events], ["clarification_request"])
        self.assertIn("backup=true", events[0]["payload"]["text"])
        self.assertFalse(agent.operations)

    def test_swapped_nested_paths_are_rejected(self):
        text = "Set payment.amount to 2 and payment.tax to 50 for Nia."
        agent = self.agent(text)
        agent.tools["set_payment"] = {"kind": "state_modifying", "description": "Set payment values for a customer.",
                                      "args": {"payment": {"type": "object", "required": True,
                                                              "properties": {
                                                                  "amount": {"type": "integer", "required": True},
                                                                  "tax": {"type": "integer", "required": True}}},
                                               "customer": {"type": "string", "required": True}}}

        agent._dispatch(self.step("set_payment", {"payment": {"amount": 50, "tax": 2}, "customer": "Nia"}, text))

        events = self.events(agent)
        self.assertEqual([event["action"] for event in events], ["clarification_request"])
        self.assertIn("payment.amount=50, payment.tax=2", events[0]["payload"]["text"])
        self.assertFalse(agent.operations)

    def test_exact_two_field_values_dispatch_together(self):
        text = "Set limit 2 and threshold 50 for Nia."
        agent = self.agent(text)
        agent.tools["set_constraints"] = {"kind": "state_modifying", "description": "Set limits for a customer.",
                                          "args": {"limit": {"type": "integer", "required": True},
                                                   "threshold": {"type": "integer", "required": True},
                                                   "customer": {"type": "string", "required": True}}}

        agent._dispatch(self.step("set_constraints", {"limit": 2, "threshold": 50, "customer": "Nia"}, text))

        events = self.events(agent)
        self.assertEqual([event["action"] for event in events], ["tool_call"])
        self.assertEqual(events[0]["payload"]["args"], {"limit": 2, "threshold": 50, "customer": "Nia"})

    def test_exact_new_confirmation_turn_can_dispatch_the_named_proposal(self):
        first = "Set limit 2 and threshold 50 for Nia."
        corrected = "Set limit=50 and threshold=2 for Nia."
        agent = self.agent(first)
        agent.tools["set_constraints"] = {"kind": "state_modifying", "description": "Set limits for a customer.",
                                          "args": {"limit": {"type": "integer", "required": True},
                                                   "threshold": {"type": "integer", "required": True},
                                                   "customer": {"type": "string", "required": True}}}

        agent._dispatch(self.step("set_constraints", {"limit": 50, "threshold": 2, "customer": "Nia"}, first))
        clarification = self.events(agent)
        self.assertEqual([event["action"] for event in clarification], ["clarification_request"])
        self.assertIn("limit=50, threshold=2", clarification[0]["payload"]["text"])

        agent.messages.append({"event_type": "user_speech_chunk", "payload": {"text": corrected}})
        agent._request_start = 1
        agent._awaiting_clarification = False
        agent._dispatch(self.step("set_constraints", {"limit": 50, "threshold": 2, "customer": "Nia"},
                                  corrected, index=1))

        events = self.events(agent)
        self.assertEqual([event["action"] for event in events], ["tool_call"])
        self.assertEqual(events[0]["payload"]["args"]["limit"], 50)
        self.assertEqual(events[0]["payload"]["args"]["threshold"], 2)

    def test_decimal_amount_is_bound_as_a_whole_number(self):
        text = "Set amount to 2.50 for Nia."
        agent = self.agent(text)
        agent.tools["set_amount"] = {"kind": "state_modifying", "description": "Set a customer's payment amount.",
                                      "args": {"amount": {"type": "number", "required": True},
                                               "customer": {"type": "string", "required": True}}}

        agent._dispatch(self.step("set_amount", {"amount": 2, "customer": "Nia"}, text,
                                  quote="Set amount to 2"))

        events = self.events(agent)
        self.assertEqual([event["action"] for event in events], ["clarification_request"])
        self.assertFalse(agent.operations)

    def test_exact_decimal_amount_is_allowed_with_ordinary_sentence_punctuation(self):
        text = "Set amount=2.5 for Nia."
        agent = self.agent(text)
        agent.tools["set_amount"] = {"kind": "state_modifying", "description": "Set a customer's payment amount.",
                                      "args": {"amount": {"type": "number", "required": True},
                                               "customer": {"type": "string", "required": True}}}

        agent._dispatch(self.step("set_amount", {"amount": 2.5, "customer": "Nia"}, text))

        events = self.events(agent)
        self.assertEqual([event["action"] for event in events], ["tool_call"])
        self.assertEqual(events[0]["payload"]["args"]["amount"], 2.5)

    def test_dotted_numeric_fields_are_not_sentence_boundaries(self):
        text = "Set payment.amount=2 and payment.tax=50 for Nia."
        agent = self.agent(text)
        agent.tools["set_payment"] = {"kind": "state_modifying", "description": "Set a customer's payment amount.",
                                       "args": {"payment": {"type": "object", "required": True,
                                                             "properties": {"amount": {"type": "number", "required": True},
                                                                            "tax": {"type": "number", "required": True}}},
                                                "customer": {"type": "string", "required": True}}}

        agent._dispatch(self.step("set_payment", {"payment": {"amount": 2, "tax": 50}, "customer": "Nia"}, text))

        events = self.events(agent)
        self.assertEqual([event["action"] for event in events], ["tool_call"])
        self.assertEqual(events[0]["payload"]["args"]["payment"], {"amount": 2, "tax": 50})

    def test_scientific_notation_amount_is_bound_as_a_whole_number(self):
        text = "Set amount=2.5e-3 for Nia."
        agent = self.agent(text)
        agent.tools["set_amount"] = {"kind": "state_modifying", "description": "Set a customer's payment amount.",
                                      "args": {"amount": {"type": "number", "required": True},
                                               "customer": {"type": "string", "required": True}}}

        agent._dispatch(self.step("set_amount", {"amount": 0.0025, "customer": "Nia"}, text))

        events = self.events(agent)
        self.assertEqual([event["action"] for event in events], ["tool_call"])
        self.assertEqual(events[0]["payload"]["args"]["amount"], 0.0025)

    def test_two_decimal_commands_cannot_borrow_a_value_across_sentences(self):
        text = "Set amount to 2.50 for Nia. Set amount to 3 for Nia."
        agent = self.agent(text)
        agent.tools["set_amount"] = {"kind": "state_modifying", "description": "Set a customer's payment amount.",
                                      "args": {"amount": {"type": "number", "required": True},
                                               "customer": {"type": "string", "required": True}}}

        agent._dispatch(self.step("set_amount", {"amount": 3, "customer": "Nia"}, text,
                                  quote="Set amount to 2.50 for Nia"))

        events = self.events(agent)
        self.assertEqual([event["action"] for event in events], ["clarification_request"])
        self.assertFalse(agent.operations)


if __name__ == "__main__":
    unittest.main()
