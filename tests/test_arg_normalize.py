"""Argument representation repairs: heard identifier spelling, unstated optional numbers."""
import os
from decimal import Decimal
import unittest

from participant.agent import spoken_numbers
from thread_agent.fdb3 import (LocalPlanner, complete_truncated_identifiers, drop_unstated_optional_numbers,
                               drop_unstated_search_filters,
                               heard_identifier, restore_first_person, strip_type_head_noun,
                               strip_vague_praise)

TOOLS = {
    "search_products": {"kind": "read_only", "args": {
        "query": {"type": "string", "required": True},
        "max_price": {"type": "number", "required": False}}},
    "add_to_cart": {"kind": "state_modifying", "args": {
        "product_id": {"type": "string", "required": True},
        "quantity": {"type": "integer", "required": False, "default": 1}}},
    "track_order": {"kind": "read_only", "args": {
        "order_id": {"type": "string", "required": True, "description": "Order identifier to track"}}},
    "update_identity_doc": {"kind": "state_modifying", "args": {
        "doc_type": {"type": "string", "required": True},
        "doc_number": {"type": "string", "required": True, "description": "The document identifier string"}}},
    "search_apartments": {"kind": "read_only", "args": {
        "city": {"type": "string", "required": True},
        "max_price": {"type": "number", "required": True}}},
}


def context(text):
    return {"tools": TOOLS, "current_turn_start": 0, "messages": [{"payload": {"text": text}}]}


def decision(*steps):
    return {"intent": "", "slots": {}, "tool_calls": [dict(step) for step in steps]}


class HeardIdentifierTest(unittest.TestCase):
    def test_spoken_digit_words_spell_the_identifier(self):
        text = "The number is x, y, z, eight, eight. Could you check it?"
        self.assertEqual(heard_identifier("xyz88", text), "XYZ88")

    def test_word_that_only_starts_with_digit_word_is_not_spelling(self):
        self.assertIsNone(heard_identifier("xyz88", "x y z eighty eight"))

    def test_existing_behaviour_kept(self):
        self.assertEqual(heard_identifier("b-o-b-1-2", "it is B-O-B-1-2"), "BOB12")


class TruncatedIdentifierTest(unittest.TestCase):
    def test_completion_does_not_append_a_spoken_quantity(self):
        for text in ("Add item B7, two of them please.", "Add item B seven two of them please."):
            result = complete_truncated_identifiers(decision(
                {"api_name": "add_to_cart", "args": {"product_id": "B7", "quantity": 2}}), context(text))
            self.assertEqual(result["tool_calls"][0]["args"], {"product_id": "B7", "quantity": 2}, text)

    def test_cut_short_identifier_takes_the_one_complete_spelling(self):
        result = complete_truncated_identifiers(decision({"api_name": "track_order", "args": {"order_id": "A"}}),
                                                context("The order ID is A, B, C, 1, 2, 3."))
        self.assertEqual(result["tool_calls"][0]["args"]["order_id"], "ABC123")
        result = complete_truncated_identifiers(decision(
            {"api_name": "update_identity_doc", "args": {"doc_type": "passport", "doc_number": "1122"}}),
            context("update my passport number to P one one two two"))
        self.assertEqual(result["tool_calls"][0]["args"]["doc_number"], "P1122")

    def test_spelling_alphabet_word_names_its_letter(self):
        result = complete_truncated_identifiers(decision(
            {"api_name": "update_identity_doc", "args": {"doc_type": "visa", "doc_number": "vector-4-4"}}),
            context("I need to update my visa number to v as in vector-4-4."))
        self.assertEqual(result["tool_calls"][0]["args"]["doc_number"], "V44")

    def test_ambiguous_complete_or_literal_values_untouched(self):
        for text, value in (("orders A B one and A C two", "A"), ("track x y z eight eight", "XYZ88"),
                            ("update it to J four four, no wait, not J four four, J four five", "J45"),
                            ("track order A B C one exactly as spelled", "A")):
            result = complete_truncated_identifiers(decision({"api_name": "track_order", "args": {"order_id": value}}),
                                                    context(text))
            self.assertEqual(result["tool_calls"][0]["args"]["order_id"], value, text)


