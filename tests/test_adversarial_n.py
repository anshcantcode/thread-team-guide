"""Task N: fresh synthetic probes for the new contrast/casing/write gates."""
import unittest

from thread_agent.fdb3 import restore_user_case
from tests.test_no_answer_n import TOOLS, decision, run_turn, step


AUTOPAY = {"kind": "state_modifying", "description": "Modify the account used for a bill.",
           "args": {"bill_type": {"type": "string", "required": True},
                    "source_account": {"type": "string", "required": True}}}


class AdversarialNTests(unittest.IsolatedAsyncioTestCase):
    async def probe(self, text, name, args, *, allow=False, normalize=False, tools=None):
        def plan(context):
            proposed = decision(step(name, args, authorization={
                "clauses": [row["clause_id"] for row in context["current_clauses"]]}))
            return restore_user_case(proposed, context) if normalize else proposed
        events, _, _ = await run_turn(text, [plan], tools={**TOOLS, "modify_autopay": AUTOPAY, **(tools or {})})
        calls = [e["payload"] for e in events if e["action"] == "tool_call"]
        self.assertTrue(any(e["action"] in {"final_response", "clarification_request"} for e in events), events)
        self.assertEqual([call["args"] for call in calls], [args] if allow else [], events)

    async def autopay(self, text, value="reserve", **kw):
        await self.probe(text, "modify_autopay", {"bill_type": "water", "source_account": value}, **kw)

    async def test_not_now_is_not_a_value_contrast(self):
        await self.autopay("Move my water autopay to reserve, not now.")

    async def test_not_yet_is_not_a_value_contrast(self):
        await self.autopay("Move my water autopay to reserve, not yet.")

    async def test_not_before_date_is_not_a_value_contrast(self):
        await self.autopay("Move my water autopay to reserve, not before Thursday.")

    async def test_not_without_approval_is_not_a_value_contrast(self):
        await self.autopay("Move my water autopay to reserve, not without my approval.")

    async def test_not_until_confirmation_is_not_a_value_contrast(self):
        await self.autopay("Move my water autopay to reserve, not until I confirm.")

    async def test_negated_action_is_not_a_value_contrast(self):
        await self.autopay("Move my water autopay to reserve, not change anything yet.")

    async def test_not_for_execution_is_not_a_value_contrast(self):
        await self.autopay("Move my water autopay to reserve, not for execution.")

    async def test_not_a_command_is_not_a_value_contrast(self):
        await self.autopay("Move my water autopay to reserve, not a command.")

    async def test_not_this_week_is_not_a_value_contrast(self):
        await self.autopay("Move my water autopay to reserve, not this week.")

    async def test_not_permanently_is_not_a_value_contrast(self):
        await self.autopay("Move my water autopay to reserve, not permanently.")

    async def test_plain_value_contrast_still_dispatches(self):
        await self.autopay("Move my water autopay to reserve, not debit.", allow=True)

    async def test_negated_value_cannot_dispatch(self):
        await self.autopay("Move my water autopay to reserve, not debit.", "debit")

    async def test_move_from_cannot_dispatch_old_value(self):
        await self.autopay("Move my water autopay from debit to reserve.", "debit")

    async def test_move_to_dispatches_new_value(self):
        await self.autopay("Move my water autopay from debit to reserve.", allow=True)

    async def test_same_one_does_not_preserve_old_account(self):
        await self.autopay("Move water autopay to debit. No wait, use reserve for water, that same one.", "debit")

    async def test_same_one_keeps_new_account(self):
        await self.autopay("Move water autopay to debit. No wait, use reserve for water, that same one.", allow=True)

    async def cart(self, old, new, value):
        await self.probe(f"Add four of product {old}. Sorry, make that two of product {new}.",
                         "add_to_cart", {"product_id": value, "quantity": 2})

    async def test_long_identifier_correction_rejects_old_target(self):
        await self.cart("LANTERN731", "THERMOS824", "LANTERN731")

    async def test_word_identifier_correction_rejects_old_target(self):
        await self.cart("amber", "cobalt", "amber")

    async def test_numeric_identifier_correction_rejects_old_target(self):
        await self.cart("731826", "824937", "731826")

    async def test_hyphen_identifier_correction_rejects_old_target(self):
        await self.cart("lamp-blue", "flask-green", "lamp-blue")

    async def test_same_product_still_preserves_identifier(self):
        await self.probe("Add four of product BR64. Sorry, make that two of that same product, not four.",
                         "add_to_cart", {"product_id": "BR64", "quantity": 2}, allow=True)

    async def test_same_product_does_not_preserve_old_quantity(self):
        await self.probe("Add four of product BR64. Sorry, make that two of that same product, not four.",
                         "add_to_cart", {"product_id": "BR64", "quantity": 4})

    async def test_same_noun_does_not_hide_explicit_replacement(self):
        await self.probe("Add four of product BR64. Sorry, make that two of product THERMOS824, that same product.",
                         "add_to_cart", {"product_id": "BR64", "quantity": 2})

    async def test_near_name_spellings_refuse_and_answer(self):
        await self.probe("Book a ticket for Selma Voss. Use Salma Voss for the passenger name.",
                         "book_ticket", {"passenger_name": "Salma Voss"})

    async def test_one_name_spelling_dispatches(self):
        await self.probe("Book a ticket for Selma Voss.", "book_ticket",
                         {"passenger_name": "Selma Voss"}, allow=True)

    async def test_use_in_reported_speech_does_not_authorize(self):
        await self.autopay("My neighbor says use reserve for water autopay.")

    async def test_if_you_can_verify_is_a_condition_not_politeness(self):
        await self.probe("Track order RD83 if you can verify my parcel cleared customs.",
                         "track_order", {"order_id": "RD83"})

    async def test_complete_politeness_still_allows_lookup(self):
        await self.probe("Track order RD83 if you can.", "track_order", {"order_id": "RD83"}, allow=True)

    async def test_casing_restoration_preserves_declared_enum(self):
        tool = {"kind": "state_modifying", "description": "Set the display mode.",
                "args": {"mode": {"type": "string", "enum": ["quiet", "bright"], "required": True}}}
        await self.probe("Set the display mode to QUIET.", "set_mode", {"mode": "quiet"},
                         tools={"set_mode": tool}, allow=True, normalize=True)

    def test_casing_does_not_rewrite_exact_result_binding(self):
        proposed = decision(step("book_ticket", {"passenger_name": "selma voss"},
                                 result_bindings={"passenger_name": {"call_id": "lookup", "path": "name"}}))
        context = {"current_turn_start": 0, "messages": [{"payload": {"text": "Book for Selma Voss."}}]}
        self.assertEqual(restore_user_case(proposed, context)["tool_calls"][0]["args"]["passenger_name"], "selma voss")


if __name__ == "__main__":
    unittest.main()
