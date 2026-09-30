"""A refused proposal asks for missing values in the contract's words, never the validator's.

Declared shapes are the public tool contract as load_contract reads it (type,
required, description, default). User wording is invented; no benchmark
recordings, scenario text or labels.
"""
import asyncio
from copy import deepcopy
import unittest

from participant.agent import ParticipantAgent
from participant.schema import argument_problems, argument_question, validate_args
from thread_agent.fdb3 import ControllerBridge, drop_unstated_search_filters


def declared(description, kind="string", required=True, **extra):
    return {"type": kind, "required": required, "description": description, **extra}


CONTRACT = {
    "search_apartments": {"kind": "read_only", "description": "Search for available rental apartments.", "args": {
        "city": declared("Destination city"),
        "bedrooms": declared("Number of bedrooms", "integer"),
        "max_price": declared("Maximum monthly rent budget", "number")}},
    "search_flights": {"kind": "read_only", "description": "Search for available flights to a destination.", "args": {
        "destination": declared("The city or airport, e.g. 'London' or 'LHR'"),
        "date": declared("The travel date, e.g. '2026-08-20'")}},
    "get_exchange_rate": {"kind": "read_only", "description": "Fetch the current foreign exchange rate.", "args": {
        "amount": declared("Amount to convert", "number"),
        "from_currency": declared("3-letter currency code, e.g. 'USD'"),
        "to_currency": declared("3-letter currency code, e.g. 'EUR'")}},
    "calculate_commute": {"kind": "read_only", "description": "Calculate commute duration.", "args": {
        "origin_address": declared("Starting location"),
        "destination_address": declared("Destination location"),
        "mode": declared("Transport mode, defaults to 'driving'", required=False, default="driving")}},
    "update_identity_doc": {"kind": "state_modifying", "description": "Update identity document details.", "args": {
        "doc_type": declared("Type of document, e.g. 'passport' or 'id_card'"),
        "doc_number": declared("The document identifier string")}},
    "add_to_cart": {"kind": "state_modifying", "description": "Add an item to the shopping cart.", "args": {
        "product_id": declared("ID of the product"),
        "quantity": declared("Amount to add", "integer", required=False, default=1)}},
}

# Words the validator uses that must never be spoken.
JARGON = r"args|_|\w\.\w|missing required|undeclared|expected|enum|descriptor|\bnull\b|None"


class QuestionTests(unittest.TestCase):
    def ask(self, name, args, expected):
        text = argument_question(CONTRACT[name], args)
        self.assertEqual(text, expected)
        self.assertNotRegex(text, JARGON)

    def test_housing_search_asks_for_each_missing_filter_in_contract_words(self):
        for args, expected in (
            ({"city": "Tucson", "bedrooms": 1}, "Could you tell me the maximum monthly rent budget?"),
            ({"city": "Tucson", "max_price": 1500}, "Could you tell me the number of bedrooms?"),
            ({"bedrooms": 2, "max_price": 1500}, "Could you tell me the destination city?"),
            ({"city": "Tucson"}, "Could you tell me the number of bedrooms and the maximum monthly rent budget?"),
            ({}, "Could you tell me the destination city, the number of bedrooms, and the maximum monthly rent budget?"),
            # A null is an omitted value: asked for, never dispatched.
            ({"city": "Tucson", "bedrooms": 1, "max_price": None}, "Could you tell me the maximum monthly rent budget?"),
        ):
            with self.subTest(args=args):
                self.assertTrue(validate_args(CONTRACT["search_apartments"], args))
                self.ask("search_apartments", args, expected)

    def test_validator_messages_are_unchanged_and_classified(self):
        tool = CONTRACT["search_apartments"]
        self.assertEqual(validate_args(tool, {"city": "Tucson", "bedrooms": 1}),
                         ["args.max_price: missing required argument"])
        self.assertEqual(argument_problems(tool, {"city": "Tucson", "bedrooms": 1, "max_price": None}),
                         [("args.max_price", "missing", "args.max_price: expected 'number'")])
        self.assertEqual(argument_problems(tool, {"city": "Tucson", "bedrooms": "one", "max_price": 900, "pets": True}),
                         [("args.bedrooms", "invalid", "args.bedrooms: expected 'integer'"),
                          ("args.pets", "internal", "args.pets: undeclared argument")])
        self.assertEqual(validate_args(tool, {"city": "Tucson", "bedrooms": 1, "max_price": 900}), [])

    def test_unusable_values_are_named_without_validator_jargon(self):
        self.ask("search_apartments", {"city": "Tucson", "bedrooms": "one", "max_price": 1500},
                 "I could not use the value I had for the number of bedrooms. Could you say it again?")
        self.ask("search_apartments", {"city": 7, "bedrooms": "one", "max_price": 1500},
                 "I could not use the value I had for the destination city and the number of bedrooms. "
                 "Could you say them again?")
        self.ask("search_apartments", {"city": "Tucson", "bedrooms": "one"},
                 "I could not use the value I had for the number of bedrooms. "
                 "Could you tell me the number of bedrooms and the maximum monthly rent budget?")
        units = {"kind": "read_only", "args": {
            "city": declared("City name."),
            "units": declared("Temperature units (default imperial).", required=False, enum=["metric", "imperial"])}}
        text = argument_question(units, {"city": "Oslo", "units": "kelvin"})
        self.assertEqual(text, "I could not use the value I had for the temperature units. Could you say it again?")

    def test_descriptions_drop_examples_and_defaults_and_alike_arguments_use_names(self):
        self.ask("search_flights", {}, "Could you tell me the city or airport and the travel date?")
        self.ask("calculate_commute", {}, "Could you tell me the starting location and the destination location?")
        self.ask("update_identity_doc", {"doc_number": "K4471"}, "Could you tell me the type of document?")
        self.ask("add_to_cart", {}, "Could you tell me the ID of the product?")
        # Both currencies share one description; their names tell them apart, even alone.
        self.ask("get_exchange_rate", {"amount": 20}, "Could you tell me the from currency and the to currency?")
        self.ask("get_exchange_rate", {"amount": 20, "from_currency": "USD"}, "Could you tell me the to currency?")

    def test_argument_without_usable_description_uses_its_name(self):
        tool = {"kind": "read_only", "args": {
            "max_price": {"type": "number", "required": True},
            "order_id": {"type": "string", "required": True, "description": ""},
            "include_pets": {"type": "boolean", "required": True, "description": "Whether pets are allowed"},
            "floorArea": {"type": "number", "required": True, "description": "See the unit_table.area field"}}}
        text = argument_question(tool, {})
        self.assertEqual(text, "Could you tell me the max price, the order ID, the include pets, "
                               "and the other details it needs?")
        self.assertNotRegex(text, JARGON)
        self.assertEqual(argument_question(tool, {"max_price": 1, "order_id": "Q7", "include_pets": True}),
                         "Could you tell me the floor area?")

    def test_problems_the_user_cannot_repair_ask_to_rephrase(self):
        rephrase = "I could not prepare that request with details I can use. Could you say it another way?"
        full = {"city": "Tucson", "bedrooms": 1, "max_price": 1500}
        for tool, args in ((CONTRACT["search_apartments"], {**full, "pets": True}),
                           (None, full), ({"kind": "mystery", "args": {}}, {}),
                           (CONTRACT["search_apartments"], None), (CONTRACT["search_apartments"], [full])):
            with self.subTest(tool=tool, args=args):
                self.assertTrue(validate_args(tool, args))
                self.assertEqual(argument_question(tool, args), rephrase)

    def test_nested_and_array_arguments_use_the_declared_property(self):
        tool = {"kind": "state_modifying", "args": {"order": {"type": "object", "required": True, "properties": {
            "items": {"type": "array", "required": True, "description": "Products to order",
                      "items": {"type": "object", "properties": {
                          "sku": {"type": "string", "required": True, "description": "Stock keeping unit"}}}},
            "note": {"type": "string", "description": "Delivery note"}}}}}
        self.assertEqual(argument_question(tool, {"order": {}}), "Could you tell me the products to order?")
        self.assertEqual(argument_question(tool, {"order": {"items": [{}]}}), "Could you tell me the stock keeping unit?")
        self.assertEqual(argument_question(tool, {"order": {"items": [{"sku": "B7"}], "note": 4}}),
                         "I could not use the value I had for the delivery note. Could you say it again?")