class TypeHeadNounTest(unittest.TestCase):
    def test_type_value_drops_the_repeated_head_noun(self):
        for value, expected in (("travel_card", "travel"), ("gold card", "gold"), ("platinum", "platinum"),
                                ("card", "card"), ("credit_card", "credit_card")):
            field = "bill_type" if value == "credit_card" else "card_type"
            result = strip_type_head_noun(decision({"api_name": "get_card_benefits", "args": {field: value}}), context(""))
            self.assertEqual(result["tool_calls"][0]["args"][field], expected, value)


class VaguePraiseTest(unittest.TestCase):
    def test_query_drops_subjective_praise_only(self):
        for value, expected in (("nice watch", "watch"), ("really nice desk lamp", "desk lamp"),
                                ("cheap watch", "cheap watch"), ("wireless headphones", "wireless headphones"),
                                ("nice", "nice")):
            result = strip_vague_praise(decision({"api_name": "search_products", "args": {"query": value}}), context(""))
            self.assertEqual(result["tool_calls"][0]["args"]["query"], expected, value)


class UnstatedSearchFiltersTest(unittest.TestCase):
    def run_search(self, args, said):
        step = {"api_name": "search_apartments", "args": dict(args)}
        return drop_unstated_search_filters(decision(step), context(said))["tool_calls"][0]["args"]

    def test_guessed_required_filters_become_unspecified(self):
        said = "Find me something in Leeds, please."
        self.assertEqual(self.run_search({"city": "Leeds", "max_price": 5000}, said), {"city": "Leeds"})
        self.assertEqual(self.run_search({"city": "Leeds", "max_price": 0}, said), {"city": "Leeds"})

    def test_stated_or_last_remaining_filters_stay(self):
        self.assertEqual(self.run_search({"city": "Leeds", "max_price": 900}, "Leeds under 900 a month."),
                         {"city": "Leeds", "max_price": 900})
        # Nothing stated would remain: leave the proposal for the ordinary checks.
        self.assertEqual(self.run_search({"city": "", "max_price": 5000}, "Find me a place."),
                         {"city": "", "max_price": 5000})
        self.assertEqual(self.run_search({"city": "", "max_price": 900}, "Anything under 900."), {"max_price": 900})

    def test_non_search_reads_and_writes_are_untouched(self):
        step = {"api_name": "add_to_cart", "args": {"product_id": "B7", "quantity": 4}}
        self.assertEqual(drop_unstated_search_filters(decision(step), context("Add B7."))["tool_calls"][0]["args"],
                         {"product_id": "B7", "quantity": 4})


class FirstPersonTest(unittest.TestCase):
    def test_third_person_restatement_takes_the_users_words(self):
        said = "How long would it take to walk from my flat to my studio?"
        for value, expected in (("user's flat", "my flat"), ("the user's studio", "my studio"),
                                ("customer's flat", "my flat"), ("user's garage", "user's garage"),
                                ("the flat", "the flat")):
            result = restore_first_person(decision({"api_name": "track_order", "args": {"order_id": value}}), context(said))
            self.assertEqual(result["tool_calls"][0]["args"]["order_id"], expected, value)


