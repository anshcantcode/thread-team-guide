"""Authored scalar contracts, independent of benchmark scenarios and answers."""
from copy import deepcopy
import json
import tempfile
from pathlib import Path
import unittest

import httpx

from jsonschema import Draft202012Validator

from thread_agent.fdb3 import ControllerBridge, LocalPlanner, WRITES, argument_schema, load_contract, planner_view
from thread_agent.fdb3_values import mock_call_args, mock_scalar, normalize_mock_scalar_proposals


TOOLS = {"update_search_filter": {"kind": "state_modifying", "description": "Update a search filter",
         "args": {"filter_name": {"type": "string", "required": True},
                  "value": {"type": "string", "required": True, "fdb_mock_any": True}}}}


def proposal(value, text, filter_name="max_price"):
    return {"intent": "update_filter", "slots": {}, "tool_calls": [{"api_name": "update_search_filter",
            "args": {"filter_name": filter_name, "value": value}, "authorization": {"quote": text}}]}


def context(text):
    return {"tools": deepcopy(TOOLS), "current_turn_start": 0,
            "messages": [{"event_type": "user_speech_chunk", "payload": {"text": text}}]}


class MockScalarTests(unittest.TestCase):
    def test_whole_numbers_and_grouped_currency(self):
        for raw, expected in [("2700", 2700), ("2,700", 2700), ("$2700", 2700),
                              (" $2,700.00 ", 2700), ("-2,700", -2700), ("+27", 27),
                              ("0", 0), ("\u00a327", 27), ("\u20ac27", 27), ("\u20b927", 27)]:
            with self.subTest(raw=raw):
                result = mock_scalar(raw)
                self.assertEqual(result, expected)
                self.assertIs(type(result), int)

    def test_decimal_numbers(self):
        for raw, expected in [("$2,700.25", 2700.25), ("-0.75", -0.75), ("0.1", 0.1)]:
            with self.subTest(raw=raw):
                result = mock_scalar(raw)
                self.assertEqual(result, expected)
                self.assertIs(type(result), float)

    def test_boolean_spellings(self):
        for raw, expected in [("true", True), (" TRUE ", True), ("yes", True),
                              ("false", False), ("False", False), ("NO", False)]:
            with self.subTest(raw=raw):
                self.assertIs(mock_scalar(raw), expected)

    def test_ids_and_genuine_text_keep_exact_bytes(self):
        for raw in ("P0999", "XYZ88", "007", "027.5", "North ridge", " no pets ", "true story",
                    "2700 per month", "under $2700", "2-7", "2/7", "27%", "2,70", "2,700,5",
                    "NaN", "Infinity", "1e3", "", " ", "two thousand", "2026-10-04"):
            with self.subTest(raw=raw):
                self.assertEqual(mock_scalar(raw), raw)

    def test_compound_values_are_not_parsed_or_recursively_coerced(self):
        for raw in ('["27", "yes"]', '{"amount":"27"}', "27 and 35", "yes/no"):
            self.assertEqual(mock_scalar(raw), raw)
        for value in (["27", "yes", {"amount": "$2700"}], {"value": "27", "nested": ["false"]}):
            before = deepcopy(value)
            self.assertIs(mock_scalar(value), value)
            self.assertEqual(value, before)

    def test_native_values_and_null_are_unchanged(self):
        for value in (27, 2.75, True, False, None):
            self.assertIs(mock_scalar(value), value)

    def test_precision_is_not_silently_lost(self):
        raw = "0.12345678901234567890123456789"
        self.assertEqual(mock_scalar(raw), raw)
        self.assertEqual(mock_scalar("9" * 257), "9" * 257)


