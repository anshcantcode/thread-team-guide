"""Task L: synthetic adversarial customer requests, never benchmark examples.

Exercise the actual controller dispatch and follow-up paths with in-memory
results. Negative probes assert no tool call; positive controls keep useful
corrections, partial searches, and explicitly requested follow-ups working.
"""
import asyncio
from copy import deepcopy
import unittest
from unittest.mock import patch

from participant.agent import ParticipantAgent
from participant.authorization import turn_clauses
from participant.schema import call_key
from thread_agent import fdb3


CART = {"kind": "state_modifying", "description": "Add an item to the shopping cart.",
        "args": {"product_id": {"type": "string", "required": True},
                 "quantity": {"type": "integer", "required": False, "default": 1}}}
PAY = {"kind": "state_modifying", "description": "Pay a bill.",
       "args": {"bill_type": {"type": "string", "required": True},
                "source_account": {"type": "string", "required": True}}}
ADDRESS = {"kind": "state_modifying", "description": "Update the delivery address.",
           "args": {"address": {"type": "string", "required": True}}}
FILTER = {"kind": "state_modifying", "description": "Set an alert setting.",
          "args": {"setting": {"type": "string", "required": True},
                   "value": {"type": "string", "required": True}}}
BOOK = {"kind": "state_modifying", "description": "Book a flight.",
        "args": {"flight_id": {"type": "string", "required": True}}}
TRACK = {"kind": "read_only", "description": "Track an order.",
         "args": {"order_id": {"type": "string", "required": True}}}
SEARCH = {"kind": "read_only", "description": "Search products.",
          "args": {"query": {"type": "string", "required": True}}}
HOMES = {"kind": "read_only", "description": "Search homes.",
         "args": {"city": {"type": "string", "required": True},
                  "max_price": {"type": "number", "required": True}}}
TOOLS = {"add_to_cart": CART, "pay_bill": PAY, "update_address": ADDRESS,
         "set_alert": FILTER, "book_flight": BOOK, "track_order": TRACK,
         "search_products": SEARCH, "search_homes": HOMES,
         "search_flights": {"kind": "read_only", "description": "Search flights.",
                            "args": {"city": {"type": "string", "required": True}}},
         "search_hotels": {"kind": "read_only", "description": "Search hotels.",
                           "args": {"city": {"type": "string", "required": True}}},
         "read_receipt": {"kind": "read_only", "description": "Read a receipt.",
                          "args": {"receipt_number": {"type": "integer", "required": True}}}}


def proposal(name, args, clauses=None):
    step = {"api_name": name, "args": args}
    if clauses is not None:
        step["authorization"] = {"clauses": clauses}
    return step


def cart(product="V38", quantity=1, clauses=None):
    return proposal("add_to_cart", {"product_id": product, "quantity": quantity}, clauses or ["0.0"])


def citations(text):
    return [row["clause_id"] for row in turn_clauses([(0, text)])]


