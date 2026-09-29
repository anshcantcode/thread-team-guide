"""Spoken-spelling identifiers in writes: compact representation, never new authority."""
from copy import deepcopy
import unittest

from jsonschema import Draft202012Validator
from participant.authorization import truncated_identifier
from thread_agent.fdb3 import heard_identifier, normalize_write_identifiers, proposal_schema

TOOLS = {"add_to_cart": {"kind": "state_modifying", "args": {
    "product_id": {"type": "string", "required": True, "description": "ID of the product"},
    "quantity": {"type": "integer", "required": False, "default": 1}}},
    "search_products": {"kind": "read_only", "args": {"query": {"type": "string", "required": True}}}}


def context(text):
    return {"tools": TOOLS, "current_turn_start": 0,
            "messages": [{"event_type": "user_speech_chunk", "payload": {"text": text}}]}


def decision(product):
    return {"intent": "add", "slots": {}, "tool_calls": [{"api_name": "add_to_cart",
            "args": {"product_id": product, "quantity": 2}, "authorization": {"clauses": ["0.0"]}}]}


class WriteIdentifierTests(unittest.TestCase):
    def normalized(self, text, product):
        return normalize_write_identifiers(decision(product), context(text))["tool_calls"][0]["args"]["product_id"]

    def test_complete_spoken_spelling_is_compacted(self):
        self.assertEqual(self.normalized("Add product M four to my cart. Two of them, please.", "m four"), "M4")
        self.assertEqual(self.normalized("Add item R Q seven four to my cart.", "R, Q, 7, 4"), "RQ74")

    def test_partial_literal_or_unspoken_spellings_are_untouched(self):
        self.assertEqual(self.normalized("Add product M four five to my cart.", "m four"), "m four")
        self.assertEqual(self.normalized("Add product M four exactly as spelled.", "m four"), "m four")
        self.assertEqual(self.normalized("Add the blue lamp to my cart.", "blue lamp"), "blue lamp")
        self.assertEqual(self.normalized("Add product M four to my cart.", "M4"), "M4")

    def test_truncated_spoken_spelling_is_rejected_by_the_gate(self):
        self.assertTrue(truncated_identifier("m four", "add product m four five to my cart"))
        self.assertFalse(truncated_identifier("m four", "add product m four to my cart"))

    def test_reads_are_compacted_only_when_enabled(self):
        step = {"intent": "t", "slots": {}, "tool_calls": [{"api_name": "track_order", "args": {"order_id": "n eight"}}]}
        tools = dict(TOOLS, track_order={"kind": "read_only", "args": {"order_id": {"type": "string"}}})
        ctx = dict(context("Track order N eight please."), tools=tools)
        self.assertEqual(normalize_write_identifiers(deepcopy(step), ctx)["tool_calls"][0]["args"]["order_id"], "n eight")
        self.assertEqual(normalize_write_identifiers(deepcopy(step), ctx, include_reads=True)["tool_calls"][0]["args"]["order_id"], "N8")

    def test_reads_are_not_touched_by_the_write_normalizer(self):
        step = {"intent": "s", "slots": {}, "tool_calls": [{"api_name": "search_products", "args": {"query": "m four"}}]}
        self.assertEqual(normalize_write_identifiers(deepcopy(step), context("Search for M four.")), step)


class HeardIdentifierTests(unittest.TestCase):
    def test_heard_spelling_sets_compaction_and_case(self):
        self.assertEqual(heard_identifier("77xq", "my code is 7 7 XQ please"), "77XQ")
        self.assertEqual(heard_identifier("M-A-X-4", "look up M-A-X-4 for me"), "MAX4")
        self.assertEqual(heard_identifier("RQ74", "track order RQ74"), "RQ74")

    def test_dictated_punctuation_and_truncation_are_left_alone(self):
        self.assertIsNone(heard_identifier("A-B-C", "the code is A dash B dash C"))
        self.assertIsNone(heard_identifier("Q3", "item Q 3 7 please"))
        self.assertIsNone(heard_identifier("blue lamp", "the blue lamp"))


class DeliveredBindingSchemaTests(unittest.TestCase):
    def valid(self, schema, step):
        return Draft202012Validator(schema).is_valid({"intent": "x", "slots": {}, "tool_calls": [step]})

    def test_result_bindings_only_name_delivered_successes(self):
        step = {"api_name": "search_products", "args": {}, "response_template": "x",
                "result_bindings": {"query": {"call_id": "call-1", "path": "products.0.name"}}}
        self.assertFalse(self.valid(proposal_schema(TOOLS, clause_ids=["0.0"], result_call_ids=[]), step))
        self.assertTrue(self.valid(proposal_schema(TOOLS, clause_ids=["0.0"], result_call_ids=["call-1"]), step))
        step["result_bindings"]["query"]["call_id"] = "search_products"
        self.assertFalse(self.valid(proposal_schema(TOOLS, clause_ids=["0.0"], result_call_ids=["call-1"]), step))


if __name__ == "__main__":
    unittest.main()