class MockAnyContractTests(unittest.TestCase):
    def contract(self, mock_annotation="Any"):
        # Twelve declaration-only functions satisfy the pinned loader's shape.
        # Importing either source would fail: loading must remain AST-only.
        names = sorted(WRITES) + [f"lookup_{n}" for n in range(7)]
        reference = "raise AssertionError('must not execute reference')\nclass AssistantFnc:\n"
        mock = "raise AssertionError('must not execute mock')\n"
        for name in names:
            reference += (f"    @declared(description='Authored tool')\n"
                          f"    async def {name}(self, value: str):\n        pass\n")
            annotation = mock_annotation if name == "update_search_filter" else "str"
            mock += f"def {name}(value: {annotation}, mock_only: str = 'x', **kwargs): pass\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cascaded_agent.py").write_text(reference, encoding="utf-8")
            (root / "mock_apis.py").write_text(mock, encoding="utf-8")
            return load_contract(root)

    def test_only_mock_any_enables_union(self):
        tools = self.contract()
        for name, tool in tools.items():
            spec = tool["args"]["value"]
            self.assertEqual(spec.get("fdb_mock_any", False), name == "update_search_filter")
            self.assertEqual(set(tool["args"]), {"value"})
        self.assertTrue(self.contract("typing.Any")["update_search_filter"]["args"]["value"]["fdb_mock_any"])

    def test_reference_string_stays_string_without_any(self):
        spec = self.contract("str")["update_search_filter"]["args"]["value"]
        self.assertEqual(argument_schema(spec), {"type": "string"})

    def test_planner_scalar_union_excludes_compounds_and_null(self):
        spec = self.contract()["update_search_filter"]["args"]["value"]
        validator = Draft202012Validator(argument_schema(spec))
        for value in ("text", "P0999", "XYZ88", 2700, 2.75, True, False):
            self.assertTrue(validator.is_valid(value), value)
        for value in (None, [], {}, ["2700"], {"value": "true"}):
            self.assertFalse(validator.is_valid(value), value)

    def test_planner_context_and_grammar_both_describe_the_union_without_mutating_controller(self):
        original = context("Update a filter")
        before = deepcopy(original)
        spec = planner_view(original)["tools"]["update_search_filter"]["args"]["value"]
        self.assertEqual(spec["type"], ["string", "number", "boolean"])
        self.assertEqual(argument_schema(spec), {"type": ["string", "number", "boolean"]})
        self.assertEqual(original, before)