class AdversarialLTests(unittest.TestCase):
    def agent(self, text):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.tools = deepcopy(TOOLS)
        texts = [text] if isinstance(text, str) else text
        agent.messages = [{"event_type": "user_speech_chunk",
                           "payload": {"text": value, "end_of_turn": i == len(texts) - 1}}
                          for i, value in enumerate(texts)]
        return agent

    def events(self, agent):
        return [agent.out_queue.get_nowait() for _ in range(agent.out_queue.qsize())]

    def dispatch(self, text, step, *, agent=None, follow_up=False):
        agent = agent or self.agent(text)
        if follow_up:
            agent._follow_up_active = True
            agent._apply({"tool_calls": [deepcopy(step)]})
        else:
            agent._dispatch(deepcopy(step))
        return self.events(agent)

    def refused(self, text, step, **options):
        events = self.dispatch(text, step, **options)
        self.assertFalse(any(event["action"] == "tool_call" for event in events), events)

    def accepted(self, text, step, **options):
        events = self.dispatch(text, step, **options)
        calls = [event["payload"] for event in events if event["action"] == "tool_call"]
        self.assertEqual([call["args"] for call in calls], [step["args"]], events)

    def result(self, agent, result=None, *, name="search_products", args=None, status="success"):
        args = args or {"query": "camp stove"}
        agent.operations["lookup"] = {
            "call_id": "lookup", "operation_id": "lookup", "api_name": name, "args": args,
            "kind": "read_only", "request_start": 0, "revision": agent.revision,
            "status": status, "result": result or {}, "key": call_key(name, args),
            "step": {}, "retry": 0, "depth": 0, "selection": None}

    def test_same_address_correction_invalidates_old_write(self):
        text = "Update my delivery address to Juniper Lane. Wait, change my delivery address to Birch Court."
        self.refused(text, proposal("update_address", {"address": "Juniper Lane"}, ["0.0"]))

    def test_stretched_recitation_cannot_revive_old_address(self):
        text = "Update my delivery address to Juniper Lane. Wait, change my delivery address to Birch Court."
        self.refused(text, proposal("update_address", {"address": "Juniper Lane"}, citations(text)))

    def test_shared_cart_noun_does_not_make_quantity_correction_unrelated(self):
        text = "Add three of item V38 to my cart. Wait, make the cart quantity two."
        self.refused(text, cart(quantity=3))

    def test_shared_cart_noun_does_not_make_hold_unrelated(self):
        text = "Add item V38 to my cart. Wait, leave my cart alone for now."
        self.refused(text, cart())

    def test_other_explicit_setting_correction_preserves_first_setting(self):
        text = "Set the alert tone to chime and set the alert volume to 30. Wait, change the alert volume to 40."
        self.accepted(text, proposal("set_alert", {"setting": "tone", "value": "chime"}, ["0.0"]))

    def test_retracted_clause_never_recites_to_a_write(self):
        for tail in ("Actually, don't.", "No wait, forget it.", "Maybe later."):
            text = "Add item V38 to my cart. " + tail
            with self.subTest(tail=tail):
                self.refused(text, cart(clauses=citations(text)))

    def test_status_question_cannot_authorize_second_flight(self):
        text = "Book flight NX214. Is flight NX680 still on time?"
        self.refused(text, proposal("book_flight", {"flight_id": "NX680"}, ["0.0"]))

    def test_hedged_second_item_cannot_borrow_first_items_command(self):
        text = "Add item V38 to my cart. Maybe add item L92 later."
        self.refused(text, cart("L92", clauses=["0.0"]))

    def test_second_explicit_item_can_recite_to_its_own_command(self):
        text = "Add item V38 to my cart. Add item L92 to my cart."
        self.accepted(text, cart("L92", clauses=["0.0"]))

    def test_negated_bill_cannot_borrow_positive_bill_command(self):
        text = "Don't pay the utilities bill from checking, pay the card bill from checking."
        self.refused(text, proposal("pay_bill", {"bill_type": "utilities", "source_account": "checking"}, ["0.1"]))

    def test_positive_bill_after_negated_alternative_is_preserved(self):
        text = "Don't pay the utilities bill from savings, pay the card bill from checking."
        self.accepted(text, proposal("pay_bill", {"bill_type": "card", "source_account": "checking"}, ["0.1"]))

    def test_assistant_value_is_not_user_write_authority(self):
        text = "Add item V38 to my cart."
        agent = self.agent(text)
        agent.messages.append({"event_type": "assistant_response", "payload": {"text": "Add item L92 to my cart."}})
        self.refused(text, cart("L92"), agent=agent)

    def test_tool_value_cannot_replace_explicit_user_write_target(self):
        text = "Add item V38 to my cart."
        agent = self.agent(text)
        self.result(agent, {"product_id": "L92"})
        step = cart("L92")
        step["result_bindings"] = {"product_id": {"call_id": "lookup", "path": "product_id"}}
        self.refused(text, step, agent=agent)

    def test_bare_identifier_fragment_keeps_dictation(self):
        text = ["My new flight number is NX.", "680.", "Book that flight."]
        self.accepted(text, proposal("book_flight", {"flight_id": "NX680"}, ["0.0", "2.0"]))

    def test_bare_identifier_fragment_does_not_erase_retraction(self):
        text = ["My new flight number is NX.", "680.", "Actually, don't book that flight."]
        self.refused(text, proposal("book_flight", {"flight_id": "NX680"}, ["0.0", "2.1"]))

    def test_conditional_lookup_without_price_evidence_is_not_allowed(self):
        text = "If it is over 80 dollars, track order ZK42."
        self.refused(text, proposal("track_order", {"order_id": "ZK42"}))

    def test_conditional_lookup_waits_for_pending_search(self):
        text = "Search for a camp stove. If it is over 80 dollars, track order ZK42."
        agent = self.agent(text)
        self.result(agent, status="pending")
        events = self.dispatch(text, proposal("track_order", {"order_id": "ZK42"}), agent=agent)
        self.assertEqual([event["action"] for event in events], ["read_held"])
        self.assertEqual(events[0]["payload"]["condition"], "pending")

    def test_failed_lookup_does_not_prove_price_condition(self):
        text = "Search for a camp stove. If it is over 80 dollars, track order ZK42."
        agent = self.agent(text)
        self.result(agent, status="error")
        self.refused(text, proposal("track_order", {"order_id": "ZK42"}), agent=agent)

    def test_price_less_result_does_not_prove_price_condition(self):
        text = "Search for a camp stove. If it is over 80 dollars, track order ZK42."
        agent = self.agent(text)
        self.result(agent, {"items": [{"product_id": "V38", "name": "Camp stove"}]})
        self.refused(text, proposal("track_order", {"order_id": "ZK42"}), agent=agent)

    def test_true_price_prefix_does_not_prove_stock_conjunction(self):
        text = "Search for a camp stove. If it is over 80 dollars and in stock, track order ZK42."
        agent = self.agent(text)
        self.result(agent, {"items": [{"product_id": "V38", "price": 120}]})
        self.refused(text, proposal("track_order", {"order_id": "ZK42"}), agent=agent)

    def test_subjective_condition_cannot_authorize_lookup(self):
        text = "If the delivery offer looks good to me, track order ZK42."
        self.refused(text, proposal("track_order", {"order_id": "ZK42"}))

    def test_multiple_prices_do_not_make_false_universal_condition_true(self):
        text = "Search for a camp stove. If everything's over 80 dollars, track order ZK42."
        agent = self.agent(text)
        self.result(agent, {"items": [{"product_id": "V38", "price": 120}, {"product_id": "L92", "price": 45}]})
        self.refused(text, proposal("track_order", {"order_id": "ZK42"}), agent=agent)

    def test_universal_write_condition_checks_more_than_selected_item(self):
        text = "Search for camp stoves. If they're under 80 dollars, add item V38 to my cart."
        agent = self.agent(text)
        self.result(agent, {"items": [{"product_id": "V38", "price": 45}, {"product_id": "L92", "price": 120}]})
        self.refused(text, cart(clauses=["0.2"]), agent=agent)

    def test_true_universal_condition_allows_requested_lookup(self):
        text = "Search for a camp stove. If all of them are over 80 dollars, track order ZK42."
        agent = self.agent(text)
        self.result(agent, {"items": [{"product_id": "V38", "price": 120}, {"product_id": "L92", "price": 95}]})
        self.accepted(text, proposal("track_order", {"order_id": "ZK42"}), agent=agent)

    def test_false_all_of_them_are_condition_does_not_dispatch(self):
        text = "Search for a camp stove. If all of them are over 80 dollars, track order ZK42."
        agent = self.agent(text)
        self.result(agent, {"items": [{"product_id": "V38", "price": 45}]})
        self.refused(text, proposal("track_order", {"order_id": "ZK42"}), agent=agent)

    def test_status_statement_is_not_unconditional_lookup_request(self):
        text = "My order is ZK42. Search for a camp stove. If it is over 80 dollars, track order ZK42."
        agent = self.agent(text)
        self.result(agent, {"items": [{"product_id": "V38", "price": 45}]})
        self.refused(text, proposal("track_order", {"order_id": "ZK42"}), agent=agent)

    def test_explicit_unconditional_lookup_survives_false_conditional_repeat(self):
        text = "Track order ZK42. Search for a camp stove. If it is over 80 dollars, track order ZK42."
        agent = self.agent(text)
        self.result(agent, {"items": [{"product_id": "V38", "price": 45}]})
        self.accepted(text, proposal("track_order", {"order_id": "ZK42"}), agent=agent)

    def test_numeric_lookup_argument_does_not_bypass_condition(self):
        text = "If it is over 80 dollars, read receipt 731."
        self.refused(text, proposal("read_receipt", {"receipt_number": 731}))

    def test_plan_order_cannot_bypass_pending_condition(self):
        text = "Search for a camp stove. If it is over 80 dollars, track order ZK42."
        agent = self.agent(text)
        agent._dispatch_plan([proposal("track_order", {"order_id": "ZK42"}),
                              proposal("search_products", {"query": "camp stove"})])
        calls = [event["payload"]["api_name"] for event in self.events(agent) if event["action"] == "tool_call"]
        self.assertEqual(calls, ["search_products"])

    def test_held_lookup_does_not_survive_same_turn_cancellation(self):
        text = "Search for a camp stove. If it is over 80 dollars, track order ZK42."
        agent = self.agent(text)
        self.result(agent, status="pending")
        agent._dispatch(proposal("track_order", {"order_id": "ZK42"}))
        self.events(agent)
        agent.messages.append({"event_type": "user_speech_chunk", "payload": {
            "text": "Actually, don't track order ZK42.", "end_of_turn": True}})
        with patch.object(agent, "_maybe_follow_up"):
            agent._result({"call_id": "lookup", "api_name": "search_products", "status": "success",
                           "result": {"items": [{"product_id": "V38", "price": 120}]}})
        events = self.events(agent)
        self.assertFalse(any(event["action"] == "tool_call" for event in events), events)

    def test_explicit_second_lookup_with_shared_value_is_not_dropped(self):
        text = "Search flights to Bergen. Also search hotels in Bergen."
        agent = self.agent(text)
        self.result(agent, {"flights": []}, name="search_flights", args={"city": "Bergen"})
        self.accepted(text, proposal("search_hotels", {"city": "Bergen"}), agent=agent, follow_up=True)

    def test_unrequested_lookup_with_only_borrowed_value_is_dropped(self):
        text = "Search flights to Bergen and arrange airport assistance."
        agent = self.agent(text)
        self.result(agent, {"flights": []}, name="search_flights", args={"city": "Bergen"})
        self.refused(text, proposal("search_hotels", {"city": "Bergen"}), agent=agent, follow_up=True)

    def test_negated_lookup_with_borrowed_value_is_not_a_request(self):
        text = "Search flights to Bergen. Don't search hotels in Bergen."
        agent = self.agent(text)
        self.result(agent, {"flights": []}, name="search_flights", args={"city": "Bergen"})
        self.refused(text, proposal("search_hotels", {"city": "Bergen"}), agent=agent, follow_up=True)

    def test_partial_search_requires_a_user_stated_anchor(self):
        self.refused("Find me a home.", proposal("search_homes", {"city": "Bergen"}))

    def test_partial_search_cannot_drop_an_explicit_price_filter(self):
        self.refused("Search homes in Bergen with max_price 900.", proposal("search_homes", {"city": "Bergen"}))

    def test_search_normalizer_cannot_turn_wrong_price_into_unbounded_search(self):
        text = "Search homes in Bergen with max_price 900."
        agent = self.agent(text)
        step = proposal("search_homes", {"city": "Bergen", "max_price": 4000})
        decision = fdb3.drop_unstated_search_filters({"tool_calls": [step]}, agent._context())
        self.refused(text, decision["tool_calls"][0], agent=agent)

    def test_truly_unstated_required_price_requires_clarification(self):
        text = "Search homes in Bergen."
        agent = self.agent(text)
        step = proposal("search_homes", {"city": "Bergen", "max_price": 4000})
        decision = fdb3.drop_unstated_search_filters({"tool_calls": [step]}, agent._context())
        self.refused(text, decision["tool_calls"][0], agent=agent)
        self.assertEqual(decision["tool_calls"][0]["args"], {"city": "Bergen"})

    def test_partial_search_does_not_omit_identifier_named_number(self):
        agent = self.agent("Search orders with status shipped.")
        agent.tools["search_orders"] = {"kind": "read_only", "args": {
            "status": {"type": "string", "required": True},
            "order_number": {"type": "string", "required": True, "description": "Order identifier"}}}
        self.refused("", proposal("search_orders", {"status": "shipped"}), agent=agent)

    def test_first_person_normalizer_ignores_assistant_text(self):
        text = "Search for directions to the caller's cabin."
        agent = self.agent(text)
        agent.messages.append({"event_type": "assistant_response", "payload": {"text": "My cabin is nearby."}})
        step = proposal("search_products", {"query": "caller's cabin"})
        decision = fdb3.restore_first_person({"tool_calls": [step]}, agent._context())
        self.assertEqual(decision["tool_calls"][0]["args"], {"query": "caller's cabin"})

    def test_first_person_normalizer_preserves_literal_quoted_owner(self):
        text = "Search for the title customer's cabin, not my cabin."
        agent = self.agent(text)
        step = proposal("search_products", {"query": "customer's cabin"})
        decision = fdb3.restore_first_person({"tool_calls": [step]}, agent._context())
        self.assertEqual(decision["tool_calls"][0]["args"], {"query": "customer's cabin"})

    def test_first_person_normalizer_repairs_actual_user_phrase(self):
        text = "Search for my cabin."
        agent = self.agent(text)
        step = proposal("search_products", {"query": "customer's cabin"})
        decision = fdb3.restore_first_person({"tool_calls": [step]}, agent._context())
        self.assertEqual(decision["tool_calls"][0]["args"], {"query": "my cabin"})

    def test_universal_condition_needs_a_price_for_every_returned_item(self):
        text = "Search for camp stoves. If they're under 80 dollars, add item V38 to my cart."
        agent = self.agent(text)
        self.result(agent, {"items": [{"product_id": "V38", "price": 45}, {"product_id": "L92"}]})
        self.refused(text, cart(clauses=["0.2"]), agent=agent)

    def test_true_universal_write_condition_preserves_requested_action(self):
        text = "Search for camp stoves. If they're under 80 dollars, add item V38 to my cart."
        agent = self.agent(text)
        self.result(agent, {"items": [{"product_id": "V38", "price": 45}, {"product_id": "L92", "price": 60}]})
        self.accepted(text, cart(clauses=["0.2"]), agent=agent)

    def test_unrelated_condition_in_same_sentence_does_not_drop_lookup(self):
        text = "Track order ZK42, and if it is under 80 dollars, add item V38 to my cart."
        agent = self.agent(text)
        self.result(agent, {"items": [{"product_id": "V38", "price": 120}]})
        self.accepted(text, proposal("track_order", {"order_id": "ZK42"}), agent=agent)

    def test_postfix_condition_still_scopes_lookup(self):
        text = "Track order ZK42, if it is under 80 dollars."
        agent = self.agent(text)
        self.result(agent, {"items": [{"product_id": "V38", "price": 120}]})
        self.refused(text, proposal("track_order", {"order_id": "ZK42"}), agent=agent)

    def test_bare_cancellation_cannot_revive_held_lookup(self):
        text = "Search for a camp stove. If it is over 80 dollars, track order ZK42. Actually, never mind."
        agent = self.agent(text)
        self.result(agent, {"items": [{"product_id": "V38", "price": 120}]})
        self.refused(text, proposal("track_order", {"order_id": "ZK42"}), agent=agent)

    def test_later_hedge_cannot_revive_held_lookup(self):
        text = "Search for a camp stove. If it is over 80 dollars, track order ZK42. Maybe later."
        agent = self.agent(text)
        self.result(agent, {"items": [{"product_id": "V38", "price": 120}]})
        self.refused(text, proposal("track_order", {"order_id": "ZK42"}), agent=agent)

    def test_first_person_second_lookup_with_shared_city_is_not_dropped(self):
        text = "Search flights to Bergen. I would like to search hotels in Bergen."
        agent = self.agent(text)
        self.result(agent, {"flights": []}, name="search_flights", args={"city": "Bergen"})
        self.accepted(text, proposal("search_hotels", {"city": "Bergen"}), agent=agent, follow_up=True)

    def test_combined_requested_lookups_can_share_the_city(self):
        text = "Search flights and hotels in Bergen."
        agent = self.agent(text)
        self.result(agent, {"flights": []}, name="search_flights", args={"city": "Bergen"})
        self.accepted(text, proposal("search_hotels", {"city": "Bergen"}), agent=agent, follow_up=True)

    def test_borrowed_lookup_cannot_bypass_gate_with_a_continuation(self):
        text = "Search flights to Bergen and arrange airport assistance."
        agent = self.agent(text)
        self.result(agent, {"flights": []}, name="search_flights", args={"city": "Bergen"})
        step = proposal("search_hotels", {"city": "Bergen"})
        step["after_result"] = proposal("track_order", {"order_id": "ZK42"})
        self.refused(text, step, agent=agent, follow_up=True)

    def test_follow_up_hint_does_not_hide_second_tool_with_shared_city(self):
        text = "Search flights to Bergen. Also search hotels in Bergen."
        agent = self.agent(text)
        self.result(agent, {"flights": []}, name="search_flights", args={"city": "Bergen"})
        self.assertIn("also search hotels in bergen.", agent._uncovered_requests(list(agent.operations.values())))

    def test_search_normalizer_ignores_assistant_numeric_filter(self):
        agent = self.agent("Search homes in Bergen.")
        agent.messages.append({"event_type": "assistant_response", "payload": {"text": "The maximum is 4000."}})
        step = proposal("search_homes", {"city": "Bergen", "max_price": 4000})
        result = fdb3.drop_unstated_search_filters({"tool_calls": [step]}, agent._context())
        self.assertEqual(result["tool_calls"][0]["args"], {"city": "Bergen"})

    def test_first_person_normalizer_does_not_promote_negated_phrase(self):
        agent = self.agent("Search for a cabin near the harbor, not my cabin.")
        step = proposal("search_products", {"query": "user's cabin"})
        result = fdb3.restore_first_person({"tool_calls": [step]}, agent._context())
        self.assertEqual(result["tool_calls"][0]["args"], {"query": "user's cabin"})

    def test_running_repair_does_not_allow_a_retracted_write(self):
        agent = self.agent("Search for camp stoves and add item V38 to my cart. Actually, don't add it.")
        self.result(agent, {"items": []})
        operation = agent.operations["lookup"]
        operation["step"]["after_result"] = {
            **cart(), "bindings": {"product_id": "items.0.product_id"}}
        agent._repair_used = True
        agent._plan_task = object()  # A repair is already running, without starting a model.
        agent._continue_result(operation)
        self.assertFalse(agent._awaiting_clarification)
        self.events(agent)
        self.refused("", cart(), agent=agent)

    def test_corrections_new_value_cannot_impersonate_another_target(self):
        text = ("Update my address to Juniper Lane, and update my contact phone to 713. "
                "Wait, change my address to Phone Street.")
        self.refused(text, proposal("update_address", {"address": "Juniper Lane"}, ["0.0", "0.1"]))

    def test_no_argument_lookup_cannot_bypass_its_condition(self):
        text = "If it is over 80 dollars, list receipts."
        agent = self.agent(text)
        agent.tools["list_receipts"] = {"kind": "read_only", "description": "List receipts.", "args": {}}
        self.refused(text, proposal("list_receipts", {}), agent=agent)

    def test_result_binding_is_not_permission_for_unrequested_lookup(self):
        text = "Search flights to Bergen and arrange airport assistance."
        agent = self.agent(text)
        self.result(agent, {"city": "Bergen"}, name="search_flights", args={"city": "Bergen"})
        step = proposal("search_hotels", {"city": "Bergen"})
        step["result_bindings"] = {"city": {"call_id": "lookup", "path": "city"}}
        self.refused(text, step, agent=agent, follow_up=True)

    def test_requested_bound_lookup_can_reuse_returned_city(self):
        text = "Search flights to Bergen. Also search hotels in that city."
        agent = self.agent(text)
        self.result(agent, {"city": "Bergen"}, name="search_flights", args={"city": "Bergen"})
        step = proposal("search_hotels", {"city": "Bergen"})
        step["result_bindings"] = {"city": {"call_id": "lookup", "path": "city"}}
        self.accepted(text, step, agent=agent, follow_up=True)

    def test_reversed_plan_eventually_runs_lookup_when_price_is_proven(self):
        text = "Search for a camp stove. If it is over 80 dollars, track order ZK42."
        agent = self.agent(text)
        agent._dispatch_plan([proposal("track_order", {"order_id": "ZK42"}),
                              proposal("search_products", {"query": "camp stove"})])
        calls = [event["payload"] for event in self.events(agent) if event["action"] == "tool_call"]
        self.assertEqual([call["api_name"] for call in calls], ["search_products"])
        agent._result({"call_id": calls[0]["call_id"], "api_name": "search_products", "status": "success",
                       "result": {"items": [{"product_id": "V38", "price": 120}]}})
        calls = [event["payload"] for event in self.events(agent) if event["action"] == "tool_call"]
        self.assertEqual([call["api_name"] for call in calls], ["track_order"])

    def test_search_normalizer_preserves_natural_price_limit(self):
        text = "Search homes in Bergen under nine hundred dollars."
        agent = self.agent(text)
        step = proposal("search_homes", {"city": "Bergen", "max_price": 4000})
        result = fdb3.drop_unstated_search_filters({"tool_calls": [step]}, agent._context())
        self.refused(text, result["tool_calls"][0], agent=agent)


if __name__ == "__main__":
    unittest.main()
