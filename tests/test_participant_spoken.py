"""Authored public-contract receipts: no benchmark metadata or judge calls."""
import asyncio
from copy import deepcopy
import threading
import unittest

from participant.agent import ParticipantAgent
from participant.spoken import PUBLIC_TOOLS
from thread_agent.fdb3 import ControllerBridge


# Deliberately different names and quantities from the benchmark examples.
EXAMPLES = {
    "track_order": ({"order_id": "ZQ82"}, {"order_id": "ZQ82", "shipping_status": "Awaiting pickup"},
                    "Order ZQ82 has shipping status: awaiting pickup."),
    "get_exchange_rate": ({"amount": 320, "from_currency": "GBP", "to_currency": "INR"},
                          {"converted_amount": 33600.0, "rate": 105.0},
                          "320 British pounds is 33600 Indian rupees, at a rate of 105."),
    "calculate_commute": ({"origin_address": "Pine Road", "destination_address": "the library", "mode": "walking"},
                          {"duration_mins": 17, "mode": "walking"},
                          "Walking from Pine Road to the library takes 17 minutes."),
    "get_card_benefits": ({"card_type": "silver"}, {"card_type": "silver", "benefits": ["3% Cashback", "Travel cover"]},
                         "The silver card benefits are 3 percent Cashback and Travel cover."),
    "book_flight": ({"passenger_name": "Nia Park"}, {"booking_ref": "R28", "passenger": "Nia Park"},
                    "Done. I booked a flight for Nia Park. Your booking reference is R28."),
    "update_identity_doc": ({"doc_type": "driver_license", "doc_number": "NX8271"},
                            {"updated_doc": "driver_license", "masked_number": "8271"},
                            "Done. Your driver license number is updated to NX8271."),
    "modify_autopay": ({"bill_type": "water", "source_account": "checking"},
                       {"autopay_enabled": True, "bill": "water", "source": "checking"},
                       "Done. Your water autopay now pulls from checking."),
    "update_search_filter": ({"filter_name": "pet_policy", "value": "cats allowed"},
                             {"filter_updated": "pet_policy", "new_value": "cats allowed"},
                             "Done. Your pet policy search filter is now cats allowed."),
    "add_to_cart": ({"product_id": "ITEM8", "quantity": 3},
                    {"product_id": "ITEM8", "quantity": 3, "cart_total": 74.97},
                    "Done. I added 3 of ITEM8 to your cart. Your cart total is 74.97."),
    "search_flights": ({"destination": "Porto", "date": "2027-03-12"},
                       {"flights": [{"flight_id": "ZX82", "destination": "Porto", "date": "2027-03-12", "price": 382.0}]},
                       "I found flight ZX82 to Porto on 2027-03-12, priced at 382."),
    "search_apartments": ({"city": "Dakar", "bedrooms": 3, "max_price": 1800.0},
                          {"city": "Dakar", "results": [{"id": "HOME7", "price": 1625.0, "beds": 3}]},
                          "I searched Dakar for 3 bedrooms with a maximum monthly rent of 1800. "
                          "I found apartment HOME7 with 3 bedrooms, at a monthly rent of 1625."),
    "search_products": ({"query": "desk lamps", "max_price": 85.0},
                        {"products": [{"product_id": "LAMP8", "name": "Amber desk lamp", "price": 69.5}]},
                        "I searched for desk lamps with a maximum price of 85. "
                        "I found Amber desk lamp, product LAMP8, priced at 69.5."),
}
WRITES = {"book_flight", "update_identity_doc", "modify_autopay", "update_search_filter", "add_to_cart"}


def operation(name, *, args=None, result=None, **extra):
    given, body, _ = EXAMPLES[name]
    return {"api_name": name, "args": deepcopy(given if args is None else args),
            "result": deepcopy({"status": "success", **body} if result is None else result),
            "status": "success", "kind": "state_modifying" if name in WRITES else "read_only",
            "step": {"response_template": "A planner must not replace a contract receipt."},
            "revision": 0, "call_id": "receipt-1", "depth": 0, **extra}


