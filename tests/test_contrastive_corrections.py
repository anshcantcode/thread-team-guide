"""Contrastive "Y, not X" corrections and corrections naming another identifier; invented wording only."""
import unittest

from participant.authorization import authorization_grant, turn_clauses

CART = {"kind": "state_modifying", "description": "Add an item to the shopping cart.",
        "args": {"product_id": {"type": "string", "required": True, "description": "ID of the product"},
                 "quantity": {"type": "integer", "required": False, "default": 1}}}
AUTOPAY = {"kind": "state_modifying", "description": "Modify which account pays a bill.",
           "args": {"bill_type": {"type": "string", "required": True},
                    "source_account": {"type": "string", "required": True}}}


def granted(text, tool, args):
    rows = turn_clauses([(0, text)])
    name = "modify_autopay" if tool is AUTOPAY else "add_to_cart"
    step = {"api_name": name, "args": args, "authorization": {"clauses": [row["clause_id"] for row in rows]}}
    return bool(authorization_grant(step, tool, [(0, text)], trace=[]))


class ContrastiveCorrectionTests(unittest.TestCase):
    def test_new_value_then_negated_old_value_authorizes_the_new_value(self):
        text = "For the gift bags, add four of product Q, T, five, one. Sorry, make that two of that same product, not four."
        self.assertTrue(granted(text, CART, {"product_id": "QT51", "quantity": 2}))
        self.assertFalse(granted(text, CART, {"product_id": "QT51", "quantity": 4}))

    def test_move_to_savings_not_checking(self):
        text = "Move only phone autopay to savings, not checking."
        self.assertTrue(granted(text, AUTOPAY, {"bill_type": "phone", "source_account": "savings"}))
        self.assertFalse(granted(text, AUTOPAY, {"bill_type": "phone", "source_account": "checking"}))

    def test_a_negated_sentence_of_its_own_still_retracts(self):
        self.assertFalse(granted("Move phone autopay to savings. Not now though.", AUTOPAY,
                                 {"bill_type": "phone", "source_account": "savings"}))

    def test_correction_naming_a_different_identifier_supersedes_the_old_one(self):
        text = "Add four of product QT51. Sorry, make that two of product ZK20 instead."
        self.assertFalse(granted(text, CART, {"product_id": "QT51", "quantity": 2}))
        self.assertTrue(granted(text, CART, {"product_id": "ZK20", "quantity": 2}))
        self.assertTrue(granted("Add four of product QT51. Sorry, make that two of QT51.", CART,
                                {"product_id": "QT51", "quantity": 2}))


if __name__ == "__main__":
    unittest.main()
