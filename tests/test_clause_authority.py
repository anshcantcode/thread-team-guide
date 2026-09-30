"""Clause-cited write authority through the actual controller dispatch path.

Independently authored stories for sprint-2 block 3: corrected, paused, negated,
retracted, conditional, reported, multiword and spelled-identifier requests.
A valid citation is evidence, never automatic permission.
"""
import asyncio
from copy import deepcopy
import unittest

from participant.agent import ParticipantAgent
from participant.authorization import authorization_grant, count_mentions, natural_count, spelled_runs, turn_clauses
from participant.schema import call_key


CART = {"kind": "state_modifying", "description": "MANDATORY tool to add an item to the shopping cart.",
        "args": {"product_id": {"type": "string", "required": True, "description": "ID of the product"},
                 "quantity": {"type": "integer", "required": False, "default": 1, "description": "Amount to add"}}}
FILTER = {"kind": "state_modifying", "description": "MANDATORY tool to modify search filters.",
          "args": {"filter_name": {"type": "string", "required": True, "description": "Filter key to modify"},
                   "value": {"type": "string", "required": True, "description": "Filter value to apply"}}}


BOOK = {"kind": "state_modifying", "description": "Book a flight for a passenger.",
        "args": {"passenger_name": {"type": "string", "required": True, "description": "Passenger full name"}}}


def cart(product, quantity, clauses):
    return {"api_name": "add_to_cart", "args": {"product_id": product, "quantity": quantity},
            "authorization": {"clauses": clauses}}