class SpokenReceiptTests(unittest.TestCase):
    def render(self, name, **kwargs):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        op = operation(name, **kwargs)
        before = deepcopy(op)
        answer = agent._render(op)
        self.assertEqual(op, before)
        self.assertEqual(agent.operations, {})
        self.assertTrue(agent.out_queue.empty())
        return answer

    def check(self, name):
        text = self.render(name)
        self.assertEqual(text, EXAMPLES[name][2])
        self.assertEqual(text.startswith("Done."), name in WRITES)
        for char in "[]{};_":
            self.assertNotIn(char, text)

    def test_order(self): self.check("track_order")
    def test_exchange(self): self.check("get_exchange_rate")
    def test_commute(self): self.check("calculate_commute")
    def test_card(self): self.check("get_card_benefits")
    def test_booking(self): self.check("book_flight")
    def test_identity(self): self.check("update_identity_doc")
    def test_autopay(self): self.check("modify_autopay")
    def test_filter(self): self.check("update_search_filter")
    def test_cart(self): self.check("add_to_cart")
    def test_flights(self): self.check("search_flights")
    def test_apartments(self): self.check("search_apartments")
    def test_products(self): self.check("search_products")

    def test_missing_or_extra_result_fields_use_the_existing_receipt_for_every_tool(self):
        self.assertEqual(set(EXAMPLES), set(PUBLIC_TOOLS))
        for name in EXAMPLES:
            body = operation(name)["result"]
            variants = [{key: value for key, value in body.items() if key != missing} for missing in body]
            variants.append({**body, "unfamiliar_field": "kept"})
            for result in variants:
                with self.subTest(name=name, result=result):
                    lead = "Done. " if name in WRITES else "Here is what I found: "
                    self.assertEqual(self.render(name, result=result), ParticipantAgent._compact_result(result, lead=lead))

    def test_missing_required_arguments_do_not_borrow_state_or_planner_values(self):
        optional = {("add_to_cart", "quantity"), ("calculate_commute", "mode"), ("search_products", "max_price")}
        for name, (args, _, _) in EXAMPLES.items():
            for missing in args:
                if (name, missing) in optional:
                    continue
                with self.subTest(name=name, missing=missing):
                    result = operation(name)["result"]
                    lead = "Done. " if name in WRITES else "Here is what I found: "
                    self.assertEqual(self.render(name, args={k: v for k, v in args.items() if k != missing}),
                                     ParticipantAgent._compact_result(result, lead=lead))

    def test_unsuccessful_or_conflicting_status_never_becomes_done_for_any_tool(self):
        for name in EXAMPLES:
            for status in ("pending", "unknown", "error", "not_submitted", "cancel_requested", "invalidated"):
                for conflicting in (False, True):
                    with self.subTest(name=name, status=status, conflicting=conflicting):
                        result = operation(name)["result"]
                        if conflicting:
                            result["status"] = status
                        text = self.render(name, result=result, status="success" if conflicting else status)
                        self.assertNotIn("Done", text)
                        self.assertIn("do not have a successful tool result", text)
            result = {**operation(name)["result"], "error": "not_found"}
            self.assertNotIn("Done", self.render(name, result=result))

    def test_incomplete_rows_and_wrong_types_fall_back_without_dropping_details(self):
        for name, key in (("search_flights", "flights"), ("search_apartments", "results"), ("search_products", "products")):
            body = operation(name)["result"]
            variants = [{**body, key: {}}, {**body, key: [body[key][0], {"odd": 7}]}]
            for result in variants:
                with self.subTest(name=name, result=result):
                    self.assertEqual(self.render(name, result=result), ParticipantAgent._compact_result(result))
        for name in EXAMPLES:
            for result in ([], "unexpected"):
                with self.subTest(name=name, result=result):
                    lead = "Done. " if name in WRITES else "Here is what I found: "
                    self.assertEqual(self.render(name, result=result), ParticipantAgent._compact_result(result, lead=lead))

    def test_mismatched_echoes_and_masked_number_do_not_confirm_requested_change(self):
        for name, field in (("book_flight", "passenger"), ("update_identity_doc", "masked_number"),
                            ("modify_autopay", "source"), ("update_search_filter", "new_value"),
                            ("add_to_cart", "product_id"), ("track_order", "order_id")):
            with self.subTest(name=name):
                body = {**operation(name)["result"], field: "different"}
                text = self.render(name, result=body)
                self.assertIn(field.replace("_", " ") + ": different", text)
                self.assertNotEqual(text, EXAMPLES[name][2])

    def test_false_autopay_is_not_enabled_and_unknown_shipping_is_not_delivered(self):
        body = {**operation("modify_autopay")["result"], "autopay_enabled": False}
        text = self.render("modify_autopay", result=body)
        self.assertIn("autopay enabled: false", text)
        self.assertNotIn("now pulls", text)
        body = {**operation("track_order")["result"], "shipping_status": "unknown"}
        self.assertEqual(self.render("track_order", result=body), "Order ZQ82 has shipping status: unknown.")

    def test_signs_decimals_and_field_associations_are_preserved(self):
        args = {"amount": -0.25, "from_currency": "USD", "to_currency": "EUR"}
        body = {"status": "success", "converted_amount": -0.225, "rate": 0.9}
        self.assertEqual(self.render("get_exchange_rate", args=args, result=body),
                         "-0.25 US dollars is -0.225 euros, at a rate of 0.9.")
        for value in (True, "23", float("nan"), float("inf")):
            with self.subTest(value=value):
                body = {**operation("get_exchange_rate")["result"], "rate": value}
                self.assertTrue(self.render("get_exchange_rate", result=body).startswith("Here is what I found:"))
        text = self.render("add_to_cart", step={"response_template": "Added {cart_total} of {product_id}."})
        self.assertIn("added 3 of ITEM8", text)
        self.assertIn("cart total is 74.97", text)
        self.assertNotIn("dollars", text)

    def test_no_invented_currency_comparison_or_default_values(self):
        for name in ("search_products", "search_flights", "search_apartments", "add_to_cart"):
            self.assertNotIn("dollars", self.render(name))
        body = operation("search_products")["result"]
        body["products"][0]["price"] = 99
        text = self.render("search_products", result=body)
        self.assertIn("maximum price of 85", text)
        self.assertIn("priced at 99", text)
        self.assertNotIn("under", text)
        self.assertNotIn("maximum price", self.render("search_products", args={"query": "desk lamps"}))
        self.assertIn("17 minutes", self.render("calculate_commute", args={"origin_address": "Pine Road", "destination_address": "the library"}))

    def test_empty_collections_and_multiple_results_are_spoken_without_json(self):
        for name, field in (("get_card_benefits", "benefits"), ("search_products", "products"),
                            ("search_flights", "flights"), ("search_apartments", "results")):
            with self.subTest(name=name):
                body = {**operation(name)["result"], field: []}
                self.assertIn("were returned", self.render(name, result=body))
        body = operation("search_products")["result"]
        body["products"].append({"product_id": "LAMP9", "name": "Blue lamp", "price": 61})
        text = self.render("search_products", result=body)
        self.assertLess(text.index("LAMP8"), text.index("LAMP9"))
        self.assertEqual(text.count("LAMP9"), 1)

    def test_ancillary_metadata_and_injected_planner_prose_cannot_change_receipt(self):
        body = {**operation("track_order")["result"], "notes": "Everything was delivered"}
        text = self.render("track_order", result=body)
        self.assertNotIn("Everything was delivered", text)
        self.assertIn("metadata was omitted", text)
        for template in ("Done. The payment was sent.", "Converted amount -{rate} dollars."):
            self.assertEqual(self.render("get_exchange_rate", step={"response_template": template}), EXAMPLES["get_exchange_rate"][2])

    def test_identifier_separators_are_spoken_not_silently_removed(self):
        args = {"bill_type": "water", "source_account": "ACC_827"}
        body = {"status": "success", "autopay_enabled": True, "bill": "water", "source": "ACC_827"}
        self.assertEqual(self.render("modify_autopay", args=args, result=body),
                         "Done. Your water autopay now pulls from ACC underscore 827.")
        args = {"filter_name": "preferred_item", "value": "ITEM_8"}
        body = {"status": "success", "filter_updated": "preferred_item", "new_value": "ITEM_8"}
        self.assertEqual(self.render("update_search_filter", args=args, result=body),
                         "Done. Your preferred item search filter is now ITEM underscore 8.")