class MockScalarDispatchTests(unittest.TestCase):
    def dispatched(self, text, value, filter_name="max_price"):
        class Registry:
            def __init__(self):
                self.calls = []

            def call(self, name, **args):
                self.calls.append((name, deepcopy(args)))
                return {"status": "success", "new_value": args["value"]}

        bridge = ControllerBridge(deepcopy(TOOLS), Registry(), None)
        bridge.controller.tools = deepcopy(TOOLS)
        bridge.controller.messages = context(text)["messages"]
        decision = normalize_mock_scalar_proposals(proposal(value, text, filter_name), context(text))
        bridge.controller._apply(decision)
        admitted = []
        while not bridge.outgoing.empty():
            event = bridge.outgoing.get_nowait()
            if event["action"] == "tool_call":
                admitted.append(deepcopy(event["payload"]))
                bridge._invoke(event["payload"], bridge.controller.revision)
        return bridge, admitted

    def test_checked_value_is_preserved_and_backend_and_journal_get_number(self):
        for value in ("$2,700", "2,700", "2700", 2700, 2700.0):
            with self.subTest(value=value):
                text = "Update my max price filter to $2,700"
                bridge, admitted = self.dispatched(text, value)
                self.assertEqual(len(admitted), 1)
                self.assertIsInstance(admitted[0]["args"]["value"], str)
                self.assertEqual(bridge.registry.calls[0][1]["value"], 2700)
                self.assertIs(type(bridge.registry.calls[0][1]["value"]), int)
                self.assertEqual(bridge.calls[0]["args"], bridge.registry.calls[0][1])
                operation = bridge.controller.operations[admitted[0]["call_id"]]
                self.assertEqual(operation["args"], admitted[0]["args"])

    def test_boolean_words_and_native_planner_values_reach_mock_as_bool(self):
        for word, expected in (("true", True), ("yes", True), ("false", False)):
            for value in (word, expected):
                with self.subTest(word=word, value=value):
                    bridge, admitted = self.dispatched("Update my pets allowed filter to " + word,
                                                       value, "pets_allowed")
                    self.assertEqual(len(admitted), 1)
                    self.assertIs(bridge.registry.calls[0][1]["value"], expected)

    def test_no_converts_to_false_but_cannot_bypass_the_existing_authorization_gate(self):
        self.assertIs(mock_call_args({"value": "no"}, TOOLS["update_search_filter"])["value"], False)
        # The unchanged controller treats bare "no" as a retraction. Scalar
        # serialization must not manufacture permission to get past that gate.
        for value in ("no", False):
            bridge, admitted = self.dispatched("Update my pets allowed filter to no", value, "pets_allowed")
            self.assertEqual(admitted, [])
            self.assertEqual(bridge.registry.calls, [])

    def test_existing_affirmed_predicate_still_grounds_true(self):
        text = "Update my pets allowed filter so pets are allowed"
        for value in ("true", True):
            bridge, admitted = self.dispatched(text, value, "pets_allowed")
            self.assertEqual(len(admitted), 1)
            self.assertIs(bridge.registry.calls[0][1]["value"], True)

    def test_native_true_cannot_borrow_a_conversational_yes(self):
        bridge, admitted = self.dispatched("Yes, update my pets allowed filter to false", True, "pets_allowed")
        self.assertEqual(admitted, [])
        self.assertEqual(bridge.registry.calls, [])

    def test_unstated_and_superseded_values_still_cannot_dispatch(self):
        for text, value in (("Update my max price filter to 2700", 2900),
                            ("Update my max price filter to 2700", "$2900"),
                            ("Do not update my max price filter to 2700", "2700"),
                            ("Change my max price filter from 2700 to 2900", 2700)):
            with self.subTest(text=text, value=value):
                bridge, admitted = self.dispatched(text, value)
                self.assertEqual(admitted, [])
                self.assertEqual(bridge.registry.calls, [])

    def test_genuine_text_and_alphanumeric_ids_remain_strings(self):
        for value in ("P0999", "XYZ88", "North ridge"):
            bridge, admitted = self.dispatched("Update my neighborhood filter to " + value, value, "neighborhood")
            self.assertEqual(len(admitted), 1)
            self.assertEqual(bridge.registry.calls[0][1]["value"], value)
            self.assertIs(type(bridge.registry.calls[0][1]["value"]), str)

    def test_compounds_and_missing_values_fail_the_existing_scalar_gate(self):
        for value in (["2700"], {"amount": "2700"}, None):
            bridge, admitted = self.dispatched("Update my max price filter to 2700", value)
            self.assertEqual(admitted, [])
            self.assertEqual(bridge.registry.calls, [])

    def test_unmarked_fields_and_identifier_descriptors_are_untouched(self):
        tool = {"args": {"value": {"type": "string"},
                         "product_id": {"type": "string", "fdb_mock_any": True},
                         "code": {"type": "string", "fdb_mock_any": True, "description": "Identifier"}}}
        args = {"value": "2700", "product_id": "0999", "code": "88", "undeclared": "true"}
        self.assertEqual(mock_call_args(args, tool), args)

    def test_continuations_normalize_but_bindings_keep_exact_result_types(self):
        decision = proposal(2700, "Update my max price filter to 2700")
        child = proposal(True, "Update my pets allowed filter to yes", "pets_allowed")["tool_calls"][0]
        decision["tool_calls"][0]["after_result"] = child
        normalized = normalize_mock_scalar_proposals(decision, context("Update my pets allowed filter to yes"))
        self.assertEqual(normalized["tool_calls"][0]["args"]["value"], "2700")
        self.assertEqual(child["args"]["value"], "yes")
        for binding in ("bindings", "result_bindings"):
            bound = proposal(2700, "Update the filter from the result")
            bound["tool_calls"][0][binding] = {"value": {"call_id": "call-1", "path": "amount"}}
            self.assertEqual(normalize_mock_scalar_proposals(deepcopy(bound), context("Update the filter")), bound)


class NativePlannerScalarTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_planner_path_normalizes_native_value_without_arg_normalize_flag(self):
        text = "Update my max price filter to 2700"

        def reply(request):
            if request.url.path == "/apply-template":
                view = json.loads(json.loads(request.content)["messages"][1]["content"])
                self.assertEqual(view["tools"]["update_search_filter"]["args"]["value"]["type"],
                                 ["string", "number", "boolean"])
                return httpx.Response(200, json={"prompt": "Authored prompt"})
            return httpx.Response(200, json={"content": json.dumps(proposal(2700, text)),
                                            "tokens_evaluated": 5, "tokens_predicted": 5})

        planner = LocalPlanner("http://127.0.0.1:9/v1", "authored-no-model")
        planner.arg_normalize = False
        planner.client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
        self.addAsyncCleanup(planner.close)
        result = await planner.plan(context(text))
        self.assertEqual(result["tool_calls"][0]["args"]["value"], "2700")


if __name__ == "__main__":
    unittest.main()