class UnstatedOptionalNumbersTest(unittest.TestCase):
    def test_wrong_write_quantity_is_not_silently_dropped_to_a_default(self):
        proposal = {"api_name": "add_to_cart", "args": {"product_id": "B7", "quantity": 3},
                    "authorization": {"clauses": ["0.0"]}}
        result = drop_unstated_optional_numbers(decision(proposal), context("Add four of item B seven to my cart."))
        self.assertEqual(result["tool_calls"][0]["args"], {"product_id": "B7", "quantity": 3})

    def test_numeric_evidence_keeps_sign_decimals_and_phrase_boundaries(self):
        for text, expected in (("50.5", {Decimal("50.5")}), ("-50", {-50}),
                               ("fifty point five", {Decimal("50.5")}),
                               ("minus fifty", {-50}), ("twenty, 30, five", {20, 30, 5}),
                               ("minus 50", {-50}), ("50 point five", {Decimal("50.5")}),
                               ("fifty point 5", {Decimal("50.5")}), ("50. 60.", {50, 60}),
                               ("item P50", set()), ("twenty-five", {25}),
                               ("one hundred and five", {105})):
            with self.subTest(text=text):
                self.assertEqual(spoken_numbers(text), expected)

    def test_a_hundred_is_a_stated_number(self):
        self.assertEqual(spoken_numbers("under a hundred dollars"), {100})
        self.assertEqual(spoken_numbers("a thousand US dollars"), {1000})
        result = drop_unstated_optional_numbers(decision(
            {"api_name": "search_products", "args": {"query": "wireless headphones", "max_price": 100}}),
            context("wireless headphones under a hundred dollars"))
        self.assertEqual(result["tool_calls"][0]["args"]["max_price"], 100)

    def test_unstated_optional_budget_is_dropped(self):
        result = drop_unstated_optional_numbers(decision(
            {"api_name": "search_products", "args": {"query": "cat food", "max_price": 50}}),
            context("search for cat food and add three of whatever you find"))
        self.assertEqual(result["tool_calls"][0]["args"], {"query": "cat food"})

    def test_stated_budget_kept_digits_and_words(self):
        for text in ("keyboards under 200 dollars", "keyboards under two hundred dollars"):
            result = drop_unstated_optional_numbers(decision(
                {"api_name": "search_products", "args": {"query": "keyboards", "max_price": 200}}), context(text))
            self.assertEqual(result["tool_calls"][0]["args"]["max_price"], 200, text)

    def test_required_and_default_values_untouched(self):
        result = drop_unstated_optional_numbers(decision(
            {"api_name": "search_apartments", "args": {"city": "Denver", "max_price": 500}},
            {"api_name": "add_to_cart", "args": {"product_id": "P1", "quantity": 1}}),
            context("an apartment in Denver, and add P1"))
        self.assertEqual(result["tool_calls"][0]["args"]["max_price"], 500)
        self.assertEqual(result["tool_calls"][1]["args"]["quantity"], 1)

    def test_nested_continuation_is_checked(self):
        result = drop_unstated_optional_numbers(decision(
            {"api_name": "search_products", "args": {"query": "lamp"},
             "after_result": {"api_name": "search_products", "args": {"query": "bulb", "max_price": 9}}}),
            context("find a lamp then a bulb"))
        self.assertNotIn("max_price", result["tool_calls"][0]["after_result"]["args"])

    def test_switch_is_off_by_default(self):
        saved = os.environ.pop("THREAD_FDB3_ARG_NORMALIZE", None)
        try:
            self.assertFalse(LocalPlanner("http://127.0.0.1:8098/v1", "m").arg_normalize)
            os.environ["THREAD_FDB3_ARG_NORMALIZE"] = "1"
            self.assertTrue(LocalPlanner("http://127.0.0.1:8098/v1", "m").arg_normalize)
        finally:
            os.environ.pop("THREAD_FDB3_ARG_NORMALIZE", None)
            if saved is not None:
                os.environ["THREAD_FDB3_ARG_NORMALIZE"] = saved


if __name__ == "__main__":
    unittest.main()


