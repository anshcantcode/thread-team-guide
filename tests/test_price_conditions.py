"""Price conditions verified only by this request's own returned prices."""
import unittest

from participant.authorization import authorization_grant, turn_clauses

CART = {"kind": "state_modifying", "description": "MANDATORY tool to add an item to the shopping cart.",
        "args": {"product_id": {"type": "string", "required": True, "description": "ID of the product"},
                 "quantity": {"type": "integer", "required": False, "default": 1}}}
BOOK = {"kind": "state_modifying", "description": "Book a flight ticket.",
        "args": {"passenger_name": {"type": "string", "required": True}}}
COFFEE = ("So search for a coffee maker first. If you find one that's under 50 dollars, go ahead and add two to the "
          "cart because they'd make great gifts. But if everything's over 50, just forget the coffee maker and "
          "track order W W W for me instead.")
FLIGHT = "Search flights to Toronto on July 20th. If there happens to be a flight under 300 dollars, go ahead and book it for Riley Kim."


def cited(text, *needles):
    return [row["clause_id"] for row in turn_clauses([(0, text)]) if any(n in row["text"] for n in needles)]


def grant(text, tool, args, needles, lookups=(), pending=False):
    trace = []
    step = {"api_name": "add_to_cart" if tool is CART else "book_flight", "args": args,
            "authorization": {"clauses": cited(text, *needles)}}
    return authorization_grant(step, tool, [(0, text)], trace=trace, lookups=list(lookups), lookups_pending=pending), trace


def products(price, product_id="PROD1"):
    return {"products": [{"product_id": product_id, "name": "coffee maker", "price": price}]}


class PriceConditionTests(unittest.TestCase):
    def test_a_verified_price_does_not_erase_other_conditions(self):
        for text in ("Add item B seven to my cart if it is under 50 dollars and in stock.",
                     "Add item B seven to my cart if it is under 50 dollars including shipping.",
                     "If it is under 50 dollars and can arrive tomorrow, add item B seven to my cart.",
                     "If it is under 50 dollars, and in stock, add item B seven to my cart.",
                     "If it is over twenty point five dollars, add item B seven to my cart."):
            with self.subTest(text=text):
                self.assertIsNone(grant(text, CART, {"product_id": "B7", "quantity": 1},
                                        ("add item",), [products(20.25, "B7")])[0])

    def test_complete_price_condition_with_and_then_consequent(self):
        for text in ("If it is under 50 dollars, add item B seven to my cart.",
                     "If it is under 50 dollars then add item B seven to my cart.",
                     "Add item B seven to my cart if it is under 50 dollars.",
                     "If it is under fifty dollars go ahead and add item B seven to my cart."):
            with self.subTest(text=text):
                self.assertTrue(grant(text, CART, {"product_id": "B7", "quantity": 1},
                                      ("add item",), [products(20.25, "B7")])[0])

    def test_true_by_returned_price_grants(self):
        granted, trace = grant(COFFEE, CART, {"product_id": "PROD1", "quantity": 2}, ("add two", "under 50"), [products(40.0)])
        self.assertTrue(granted, trace)

    def test_false_by_returned_price_refuses(self):
        granted, trace = grant(COFFEE, CART, {"product_id": "PROD1", "quantity": 2}, ("add two", "under 50"), [products(60.0)])
        self.assertIsNone(granted)
        self.assertTrue(trace[0].startswith("condition false"), trace)

    def test_pending_lookup_waits_and_no_lookup_refuses(self):
        _, trace = grant(COFFEE, CART, {"product_id": "PROD1", "quantity": 2}, ("add two", "under 50"), pending=True)
        self.assertTrue(trace[0].startswith("awaiting own lookup"), trace)
        _, trace = grant(COFFEE, CART, {"product_id": "PROD1", "quantity": 2}, ("add two", "under 50"))
        self.assertTrue(trace[0].startswith("unverified condition"), trace)

    def test_linked_object_is_the_one_checked(self):
        lookups = [{"products": [{"product_id": "CHEAP", "price": 20.0}, {"product_id": "PRICEY", "price": 90.0}]}]
        granted, _ = grant(COFFEE, CART, {"product_id": "CHEAP", "quantity": 2}, ("add two", "under 50"), lookups)
        self.assertTrue(granted)
        granted, _ = grant(COFFEE, CART, {"product_id": "PRICEY", "quantity": 2}, ("add two", "under 50"), lookups)
        self.assertIsNone(granted)

    def test_unlinked_write_needs_a_single_priced_result(self):
        flight = {"flights": [{"flight_id": "FL123", "price": 450.0}]}
        granted, trace = grant(FLIGHT, BOOK, {"passenger_name": "Riley Kim"}, ("book it",), [flight])
        self.assertIsNone(granted)
        self.assertTrue(trace[0].startswith("condition false"), trace)
        cheap = {"flights": [{"flight_id": "FL9", "price": 250.0}]}
        self.assertTrue(grant(FLIGHT, BOOK, {"passenger_name": "Riley Kim"}, ("book it",), [cheap])[0])
        two = {"flights": [{"flight_id": "A", "price": 250.0}, {"flight_id": "B", "price": 280.0}]}
        self.assertIsNone(grant(FLIGHT, BOOK, {"passenger_name": "Riley Kim"}, ("book it",), [two])[0])

    def test_amounts_in_words(self):
        # Held-out-008 text mode: "under fifty dollars" was never parsed, so a proven condition refused.
        worded = COFFEE.replace("under 50 dollars", "under fifty dollars")
        granted, trace = grant(worded, CART, {"product_id": "PROD1", "quantity": 2}, ("add two", "under fifty"), [products(40.0)])
        self.assertTrue(granted, trace)
        granted, trace = grant(worded, CART, {"product_id": "PROD1", "quantity": 2}, ("add two", "under fifty"), [products(60.0)])
        self.assertIsNone(granted)
        from participant.authorization import _leading_amount
        for text, value in ((" a hundred dollars", 100), (" fifteen hundred", 1500), (" twenty-five bucks", 25),
                            (" two thousand five hundred", 2500), (" $1,200", 1200), (" 30 minutes", 30)):
            self.assertEqual(_leading_amount(text)[0], value, text)
        self.assertIsNone(_leading_amount(" the budget"))

    def test_other_units_are_not_prices(self):
        for text in ("Search for a phone case and check the commute, and if it's under 30 minutes, add the case to my cart.",
                     "Search for a phone case and check the commute, and if it's under thirty minutes, add the case to my cart."):
            self._minutes(text)

    def _minutes(self, text):
        granted, trace = grant(text, CART, {"product_id": "PROD1", "quantity": 1}, ("add the case",), [products(9.0)])
        self.assertIsNone(granted)
        self.assertTrue(trace[0].startswith("unverified condition"), trace)

    def test_subjective_condition_still_refuses(self):
        text = "Check 1000 US dollars in euros. If the exchange rate looks good to me, then change my mortgage autopay to checking."
        tool = {"kind": "state_modifying", "description": "MANDATORY tool to process billing details.",
                "args": {"bill_type": {"type": "string"}, "source_account": {"type": "string"}}}
        step = {"api_name": "modify_autopay", "args": {"bill_type": "mortgage", "source_account": "checking"},
                "authorization": {"clauses": cited(text, "change my mortgage")}}
        trace = []
        self.assertIsNone(authorization_grant(step, tool, [(0, text)], trace=trace,
                                              lookups=[{"converted_amount": 900.0, "rate": 0.9}]))


if __name__ == "__main__":
    unittest.main()