class ClauseAuthorityTests(unittest.TestCase):
    def dispatch(self, texts, step, tools=None, operations=None):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.tools = deepcopy(tools or {"add_to_cart": CART, "update_search_filter": FILTER})
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": text, "end_of_turn": i == len(texts) - 1}}
                          for i, text in enumerate(texts)]
        agent.operations = deepcopy(operations or {})
        agent._dispatch(deepcopy(step))
        events = []
        while not agent.out_queue.empty():
            events.append(agent.out_queue.get_nowait())
        return [event["action"] for event in events], events

    def accepted(self, texts, step, **options):
        actions, events = self.dispatch(texts, step, **options)
        self.assertEqual(actions, ["tool_call"], (texts, events))
        self.assertEqual(events[0]["payload"]["args"], step["args"])

    def rejected(self, texts, step, **options):
        actions, events = self.dispatch(texts, step, **options)
        self.assertEqual(actions, ["clarification_request"], (texts, events))

    def test_clause_ids_are_stable_provenance(self):
        rows = turn_clauses([(3, "Add three of item J nine to my cart."), (5, "No wait, that's too many. Make it one.")])
        self.assertEqual([row["clause_id"] for row in rows], ["3.0", "5.0", "5.1", "5.2"])
        self.assertEqual([row["text"] for row in rows],
                         ["add three of item j nine to my cart.", "no wait,", "that's too many.", "make it one."])

    def test_pause_split_write_completes_with_both_clauses(self):
        self.accepted(["Add product M four to my cart.", "Two of them, please."], cart("M4", 2, ["0.0", "1.0"]))

    def test_quantity_correction_after_pause_uses_latest_value(self):
        texts = ["Add three of item J nine to my cart.", "No wait, that's too many. Make it one."]
        self.accepted(texts, cart("J9", 1, ["0.0", "1.2"]))
        self.rejected(texts, cart("J9", 3, ["0.0"]))            # later retraction voids the old count
        self.rejected(texts, cart("J9", 3, ["0.0", "1.2"]))     # count must follow the correction
        # Citing the retraction clause itself is no longer fatal: the count is restated
        # after the last marker ("make it one"), so this is the same effect as 0.0 + 1.2.
        self.accepted(texts, cart("J9", 1, ["0.0", "1.0", "1.2"]))
        self.rejected(texts, cart("J9", 3, ["0.0", "1.0", "1.2"]))  # the retracted count is never restated

    def test_modifier_only_citation_attaches_the_preceding_command(self):
        # Observed in the repaired text diagnostic: the model cited only "make it one".
        texts = ["Add three of item J nine to my cart. No wait, that's too many. Make it one."]
        self.accepted(texts, cart("J9", 1, ["0.3"]))
        self.rejected(texts, cart("J9", 3, ["0.3"]))

    def test_cancellation_is_not_revived_by_a_later_modifier(self):
        texts = ["Add item J nine to my cart. Actually, forget it. Make it one."]
        rows = {row["text"]: row["clause_id"] for row in turn_clauses([(0, texts[0])])}
        self.rejected(texts, cart("J9", 1, [rows["make it one."]]))
        self.rejected(texts, cart("J9", 1, [rows["add item j nine to my cart."], rows["make it one."]]))
        # A fresh full command after the cancellation is new authority.
        fresh = ["Add item J nine to my cart. Actually, forget it. Add item K two to my cart."]
        self.accepted(fresh, cart("K2", 1, [turn_clauses([(0, fresh[0])])[-1]["clause_id"]]))

    def test_citing_a_cancellation_cannot_revive_it_with_a_modifier(self):
        for text in ("Add item B seven to my cart. Actually, forget it. Make it one.",
                     "Add item B seven to my cart no wait cancel that actually make it one",
                     "Search for a kettle. Add item B seven to my cart. Never mind. Just one."):
            rows = turn_clauses([(0, text)])
            citations = [[row["clause_id"] for row in rows], [rows[0]["clause_id"], rows[-1]["clause_id"]]]
            for ids in citations:
                with self.subTest(text=text, ids=ids):
                    self.assertIsNone(authorization_grant(cart("B7", 1, ids), CART, [(0, text)]))

    def test_refused_plan_step_does_not_revive_a_cancelled_later_write(self):
        text = ("Don't add item K two. Add item B seven to my cart. "
                "Actually, forget it. Make it one.")
        rows = turn_clauses([(0, text)])
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.tools = {"add_to_cart": deepcopy(CART)}
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": text, "end_of_turn": True}}]
        agent._dispatch_plan([cart("K2", 1, [rows[0]["clause_id"]]),
                              cart("B7", 1, [row["clause_id"] for row in rows[1:]])])
        events = [agent.out_queue.get_nowait() for _ in range(agent.out_queue.qsize())]
        self.assertFalse(any(event["action"] == "tool_call" for event in events), events)
        self.assertEqual([event["action"] for event in events], ["clarification_request"])

    def test_ambiguous_counts_without_retraction_reject(self):
        self.rejected(["Add three of item J nine, two of them."], cart("J9", 2, ["0.0", "0.1"]))

    def test_unstated_quantity_accepts_only_the_declared_default(self):
        self.accepted(["Add item J nine to my cart."], cart("J9", 1, ["0.0"]))
        self.rejected(["Add item J nine to my cart."], cart("J9", 2, ["0.0"]))

    def test_negated_write_is_never_cherry_picked(self):
        text = ["Don't add item H six to my cart yet. Just search for hiking boots."]
        self.rejected(text, cart("H6", 1, ["0.0"]))
        self.rejected(text, cart("H6", 1, ["0.1"]))

    def test_retraction_after_pause_voids_the_write(self):
        self.rejected(["Add item Q three to my cart.", "Actually, forget it. Never mind."], cart("Q3", 1, ["0.0"]))
        self.rejected(["Add item Q three to my cart. Stop."], cart("Q3", 1, ["0.0"]))

    def test_conditional_or_reported_command_rejects_even_when_split_by_commas(self):
        for text in ("If it's in stock, add item J nine to my cart.", "My friend said add item J nine to my cart.",
                     "Add item J nine to my cart when it's back in stock.", "Maybe add item J nine to my cart."):
            with self.subTest(text=text):
                rows = turn_clauses([(0, text)])
                cited = [row["clause_id"] for row in rows if "add" in row["text"]]
                self.rejected([text], cart("J9", 1, cited))

    def test_sequencing_is_not_a_condition_and_idiom_is_not_negation(self):
        self.accepted(["Check my order first, and after that, add item J nine to my cart."], cart("J9", 1, ["0.2"]))
        self.accepted(["Don't forget to add item J nine to my cart."], cart("J9", 1, ["0.0"]))

    def test_citation_must_exist_in_order_and_in_the_current_turn(self):
        texts = ["Add item J nine to my cart. Add item K two to my cart."]
        for clauses in (["9.0"], [], [0], "0.0"):
            with self.subTest(clauses=clauses):
                self.rejected(texts, cart("J9", 1, clauses))
        # Both command clauses cited (any order) is re-cited to the one that states J9.
        self.accepted(texts, cart("J9", 1, ["0.1", "0.0"]))
        self.rejected(texts, cart("J7", 1, ["0.1", "0.0"]))  # a value nobody said
        # A citation to a different item's clause is re-cited once to the single current
        # clause that states this write's values, and must pass every check there.
        self.accepted(texts, cart("J9", 1, ["0.1"]))
        self.rejected(["Add item K two to my cart."], cart("J9", 1, ["0.0"]))  # nothing states J9
        # A clause cited twice is the same evidence as citing it once (public case 53
        # cited ["3.0", "3.0"]); order and existence are still enforced above.
        self.accepted(texts, cart("J9", 1, ["0.0", "0.0"]))

    def test_spelled_identifier_must_be_a_complete_run(self):
        self.assertEqual(spelled_runs("track order R Q seven four please"), {"rq74"})
        self.assertEqual(spelled_runs("my visa number is v as in vector-4-4"), {"v44"})
        # ASR writes a letter-digit chunk ("P5-2"); it still spells P52, and P5 stays cut short.
        self.assertEqual(spelled_runs("Two of item. P5-2 to my cart"), {"p52"})
        self.rejected(["Can you add two of item P5-2 to my cart?"], cart("P5", 2, ["0.0"]))
        self.accepted(["Can you add two of item P5-2 to my cart?"], cart("P52", 2, ["0.0"]))
        self.rejected(["Add item J nine five to my cart."], cart("J9", 1, ["0.0"]))
        self.rejected(["Add product M four to my cart."], cart("M", 1, ["0.0"]))  # letter of a longer spelling
        self.accepted(["Add item J nine five to my cart."], cart("J95", 1, ["0.0"]))

    def test_a_following_quantity_is_not_an_identifier_character(self):
        for text in ("Add item B7, two of them please.", "Add item B seven, two of them please.",
                     "Add item B7 two of them please.", "Add item B seven, two units please."):
            ids = [row["clause_id"] for row in turn_clauses([(0, text)])]
            with self.subTest(text=text):
                self.assertNotIn("b72", spelled_runs(text))
                self.accepted([text], cart("B7", 2, ids))
                self.rejected([text], cart("B72", 2, ids))

    def test_pronoun_value_is_not_a_target(self):
        self.rejected(["Add it to my cart."], cart("it", 1, ["0.0"]))

    def test_multiword_value_is_retained_not_truncated(self):
        text = ["Set my apartment search filter for neighborhood to quiet and safe."]
        step = {"api_name": "update_search_filter", "args": {"filter_name": "neighborhood", "value": "quiet and safe"},
                "authorization": {"clauses": ["0.0"]}}
        self.accepted(text, step)
        truncated = deepcopy(step)
        truncated["args"]["value"] = "quiet"
        self.rejected(text, truncated)
        appended = deepcopy(step)
        appended["args"]["value"] = "quiet and safe and cheap"
        self.rejected(text, appended)

    def test_type_label_before_its_schema_noun_is_not_truncated(self):
        # Held-out-001 finding: "passport number" named the doc_number field.
        tools = {"update_identity_doc": {"kind": "state_modifying", "description": "Update an identity document.",
                 "args": {"doc_type": {"type": "string", "required": True, "description": "Document type"},
                          "doc_number": {"type": "string", "required": True, "description": "Document number"}}}}
        step = {"api_name": "update_identity_doc", "args": {"doc_type": "passport", "doc_number": "XY4481"},
                "authorization": {"clauses": ["0.0"]}}
        self.accepted(["Update my passport number to XY4481."], step, tools=tools)

    def test_asr_split_compound_still_names_the_target(self):
        # Held-out-001 finding: ASR wrote "auto pay" for "autopay".
        tools = {"modify_autopay": {"kind": "state_modifying", "description": "MANDATORY tool to modify autopay settings.",
                 "args": {"bill_type": {"type": "string", "required": True}, "source_account": {"type": "string", "required": True}}}}
        step = {"api_name": "modify_autopay", "args": {"bill_type": "electricity", "source_account": "savings"},
                "authorization": {"clauses": ["0.0"]}}
        self.accepted(["Turn on auto pay for my electricity bill from my savings account."], step, tools=tools)

    def test_negated_alternative_does_not_block_the_same_turn_replacement(self):
        # extension-audio011: "no, do not add celery" retracts the alternative only.
        tools = {"add_checklist_item": {"kind": "state_modifying", "description": "Add an item to the checklist.",
                 "args": {"text": {"type": "string", "required": True}}}}
        text = ["Add chop the celery to my checklist.", "No, do not add celery.",
                "Add wash the spinach to my checklist instead."]
        def item(value, clause):
            return {"api_name": "add_checklist_item", "args": {"text": value}, "authorization": {"clauses": [clause]}}
        self.accepted(text, item("wash the spinach", "2.0"), tools=tools)
        self.rejected(text, item("chop the celery", "0.0"), tools=tools)
        self.rejected(["Do not add wash the spinach.", "Add wash the spinach to my checklist instead."],
                      item("wash the spinach", "1.0"), tools=tools)

    def test_condition_on_the_users_own_later_plan_does_not_veto_a_stated_command(self):
        text = ["Add item Z four to my cart, just one for now. I'll buy more later if I like it."]
        self.accepted(text, cart("Z4", 1, ["0.0", "0.1"]))
        self.rejected(["I'll add item Z four to my cart if it's cheap."], cart("Z4", 1, ["0.0"]))
        self.rejected(["Add item Z four to my cart if it's cheap. I'll pay later."], cart("Z4", 1, ["0.0"]))

    def test_count_phrases_with_item_nouns(self):
        self.assertEqual(natural_count("add three of item z4 to my cart"), 3)
        self.assertEqual(natural_count("put two units of z4 in my cart"), 2)
        self.accepted(["Put two units of item Z four in my cart."], cart("Z4", 2, ["0.0"]))

    def test_first_person_requests_and_prepositional_instead(self):
        tools = {"modify_autopay": {"kind": "state_modifying", "description": "MANDATORY tool to modify autopay settings.",
                 "args": {"bill_type": {"type": "string", "required": True, "description": "Type of bill"},
                          "source_account": {"type": "string", "required": True, "description": "Account to pull from"}}}}
        def autopay(clauses):
            return {"api_name": "modify_autopay", "args": {"bill_type": "water", "source_account": "checking"},
                    "authorization": {"clauses": clauses}}
        self.accepted(["I want to change my water auto pay to pull from checking instead of where it is now."],
                      autopay(["0.0"]), tools=tools)
        self.accepted(["Never mind the other thing, but for now could you switch my water autopay to checking?"],
                      autopay(["0.1"]), tools=tools)
        self.rejected(["I want to change my water autopay to checking. Actually, forget it."], autopay(["0.0"]), tools=tools)
        self.rejected(["I don't want to change my water autopay to checking."], autopay(["0.0"]), tools=tools)

    def test_snake_case_names_and_spoken_numbers_count_as_said(self):
        text = ["I want to update my search filter.", "So the max price is like eighteen hundred dollars a month."]
        step = {"api_name": "update_search_filter", "args": {"filter_name": "max_price", "value": "1800"},
                "authorization": {"clauses": ["0.0", "1.0"]}}
        self.accepted(text, step)
        unsaid = deepcopy(step)
        unsaid["args"]["value"] = "1900"
        self.rejected(text, unsaid)

    def test_superseded_clause_cannot_hide_a_submitted_effect(self):
        texts = ["Add item J nine to my cart. No, add item K two to my cart."]
        submitted = {"call-1": {"kind": "state_modifying", "status": "pending", "api_name": "add_to_cart",
                                "args": {"product_id": "J9", "quantity": 1}, "revision": 0, "request_start": 0,
                                "key": "x", "operation_id": "operation-1"}}
        self.rejected(texts, cart("K2", 1, ["0.2"]), operations=submitted)
        self.accepted(texts, cart("K2", 1, ["0.2"]))

    def test_count_phrases_are_direct_counts_only(self):
        self.assertEqual(count_mentions("add j9. one for me and one as a gift."), [])
        self.assertEqual(natural_count("add two items, two of the items, k2 to my cart."), 2)
        self.assertIsNone(natural_count("add three of j9. make it one."))

    # Negative controls adapted from competitor designs (ideas only, no code):
    # Aura's topic gate and REACTOR's repeat-versus-duplicate distinction.
    def test_same_verb_with_a_different_object_does_not_authorize(self):
        tools = {"book_flight": BOOK}
        step = {"api_name": "book_flight", "args": {"passenger_name": "Ana Diaz"}, "authorization": {"clauses": ["0.0"]}}
        self.rejected(["Can you book a hotel for Ana Diaz too?"], step, tools=tools)
        self.accepted(["Book the flight for Ana Diaz."], step, tools=tools)

    def test_backchannel_or_question_is_not_a_command(self):
        booking = {"api_name": "book_flight", "args": {"passenger_name": "Ana Diaz"}, "authorization": {"clauses": ["0.0"]}}
        self.rejected(["Okay."], booking, tools={"book_flight": BOOK})
        change = {"api_name": "update_search_filter", "args": {"filter_name": "neighborhood", "value": "gym"},
                  "authorization": {"clauses": ["0.0"]}}
        self.rejected(["Is the neighborhood near the gym safe?"], change)

    def test_fresh_request_for_one_more_is_a_new_effect_not_a_duplicate(self):
        done = {"call-1": {"operation_id": "operation-1", "call_id": "call-1", "api_name": "add_to_cart",
                           "args": {"product_id": "B7", "quantity": 1}, "kind": "state_modifying",
                           "request_start": 0, "revision": 0, "status": "success",
                           "key": call_key("add_to_cart", {"product_id": "B7", "quantity": 1}, write=True),
                           "step": {}, "retry": 0, "depth": 0, "selection": None, "authority_key": None}}
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.tools = deepcopy({"add_to_cart": CART})
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": text, "end_of_turn": True}}
                          for text in ("Add item B seven to my cart.", "Add one more of item B seven.")]
        agent.operations, agent._request_start = done, 1
        agent._dispatch(cart("B7", 1, ["1.0"]))
        self.assertEqual(agent.out_queue.get_nowait()["action"], "tool_call")


if __name__ == "__main__":
    unittest.main()