class Planner:
    def __init__(self, proposal):
        self.proposal = proposal

    async def setup(self):
        pass

    async def close(self):
        pass

    async def plan(self, context):
        # As the local planner post-processes a proposal: a guessed search filter is removed.
        return drop_unstated_search_filters({"tool_calls": [deepcopy(self.proposal)]}, context)


class Registry:
    def __init__(self):
        self.calls = []

    def call(self, name, **args):
        self.calls.append((name, deepcopy(args)))
        return {"status": "success", "city": args["city"], "results": []}


class DispatchTests(unittest.IsolatedAsyncioTestCase):
    EVIDENCE = {"api_name": "search_apartments", "problems": ["args.max_price: missing required argument"]}

    def agent(self):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.tools = deepcopy(CONTRACT)
        agent.messages = [{"event_type": "user_speech_chunk",
                           "payload": {"text": "Find a one bedroom apartment in Tucson."}}]
        return agent

    def events(self, agent):
        rows = []
        while not agent.out_queue.empty():
            rows.append(agent.out_queue.get_nowait())
        return rows

    async def test_controller_speaks_the_question_and_keeps_validator_evidence(self):
        agent = self.agent()
        agent._dispatch({"api_name": "search_apartments", "args": {"city": "Tucson", "bedrooms": 1}})
        events = self.events(agent)
        self.assertFalse([event for event in events if event["action"] == "tool_call"])
        self.assertEqual([event["payload"] for event in events if event["action"] == "clarification_request"],
                         [{"text": "Could you tell me the maximum monthly rent budget?", "validation": self.EVIDENCE}])

    async def test_a_question_held_during_a_plan_keeps_its_evidence(self):
        agent = self.agent()
        agent._dispatch_plan([{"api_name": "search_apartments", "args": {"city": "Tucson", "bedrooms": 1}}])
        events = self.events(agent)
        self.assertFalse([event for event in events if event["action"] == "tool_call"])
        self.assertEqual([event["payload"] for event in events if event["action"] == "clarification_request"],
                         [{"text": "Could you tell me the maximum monthly rent budget?", "validation": self.EVIDENCE}])

    async def test_a_guessed_budget_is_removed_and_asked_for_without_any_call(self):
        registry = Registry()
        planner = Planner({"api_name": "search_apartments", "args": {"city": "Tucson", "bedrooms": 1, "max_price": 5000}})
        bridge = ControllerBridge(deepcopy(CONTRACT), registry, planner)
        await bridge.start()
        try:
            answer = await bridge.response("Find a one bedroom apartment in Tucson.", timeout=2)
            self.assertEqual(answer, "Could you tell me the maximum monthly rent budget?")
            self.assertEqual([event["payload"]["validation"] for event in bridge.events
                              if event["action"] == "clarification_request"], [self.EVIDENCE])
            self.assertEqual(registry.calls, [])
            self.assertEqual(bridge.calls, [])
        finally:
            await bridge.close()


if __name__ == "__main__":
    unittest.main()