class DeclaredWriteDefaultsTest(unittest.TestCase):
    def test_omitted_optional_write_argument_takes_the_declared_default(self):
        from thread_agent.fdb3 import fill_declared_write_defaults
        tools = {"add_to_cart": {"kind": "state_modifying", "args": {
                     "product_id": {"type": "string", "required": True},
                     "quantity": {"type": "integer", "required": False, "default": 1}}},
                 "calculate_commute": {"kind": "read_only", "args": {
                     "origin_address": {"type": "string", "required": True},
                     "mode": {"type": "string", "required": False, "default": "driving"}}},
                 "book_flight": {"kind": "state_modifying", "args": {"passenger_name": {"type": "string", "required": True}}}}
        decision = {"tool_calls": [
            {"api_name": "add_to_cart", "args": {"product_id": "Y3"}},
            {"api_name": "add_to_cart", "args": {"product_id": "Y4", "quantity": 3}},
            {"api_name": "calculate_commute", "args": {"origin_address": "Oak Street"}},
            {"api_name": "search_products", "args": {"query": "lamp"},
             "after_result": {"api_name": "add_to_cart", "args": {"product_id": "PROD1"}}},
            {"api_name": "book_flight", "args": {"passenger_name": "Emma Brown"}}]}
        result = fill_declared_write_defaults(decision, {"tools": tools})
        calls = result["tool_calls"]
        self.assertEqual(calls[0]["args"], {"product_id": "Y3", "quantity": 1})
        self.assertEqual(calls[1]["args"], {"product_id": "Y4", "quantity": 3})
        self.assertEqual(calls[2]["args"], {"origin_address": "Oak Street"})  # reads unchanged
        self.assertEqual(calls[3]["after_result"]["args"], {"product_id": "PROD1", "quantity": 1})
        self.assertEqual(calls[4]["args"], {"passenger_name": "Emma Brown"})  # nothing declared, nothing invented


class SnakeSpelledIdentifierTest(unittest.TestCase):
    def test_snake_or_prefixed_spelling_compacts_only_to_what_was_said(self):
        from thread_agent.fdb3 import normalize_write_identifiers
        tools = {"add_to_cart": {"kind": "state_modifying", "args": {
            "product_id": {"type": "string", "required": True, "description": "ID of the product"},
            "quantity": {"type": "integer", "required": False, "default": 1}}}}
        def run(text, value):
            decision = {"tool_calls": [{"api_name": "add_to_cart", "args": {"product_id": value, "quantity": 1}}]}
            context = {"messages": [{"payload": {"text": text}}], "current_turn_start": 0, "tools": tools}
            return normalize_write_identifiers(decision, context)["tool_calls"][0]["args"]["product_id"]
        text = "Put one of item S two in my cart, and add four of item S three as well."
        self.assertEqual(run(text, "s_two"), "S2")
        self.assertEqual(run(text, "s_three"), "S3")
        self.assertEqual(run("For item B seven, add six, sorry, make that two to my cart.", "item_b7"), "B7")
        # Never a spelling the user did not say, and prose stays prose.
        self.assertEqual(run(text, "s_four"), "s_four")
        self.assertEqual(run(text, "item_s9"), "item_s9")
        self.assertEqual(run("Add the blue mug to my cart.", "blue_mug"), "blue_mug")


class SpokenNumberConjunctionTest(unittest.TestCase):
    def test_and_ends_a_number_unless_it_follows_hundred_or_thousand(self):
        # Held-out-013: "under $30 and put three" lost the stated budget (max_price dropped).
        from decimal import Decimal
        from participant.agent import spoken_numbers
        self.assertIn(Decimal(30), spoken_numbers("look for a travel mug under $30 and put three of the one"))
        self.assertIn(Decimal(200), spoken_numbers("a watch under 200 and add it"))
        self.assertIn(Decimal(50), spoken_numbers("fifty and then"))
        self.assertEqual(spoken_numbers("two hundred and fifty"), {Decimal(250)})
        self.assertEqual(spoken_numbers("one thousand and five"), {Decimal(1005)})
        self.assertIn(Decimal(200), spoken_numbers("two hundred and then some"))