class SpokenTurnTests(unittest.IsolatedAsyncioTestCase):
    async def test_out_of_order_results_are_joined_once_in_dispatch_order(self):
        class Planner:
            async def setup(self): pass
            async def close(self): pass
            async def plan(self, context):
                return {"intent": "track", "slots": {}, "tool_calls": [
                    {"api_name": "track_order", "args": {"order_id": key}} for key in ("FIRST8", "SECOND9")]}
        released = threading.Event()
        class Registry:
            def call(self, name, **args):
                if args["order_id"] == "FIRST8":
                    if not released.wait(2):
                        raise TimeoutError("second call did not arrive")
                return {"status": "success", **args, "shipping_status": "In transit"}
        tools = {"track_order": {"kind": "read_only", "args": {"order_id": {"type": "string", "required": True}}}}
        bridge = ControllerBridge(tools, Registry(), Planner())
        original_final = bridge.controller._final
        def announce(text, *, call_id=None):
            original_final(text, call_id=call_id)
            if call_id == "call-2":
                released.set()  # Only after the second receipt is actually queued.
        bridge.controller._final = announce
        await bridge.start()
        try:
            answer = await bridge.response("Track FIRST8 and SECOND9", timeout=4)
            self.assertEqual(answer, "Order FIRST8 has shipping status: in transit. Order SECOND9 has shipping status: in transit.")
            self.assertEqual(len(bridge.calls), 2)
            self.assertEqual([e["payload"]["call_id"] for e in bridge.events if e["action"] == "final_response"],
                             ["call-2", "call-1"])
        finally:
            await bridge.close()

    async def test_completed_parent_and_continuation_are_both_announced_once(self):
        class Planner:
            async def setup(self): pass
            async def close(self): pass
            async def plan(self, context):
                return {"intent": "track", "slots": {}, "tool_calls": [{
                    "api_name": "track_order", "args": {"order_id": "CHAIN8"}, "after_result": {
                        "api_name": "track_order", "args": {"order_id": "CHAIN9"}}}]}
        class Registry:
            def call(self, name, **args):
                return {"status": "success", **args, "shipping_status": "In transit"}
        tools = {"track_order": {"kind": "read_only", "args": {"order_id": {"type": "string", "required": True}}}}
        bridge = ControllerBridge(tools, Registry(), Planner())
        await bridge.start()
        try:
            answer = await bridge.response("Track CHAIN8 and then CHAIN9", timeout=4)
            self.assertEqual(answer, "Order CHAIN8 has shipping status: in transit. Order CHAIN9 has shipping status: in transit.")
            # A duplicate executor notification neither dispatches the child
            # again nor produces a second copy of either completed step.
            await bridge.incoming.put({"event_type": "tool_result", "payload": {
                "call_id": "call-1", "api_name": "track_order", "status": "success",
                "result": {"status": "success", "order_id": "CHAIN8", "shipping_status": "In transit"}}})
            await bridge.synchronize()
            self.assertEqual(len(bridge.calls), 2)
            self.assertEqual(len([e for e in bridge.events if e["action"] == "final_response"]), 2)
            self.assertTrue(bridge.outputs.empty())
        finally:
            await bridge.close()


if __name__ == "__main__":
    unittest.main()
