"""Write-gate revision from the public-run refusal audit (27 September).

Each rule removes a blocker only when the text proves it does not apply to this
action; every accepted story has a refused counterpart. Stories are written for
these tests, not copied from benchmark recordings.
"""
import asyncio
from copy import deepcopy
import unittest

from participant.agent import ParticipantAgent, _affirmed_predicate, _said_as_phrase
from participant.authorization import authorization_grant, turn_clauses

FILTER = {"kind": "state_modifying",
          "description": "Instantly update the user's search filter in the backend system.",
          "args": {"filter_name": {"type": "string", "required": True, "description": "Filter key to modify"},
                   "value": {"type": "string", "required": True, "description": "Filter value to apply"}}}
AUTOPAY = {"kind": "state_modifying",
           "description": "MANDATORY tool to process billing details. Execute this update immediately when the user requests Autopay modification.",
           "args": {"bill_type": {"type": "string", "required": True, "description": "Type of bill, e.g. 'credit_card' or 'utilities'"},
                    "source_account": {"type": "string", "required": True, "description": "Bank account identifier, e.g. 'checking'"}}}
IDENTITY = {"kind": "state_modifying",
            "description": "MANDATORY tool to update simulated user identity document details (e.g. passport, driver license).",
            "args": {"doc_type": {"type": "string", "required": True, "description": "Type of document, e.g. 'passport' or 'id_card'"},
                     "doc_number": {"type": "string", "required": True, "description": "The document identifier string"}}}
BOOK = {"kind": "state_modifying", "description": "Book a flight ticket.",
        "args": {"passenger_name": {"type": "string", "required": True, "description": "The name of the passenger, e.g. 'John Doe'"}}}
CART = {"kind": "state_modifying", "description": "MANDATORY tool to add an item to the shopping cart.",
        "args": {"product_id": {"type": "string", "required": True, "description": "ID of the product"},
                 "quantity": {"type": "integer", "required": False, "default": 1, "description": "Amount to add"}}}
TOOLS = {"update_search_filter": FILTER, "modify_autopay": AUTOPAY, "update_identity_doc": IDENTITY,
         "book_flight": BOOK, "add_to_cart": CART}


def clause(texts, text):
    rows = turn_clauses(list(enumerate(texts)))
    return next(row["clause_id"] for row in rows if row["text"] == text)


def step(api, args, clauses):
    return {"api_name": api, "args": args, "authorization": {"clauses": clauses}}


class GateV2Tests(unittest.TestCase):
    def dispatch(self, texts, proposal, operations=None):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.tools = deepcopy(TOOLS)
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": text, "end_of_turn": i == len(texts) - 1}}
                          for i, text in enumerate(texts)]
        agent.operations = deepcopy(operations or {})
        agent._dispatch(deepcopy(proposal))
        events = []
        while not agent.out_queue.empty():
            events.append(agent.out_queue.get_nowait())
        return [event["action"] for event in events], events

    def accepted(self, texts, proposal, **options):
        actions, events = self.dispatch(texts, proposal, **options)
        self.assertEqual(actions, ["tool_call"], (texts, events))

    def rejected(self, texts, proposal, **options):
        actions, events = self.dispatch(texts, proposal, **options)
        self.assertEqual(actions, ["clarification_request"], (texts, events))
        return events[0]["payload"].get("gate")

    # Command grammar: fillers and adverbs around the request frame.
    def test_adverbs_and_fillers_around_the_command(self):
        texts = ["Could you just update my search filter so pets are allowed?"]
        self.accepted(texts, step("update_search_filter", {"filter_name": "pets", "value": "allowed"},
                                  [clause(texts, texts[0].casefold())]))
        texts = ["Um, so I need to like update my passport number to P one one two two."]
        cid = clause(texts, "so i need to like update my passport number to p one one two two.")
        self.accepted(texts, step("update_identity_doc", {"doc_type": "passport", "doc_number": "P1122"}, [cid]))
        # The value must still be complete and stated.
        self.rejected(texts, step("update_identity_doc", {"doc_type": "passport", "doc_number": "1122"}, [cid]))

    def test_raising_or_lowering_a_setting_is_an_update_command(self):
        # Public-run shape: "Let's raise the max price ..." and "bump up the minimum
        # bedrooms ..." were refused for lack of a command verb.
        for text, value in (("Let's raise the max price to 3,000 per month.", "3000"),
                            ("Could you lower my max price to 1,500?", "1500"),
                            ("And also bump up the max price to 2,000.", "2000"),
                            ("Please increase the max price to 2,500.", "2500")):
            texts = [text]
            cited = [row["clause_id"] for row in turn_clauses(list(enumerate(texts)))]
            with self.subTest(text=text):
                self.accepted(texts, step("update_search_filter", {"filter_name": "max_price", "value": value}, cited))
        for text, value in (("I might raise my max price to 3,000 later.", "3000"),
                            ("Don't lower the max price to 1,500.", "1500"),
                            ("If the listings stay this expensive, raise the max price to 3,000.", "3000")):
            texts = [text]
            cited = [row["clause_id"] for row in turn_clauses(list(enumerate(texts)))]
            with self.subTest(text=text):
                self.rejected(texts, step("update_search_filter", {"filter_name": "max_price", "value": value}, cited))

    def all_clauses(self, texts):
        return [row["clause_id"] for row in turn_clauses(list(enumerate(texts)))]

    def command_clause(self, texts, needle):
        return [row["clause_id"] for row in turn_clauses(list(enumerate(texts))) if needle in row["text"]]

    def test_topic_phrase_in_the_command_sentence_states_the_value(self):
        # Held-out-012 shape: "About my passport, I need you to update it, ..." cited without its topic.
        texts = ["About my passport, I need you to update it, the new number is T four four one."]
        cited = self.command_clause(texts, "update it") + self.command_clause(texts, "new number")
        self.accepted(texts, step("update_identity_doc", {"doc_type": "passport", "doc_number": "T441"}, cited))
        # Another sentence never states it.
        texts = ["I renewed my passport last year.", "Update the number to T four four one."]
        self.rejected(texts, step("update_identity_doc", {"doc_type": "passport", "doc_number": "T441"},
                                  self.command_clause(texts, "update the number")))

    def test_later_command_pointing_back_attaches_to_a_cited_value(self):
        texts = ["My new driver's license number is D four six eight.", "Can you update that on my profile?"]
        self.accepted(texts, step("update_identity_doc", {"doc_type": "driver_license", "doc_number": "D468"},
                                  self.command_clause(texts, "license number")))
        for later in ("That's just for reference. Don't change my profile yet.", "Maybe I'll update it next week."):
            texts = ["My new driver's license number is D four six eight.", later]
            with self.subTest(later=later):
                self.rejected(texts, step("update_identity_doc", {"doc_type": "driver_license", "doc_number": "D468"},
                                          self.command_clause(texts, "license number")))

    def test_hedge_about_a_different_item_does_not_scope_this_write(self):
        texts = ["Add item N six to my cart. I might want item N seven later, but not yet."]
        self.accepted(texts, step("add_to_cart", {"product_id": "N6", "quantity": 1},
                                  self.command_clause(texts, "add item n six")))
        for text in ("Add item N six to my cart. Actually, I might want that item later, but not yet.",
                     "Add item N six to my cart. I might change my mind.",
                     "Add item N six to my cart. Maybe item N six is the wrong one."):
            texts = [text]
            with self.subTest(text=text):
                self.rejected(texts, step("add_to_cart", {"product_id": "N6", "quantity": 1},
                                          self.command_clause(texts, "add item n six")))

    def test_condition_on_a_different_item_scopes_only_that_item(self):
        for text in ("Put one of item S two in my cart. Add four of item S three only if my sister confirms she needs them.",
                     "Add 2 of item M4 to my cart. I might want item M5, but I haven't decided about that one."):
            texts = [text]
            product, quantity = ("S2", 1) if "S two" in text else ("M4", 2)
            with self.subTest(text=text):
                self.accepted(texts, step("add_to_cart", {"product_id": product, "quantity": quantity},
                                          [texts[0].casefold() and turn_clauses([(0, text)])[0]["clause_id"]]))
        for text in ("Put one of item S two in my cart. Only if item S three sells out.",
                     "Put one of item S two in my cart only if item S three sells out.",
                     "Put one of item S two in my cart. Add item S two again only if it's cheap."):
            texts = [text]
            with self.subTest(text=text):
                self.rejected(texts, step("add_to_cart", {"product_id": "S2", "quantity": 1},
                                          [turn_clauses([(0, text)])[0]["clause_id"]]))

    def test_refusal_records_its_reason(self):
        texts = ["Maybe update my passport number to R T nine nine one."]
        gate = self.rejected(texts, step("update_identity_doc", {"doc_type": "passport", "doc_number": "RT991"}, ["0.0"]))
        self.assertEqual(gate["api_name"], "update_identity_doc")
        self.assertTrue(gate["reasons"][0].startswith("scope qualifier"), gate)

    def test_hold_fence_synonyms_cannot_authorize_after_the_timer_expires(self):
        for hold in ("Hang on.", "One second.", "Just a sec.", "Let me think.", "Let me see.", "Let me check."):
            text = "Add item B seven to my cart. " + hold
            for ids in (["0.0"], ["0.0", "0.1"]):
                with self.subTest(text=text, ids=ids):
                    self.assertIsNone(authorization_grant(step("add_to_cart", {"product_id": "B7", "quantity": 1}, ids),
                                                          CART, [(0, text)]))

    def test_completed_quantity_after_a_temporary_hold_is_authorized(self):
        text = "Add item B seven to my cart. Let me think. Just one."
        self.accepted([text], step("add_to_cart", {"product_id": "B7", "quantity": 1}, ["0.0", "0.1", "0.2"]))

    # A retraction inside the cited clause is a correction only when a proposed value
    # is restated after the last marker and nothing after it cancels.
    def test_unpunctuated_self_correction(self):
        texts = ["I want to switch my mortgage autopay to pull from checking wait wait no that's wrong make it savings instead"]
        self.accepted(texts, step("modify_autopay", {"bill_type": "mortgage", "source_account": "savings"}, ["0.0"]))
        self.rejected(texts, step("modify_autopay", {"bill_type": "mortgage", "source_account": "checking"}, ["0.0"]))

    def test_restating_the_target_does_not_revive_its_replaced_value(self):
        cases = (
            ("modify_autopay", AUTOPAY, {"bill_type": "mortgage", "source_account": "checking"},
             "source_account", "savings", "Switch my mortgage autopay to checking no wait use savings for my mortgage."),
            ("update_identity_doc", IDENTITY, {"doc_type": "passport", "doc_number": "P44"},
             "doc_number", "P45", "Update my passport number to P44, no wait P45 for my passport."),
            ("update_search_filter", FILTER, {"filter_name": "max_price", "value": "1500"},
             "value", "1200", "Update max price to 1500 no wait make it 1200 for max price."),
        )
        for api, tool, args, field, corrected, text in cases:
            ids = [row["clause_id"] for row in turn_clauses([(0, text)])]
            with self.subTest(text=text):
                self.assertIsNone(authorization_grant(step(api, args, ids), tool, [(0, text)]))
                self.accepted([text], step(api, {**args, field: corrected}, ids))

    def test_sparse_citations_cannot_hide_a_replaced_value(self):
        text = "Switch my mortgage autopay to checking. No wait. Use savings for my mortgage."
        for ids in (["0.0", "0.1", "0.2"], ["0.0", "0.2"], ["0.2"]):
            with self.subTest(ids=ids):
                self.rejected([text], step("modify_autopay", {"bill_type": "mortgage", "source_account": "checking"}, ids))
                self.accepted([text], step("modify_autopay", {"bill_type": "mortgage", "source_account": "savings"}, ids))

    def test_retraction_without_restatement_or_with_cancel_still_refuses(self):
        cancelled = ["Add item B seven to my cart three of them no wait forget it"]
        self.rejected(cancelled, step("add_to_cart", {"product_id": "B7", "quantity": 3}, ["0.0"]))
        self.rejected(cancelled, step("add_to_cart", {"product_id": "B7", "quantity": 1}, ["0.0"]))
        evaluated = ["Add two of item B seven to my cart no wait two is too many"]
        self.rejected(evaluated, step("add_to_cart", {"product_id": "B7", "quantity": 2}, ["0.0"]))
        corrected = ["Add two of item B seven to my cart no wait just one"]
        self.accepted(corrected, step("add_to_cart", {"product_id": "B7", "quantity": 1}, ["0.0"]))
        self.rejected(corrected, step("add_to_cart", {"product_id": "B7", "quantity": 2}, ["0.0"]))

    def test_negated_value_is_not_a_restatement(self):
        texts = ["Book the flight for John no wait not for John, for Jane"]
        ids = [row["clause_id"] for row in turn_clauses([(0, texts[0])])]
        self.accepted(texts, step("book_flight", {"passenger_name": "Jane"}, ids))
        self.rejected(texts, step("book_flight", {"passenger_name": "John"}, ids))

    def test_negated_identifier_and_its_correction_stay_separate(self):
        # Held-out-006 (text mode): a comma between two multi-token spellings had
        # merged them into "J44J45" and the completion step rewrote a correct J45.
        texts = ["Update my passport number to J four four, no wait, not J four four, J four five."]
        ids = [row["clause_id"] for row in turn_clauses([(0, texts[0])])]
        self.accepted(texts, step("update_identity_doc", {"doc_type": "passport", "doc_number": "J45"}, ids))
        for wrong in ("J44", "J44J45"):
            self.rejected(texts, step("update_identity_doc", {"doc_type": "passport", "doc_number": wrong}, ids))

    def test_first_turn_instead_is_the_current_state(self):
        # Public cases 48/53: "...so it pulls from the savings instead" with no earlier turn
        # naming the action replaces the current setting, not an earlier request.
        self.accepted(["Switch my mortgage autopay to savings instead."],
                      step("modify_autopay", {"bill_type": "mortgage", "source_account": "savings"}, ["0.0"]))

    def test_value_stated_before_a_pronoun_command(self):
        # Public cases 81/98: the document type is stated in a cited clause before the verb.
        texts = ["Oh yeah, so my new passport number is P88990011. Could you update that in the system for me, please?"]
        ids = [row["clause_id"] for row in turn_clauses([(0, texts[0])])]
        self.accepted(texts, step("update_identity_doc", {"doc_type": "passport", "doc_number": "P88990011"}, ids))
        self.rejected(texts, step("update_identity_doc", {"doc_type": "visa", "doc_number": "P88990011"}, ids))

    def test_possessive_names_the_document(self):
        texts = ["The new driver's license number is D-L-5-5-5. Could you swap out the old one and put this new one in there?"]
        ids = [row["clause_id"] for row in turn_clauses([(0, texts[0])])]
        self.accepted(texts, step("update_identity_doc", {"doc_type": "driver_license", "doc_number": "DL555"}, ids))
        letters_only = ["The new driver's license number is DL.", "Could you swap out the old one and put this new one in there?"]
        ids = [row["clause_id"] for row in turn_clauses(list(enumerate(letters_only)))]
        self.rejected(letters_only, step("update_identity_doc", {"doc_type": "driver_license", "doc_number": "DL"}, ids))
        spoken_dash = ["The new driver license number is D-L-5. dash 5, dash 5. Could you update it?"]
        ids = [row["clause_id"] for row in turn_clauses([(0, spoken_dash[0])])]
        self.rejected(spoken_dash, step("update_identity_doc", {"doc_type": "driver_license", "doc_number": "DL5"}, ids))

    def test_politeness_hedge_is_not_a_condition(self):
        texts = ["Could you track order G G five? Then process a refund for it if possible.",
                 "And also, while we're at it, add item X one to my cart."]
        self.accepted(texts, step("add_to_cart", {"product_id": "X1", "quantity": 1},
                                  [clause(texts, "and also,"), clause(texts, "while we're at it,"),
                                   clause(texts, "add item x one to my cart.")]))
        self.rejected(["Add item X one to my cart if it is in stock."],
                      step("add_to_cart", {"product_id": "X1", "quantity": 1}, ["0.0"]))

    def test_polite_prefix_of_a_real_condition_keeps_the_condition(self):
        for condition in ("if you can get free shipping", "if you could deliver it tomorrow",
                          "if you can find it under fifty dollars", "if possible without a delivery fee"):
            text = "Add item B seven to my cart " + condition + "."
            proposal = step("add_to_cart", {"product_id": "B7", "quantity": 1}, ["0.0"])
            with self.subTest(text=text):
                self.assertIsNone(authorization_grant(proposal, CART, [(0, text)]))

    def test_standalone_politeness_hedges_still_authorize(self):
        for text in ("Add item B seven to my cart if you can.",
                     "Add item B seven to my cart if possible.",
                     "If you can, add item B seven to my cart.",
                     "If you don't mind, add item B seven to my cart."):
            ids = [row["clause_id"] for row in turn_clauses([(0, text)])]
            with self.subTest(text=text):
                self.accepted([text], step("add_to_cart", {"product_id": "B7", "quantity": 1}, ids))

    def test_value_from_a_pending_lookup_waits_for_the_follow_up(self):
        # Public case 27: "search for cat food ... and add three of whatever you find" proposed
        # the add beside the search; the product id is not in the user's words yet.
        from types import SimpleNamespace
        texts = ["Search for cat food and add three of whatever you find to my cart."]
        proposal = step("add_to_cart", {"product_id": "PROD1", "quantity": 3}, ["0.0"])
        pending = {"operation-1": {"operation_id": "operation-1", "call_id": "call-1", "api_name": "search_products",
                                   "args": {"query": "cat food"}, "kind": "read_only", "status": "pending",
                                   "request_start": 0, "revision": 0}}
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.tools = deepcopy(TOOLS)
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": texts[0], "end_of_turn": True}}]
        agent.operations = deepcopy(pending)
        agent.planner = SimpleNamespace(follow_up_rounds=2)
        agent._dispatch(deepcopy(proposal))
        actions = [agent.out_queue.get_nowait()["action"] for _ in range(agent.out_queue.qsize())]
        self.assertEqual(actions, ["write_deferred"])
        # Without a pending lookup (or without follow-up rounds) it is still a refusal.
        self.rejected(texts, proposal)

    def test_command_in_an_uncited_clause_inside_the_cited_span(self):
        # Public case 22 (run 18db0ad9): the citation skipped the clause holding the verb.
        texts = ["Search for a tablet. And add two of item T one to the cart. Actually no, no, just one, just one."]
        rows = turn_clauses([(0, texts[0])])
        cited = [rows[0]["clause_id"], rows[-1]["clause_id"]]
        self.accepted(texts, step("add_to_cart", {"product_id": "T1", "quantity": 1}, cited))
        # The span still carries its retraction: the retracted count is refused end to end.
        self.rejected(texts, step("add_to_cart", {"product_id": "T1", "quantity": 2}, cited))

    def test_refused_step_does_not_cancel_the_rest_of_the_plan(self):
        # Public case 28 (run 18db0ad9): a write refused before the search stopped the search.
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.tools = deepcopy({**TOOLS, "search_products": {"kind": "read_only", "description": "Search products.",
                                                            "args": {"query": {"type": "string", "required": True}}}})
        agent.messages = [{"event_type": "user_speech_chunk",
                           "payload": {"text": "Don't add item Q one. Search for cat food.", "end_of_turn": True}}]
        agent.operations = {}
        agent._dispatch_plan([step("add_to_cart", {"product_id": "Q1", "quantity": 1}, ["0.0"]),
                              {"api_name": "search_products", "args": {"query": "cat food"}}])
        actions = [agent.out_queue.get_nowait()["action"] for _ in range(agent.out_queue.qsize())]
        self.assertEqual(actions, ["tool_call", "clarification_request"], actions)

    def test_refused_prerequisite_cannot_authorize_an_only_then_write(self):
        for dependency, expected_calls in (("Only then", []), ("Separately,", ["book_flight"])):
            text = "Update my passport number to P77 first. " + dependency + " book the flight for Maya Chen."
            rows = turn_clauses([(0, text)])
            agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
            agent.tools = deepcopy(TOOLS)
            agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": text, "end_of_turn": True}}]
            agent._dispatch_plan([
                step("update_identity_doc", {"doc_type": "passport", "doc_number": "P78"}, [rows[0]["clause_id"]]),
                step("book_flight", {"passenger_name": "Maya Chen"}, [rows[-1]["clause_id"]]),
            ])
            events = [agent.out_queue.get_nowait() for _ in range(agent.out_queue.qsize())]
            with self.subTest(text=text):
                self.assertEqual([e["payload"]["api_name"] for e in events if e["action"] == "tool_call"], expected_calls)
                self.assertEqual(events[-1]["action"], "clarification_request")

    # A second command whose object is only a pronoun refers back to the first.
    def test_anaphoric_repeat_is_one_command(self):
        texts = ["I want to set my credit card autopay to pull from savings. Can you switch that over for me?"]
        self.accepted(texts, step("modify_autopay", {"bill_type": "credit_card", "source_account": "savings"}, ["0.0", "0.1"]))
        two = ["Set my credit card autopay to savings. Switch my utilities autopay to checking."]
        # Two commands in the cited span are resolved by re-citing to the one clause that
        # states this write's values; a write mixing the two requests is still refused.
        self.accepted(two, step("modify_autopay", {"bill_type": "credit_card", "source_account": "savings"}, ["0.0", "0.1"]))
        self.accepted(two, step("modify_autopay", {"bill_type": "utilities", "source_account": "checking"}, ["0.0", "0.1"]))
        self.rejected(two, step("modify_autopay", {"bill_type": "credit_card", "source_account": "checking"}, ["0.0", "0.1"]))

    def test_affirmed_predicate_filter(self):
        texts = ["Can you first update my filter so pets are allowed?"]
        cid = clause(texts, texts[0].casefold())
        self.accepted(texts, step("update_search_filter", {"filter_name": "pets_allowed", "value": "true"}, [cid]))
        negated = ["Can you first update my filter so pets are not allowed?"]
        ncid = clause(negated, negated[0].casefold())
        self.rejected(negated, step("update_search_filter", {"filter_name": "pets_allowed", "value": "true"}, [ncid]))
        # "true" needs the predicate the name states; an unrelated name does not affirm it.
        self.rejected(texts, step("update_search_filter", {"filter_name": "pool_access", "value": "true"}, [cid]))

    def test_contracted_and_asr_negators_do_not_affirm_a_filter(self):
        for negator in ("shouldn't be", "shouldnt be", "wouldn't be", "couldn't be",
                        "wasn't", "weren't", "isnt", "arent", "cannot be", "mustn't be"):
            text = "Update my filter so pets " + negator + " allowed."
            with self.subTest(text=text):
                self.assertFalse(_said_as_phrase("pets_allowed", text))
                self.rejected([text], step("update_search_filter", {"filter_name": "pets_allowed", "value": "true"},
                                           ["0.0"]))

    def test_affirmative_phrase_gaps_and_possessives_remain_supported(self):
        for text in ("pets are allowed", "pets should be allowed", "pets must be allowed"):
            self.assertTrue(_said_as_phrase("pets_allowed", text), text)
        self.assertTrue(_said_as_phrase("driver_license", "my driver's license"))

    def test_naming_a_filter_does_not_assign_true_to_it(self):
        for name, text in (("max_price", "Update my max price to 1500."),
                           ("pool_access", "Update my filter so pool access is unavailable."),
                           ("pets_allowed", "Update my filter so pets are rarely allowed."),
                           ("pets_allowed", "Update my filter so no pets are allowed.")):
            args = {"filter_name": name, "value": "true"}
            with self.subTest(text=text):
                self.assertFalse(_affirmed_predicate(args, "value", text))
                self.rejected([text], step("update_search_filter", args, ["0.0"]))

    def test_explicit_true_and_affirmative_predicates_still_work(self):
        for text in ("Update my pool access filter value to true.",
                     "Update my pool access filter value to yes."):
            value = "yes" if "yes" in text else "true"
            self.accepted([text], step("update_search_filter", {"filter_name": "pool_access", "value": value}, ["0.0"]))
        for text in ("Update my filter so pets are allowed.", "Update my filter so pets should be allowed."):
            self.accepted([text], step("update_search_filter", {"filter_name": "pets_allowed", "value": "true"}, ["0.0"]))

    def test_snake_case_value_said_as_words_names_the_target(self):
        texts = ["So first I want to update my max price to 1500 because I'm on a tighter budget."]
        self.accepted(texts, step("update_search_filter", {"filter_name": "max_price", "value": "1500"}, ["0.0"]))

    def test_a_number_fragment_is_not_the_stated_filter_value(self):
        for amount, wrong in (("50.5", "50"), ("50.5", "5"), ("-50", "50"),
                              ("fifty point five", "50"), ("fifty point five", "5"), ("minus fifty", "50")):
            text = "Update my max price to " + amount + "."
            with self.subTest(text=text, wrong=wrong):
                self.rejected([text], step("update_search_filter", {"filter_name": "max_price", "value": wrong}, ["0.0"]))

    def test_complete_numeric_filter_values_still_work(self):
        for amount, value in (("50.5", "50.5"), ("fifty point five", "50.5"), ("fifteen hundred", "1500"),
                              ("1,500", "1500"), ("twenty-five", "25")):
            text = "Update my max price to " + amount + "."
            ids = [row["clause_id"] for row in turn_clauses([(0, text)])]
            with self.subTest(text=text):
                self.accepted([text], step("update_search_filter", {"filter_name": "max_price", "value": value}, ids))

    # Conditions scope their own sentence.
    def test_self_contained_condition_elsewhere_does_not_scope_this_action(self):
        texts = ["Search flights to Vegas and once you find something book it for Quinn Davis.",
                 "Oh and while you're at it, could you update my visa number to V77?"]
        visa = clause(texts, "could you update my visa number to v77?")
        self.accepted(texts, step("update_identity_doc", {"doc_type": "visa", "doc_number": "V77"}, [visa]))
        own_plan = ["Can you first update my filter so pets are allowed?",
                    "Then search in Seattle and once you find something I'll check the commute."]
        self.accepted(own_plan, step("update_search_filter", {"filter_name": "pets", "value": "allowed"},
                                     [clause(own_plan, "can you first update my filter so pets are allowed?")]))

    def test_conditions_that_can_scope_this_action_still_refuse(self):
        dangling = ["If the rate is good.", "Change my mortgage autopay to savings."]
        self.rejected(dangling, step("modify_autopay", {"bill_type": "mortgage", "source_account": "savings"},
                                     [clause(dangling, "change my mortgage autopay to savings.")]))
        pro_verb = ["Book the flight for Jane.", "If it's under 300, do it."]
        self.rejected(pro_verb, step("book_flight", {"passenger_name": "Jane"}, [clause(pro_verb, "book the flight for jane.")]))
        names_action = ["Book the flight for Jane.", "Actually if it's over 300, don't book it."]
        self.rejected(names_action, step("book_flight", {"passenger_name": "Jane"},
                                         [clause(names_action, "book the flight for jane.")]))
        same_sentence = ["Change my mortgage autopay to savings if the rate is good."]
        self.rejected(same_sentence, step("modify_autopay", {"bill_type": "mortgage", "source_account": "savings"}, ["0.0"]))

    def test_adverbs_and_nouns_do_not_turn_a_condition_into_its_own_request(self):
        for condition in ("If you just find it in stock.", "If you can actually find it in stock.",
                          "If you already see it in stock.", "If you have a watch."):
            text = condition + " Add item B seven to my cart."
            ids = [turn_clauses([(0, text)])[-1]["clause_id"]]
            with self.subTest(text=text):
                self.assertIsNone(authorization_grant(step("add_to_cart", {"product_id": "B7", "quantity": 1}, ids),
                                                      CART, [(0, text)]))

    def test_adverb_in_an_independent_consequent_stays_local(self):
        text = "If you find a flight, then just book it for Dana Reed. Add item B seven to my cart."
        ids = [turn_clauses([(0, text)])[-1]["clause_id"]]
        self.accepted([text], step("add_to_cart", {"product_id": "B7", "quantity": 1}, ids))

    # "Once you find something, book it": waits for this request's own lookup.
    def test_own_lookup_dependency(self):
        texts = ["Search flights to Vegas and once you find something book it for Quinn Davis."]
        proposal = step("book_flight", {"passenger_name": "Quinn Davis"}, ["0.0"])
        trace = []
        self.assertIsNone(authorization_grant(proposal, BOOK, [(0, texts[0])], trace=trace))
        self.assertTrue(trace[0].startswith("awaiting own lookup"), trace)
        self.assertTrue(authorization_grant(proposal, BOOK, [(0, texts[0])], lookup_done=True))
        # A qualified condition is not a bare dependency, even after a lookup.
        qualified = ["Search flights to Vegas and once you find one under 300 book it for Quinn Davis."]
        self.assertIsNone(authorization_grant(step("book_flight", {"passenger_name": "Quinn Davis"}, ["0.0"]),
                                              BOOK, [(0, qualified[0])], lookup_done=True))

    def test_interjection_after_a_name_is_not_a_longer_name(self):
        texts = ["Then go ahead and book the cheapest option the name on the ticket should be Casey Lee oh and I almost forgot"]
        self.accepted(texts, step("book_flight", {"passenger_name": "Casey Lee"}, ["0.0"]))


if __name__ == "__main__":
    unittest.main()


class SchemaExampleGuardTests(unittest.TestCase):
    FLIGHTS = {"kind": "read_only", "description": "Search for flights.",
               "args": {"destination": {"type": "string", "required": True, "description": "City name, e.g. 'London' or 'LHR'"},
                        "date": {"type": "string", "required": True, "description": "Travel date, e.g. '2026-08-20'"}}}
    PRODUCTS = {"kind": "read_only", "description": "Search products.",
                "args": {"query": {"type": "string", "required": True, "description": "Product search term, e.g. 'headphones'"}}}

    def run_step(self, text, api, args):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.tools = {"search_flights": deepcopy(self.FLIGHTS), "search_products": deepcopy(self.PRODUCTS)}
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": text, "end_of_turn": True}}]
        agent._dispatch({"api_name": api, "args": args, "response_template": "ok"})
        actions = []
        while not agent.out_queue.empty():
            actions.append(agent.out_queue.get_nowait()["action"])
        return actions

    def test_copied_contract_example_is_not_looked_up(self):
        # Public-run shapes: benefits question -> search_flights(London, 2026-08-20); keyboard -> "headphones".
        self.assertEqual(self.run_step("What are the benefits of the travel card?", "search_flights",
                                       {"destination": "London", "date": "2026-08-20"}), ["clarification_request"])
        self.assertEqual(self.run_step("I want a mechanical keyboard under $200.", "search_products",
                                       {"query": "headphones"}), ["clarification_request"])

    def test_example_value_the_user_said_is_looked_up(self):
        self.assertEqual(self.run_step("Find me flights to London on August twentieth.", "search_flights",
                                       {"destination": "London", "date": "2026-08-20"}), ["tool_call"])
        self.assertEqual(self.run_step("Search for noise cancelling headphones.", "search_products",
                                       {"query": "headphones"}), ["tool_call"])
        self.assertEqual(self.run_step("Find flights to Denver.", "search_flights",
                                       {"destination": "Denver", "date": "2026-08-20"}), ["tool_call"])


class SegmentSplitSpellingTests(unittest.TestCase):
    def test_letters_then_digits_across_a_segment_break_is_one_spelling(self):
        from participant.authorization import spelled_runs
        self.assertIn("dl555", spelled_runs("The new driver's license number is DL. 555. Could you swap out the old one?"))
        # Only letters-then-digits with a bare sentence break; prose words never join.
        self.assertNotIn("is555", spelled_runs("My number is. 555 people came."))
        self.assertNotIn("dl555", spelled_runs("The number is DL, and 555 people came."))
        self.assertEqual(spelled_runs("It was the end. 42 people came."), set())

    def test_split_spelling_authorizes_only_its_exact_value(self):
        texts = ["The new driver's license number is DL.", "555.", "Could you swap out the old one and put this new one in there?"]
        cited = [row["clause_id"] for row in turn_clauses(list(enumerate(texts)))]
        gate = GateV2Tests()
        gate.accepted(texts, step("update_identity_doc", {"doc_type": "driver_license", "doc_number": "DL555"}, cited))
        gate.rejected(texts, step("update_identity_doc", {"doc_type": "driver_license", "doc_number": "DL556"}, cited))


class QualifiedResultIdentifierTests(unittest.TestCase):
    COMMUTE = {"kind": "read_only", "description": "Calculate commute duration.",
               "args": {"origin_address": {"type": "string", "required": True},
                        "destination_address": {"type": "string", "required": True},
                        "mode": {"type": "string", "required": False, "default": "driving"}}}
    SEARCH = {"kind": "read_only", "description": "Search apartments.", "args": {"city": {"type": "string", "required": True}}}

    def run_step(self, tools, text, step, result):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.tools = deepcopy(tools)
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": text, "end_of_turn": True}}]
        agent.operations = {"call-1": {"call_id": "call-1", "operation_id": "operation-1", "api_name": "search_apartments",
                                       "args": {"city": "Portland"}, "kind": "read_only", "request_start": 0,
                                       "revision": agent.revision, "status": "success", "result": result,
                                       "key": "k", "step": {}, "retry": 0, "depth": 0, "selection": None}}
        agent._dispatch(step)
        actions = []
        while not agent.out_queue.empty():
            actions.append(agent.out_queue.get_nowait())
        return [a["action"] for a in actions], actions

    def test_lookup_may_qualify_a_returned_identifier(self):
        result = {"status": "success", "results": [{"id": "APT1", "price": 700}]}
        text = "Search Portland, then check how long it takes to bike from there to the coffee shop."
        step = {"api_name": "calculate_commute", "response_template": "ok",
                "args": {"origin_address": "APT1, Portland", "destination_address": "coffee shop", "mode": "biking"},
                "result_bindings": {"origin_address": {"call_id": "call-1", "path": "results.0.id"}}}
        actions, events = self.run_step({"calculate_commute": self.COMMUTE, "search_apartments": self.SEARCH}, text, step, result)
        self.assertEqual(actions, ["tool_call"], events)
        step["args"]["origin_address"] = "APT12, Portland"  # not the returned identifier
        actions, events = self.run_step({"calculate_commute": self.COMMUTE, "search_apartments": self.SEARCH}, text, step, result)
        self.assertEqual(actions, ["clarification_request"], events)


class BorrowedResultIdentifierTests(unittest.TestCase):
    TRACK = {"kind": "read_only", "description": "Track an order.", "args": {"order_id": {"type": "string", "required": True}}}

    def actions(self, text, order_id, result):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.tools = {"track_order": deepcopy(self.TRACK)}
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": text, "end_of_turn": True}}]
        agent.operations = {"call-1": {"call_id": "call-1", "operation_id": "operation-1", "api_name": "search_apartments",
                                       "args": {"city": "Dallas"}, "kind": "read_only", "status": "success", "result": result,
                                       "request_start": 0, "revision": agent.revision, "key": "k", "step": {},
                                       "retry": 0, "depth": 0, "selection": None}}
        agent._dispatch({"api_name": "track_order", "args": {"order_id": order_id}, "response_template": "ok"})
        out = []
        while not agent.out_queue.empty():
            out.append(agent.out_queue.get_nowait()["action"])
        return out

    def test_identifier_from_another_tool_is_not_an_unsaid_order_number(self):
        result = {"status": "success", "results": [{"id": "APT1", "price": 1400}]}
        self.assertEqual(self.actions("Check the walking time from whatever you find to the grocery store.", "APT1", result),
                         ["clarification_request"])
        # Said by the user, it is looked up.
        self.assertEqual(self.actions("Please track order APT1.", "APT1", result), ["tool_call"])
        self.assertEqual(self.actions("Track order Q7 for me.", "Q7", result), ["tool_call"])


class RecitationTests(unittest.TestCase):
    def run_two(self, texts, second_args):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.tools = deepcopy(TOOLS)
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": t, "end_of_turn": i == len(texts) - 1}}
                          for i, t in enumerate(texts)]
        first = clause(texts, texts[0].casefold())
        agent._dispatch(step("modify_autopay", {"bill_type": "mortgage", "source_account": "savings"}, [first]))
        agent._dispatch(step("modify_autopay", second_args, [first]))  # planner re-used the first clause
        actions = []
        while not agent.out_queue.empty():
            event = agent.out_queue.get_nowait()
            actions.append((event["action"], event["payload"].get("args")))
        return actions

    def test_second_write_is_recited_to_its_own_clause(self):
        texts = ["I want to change my mortgage autopay so it pulls from savings.",
                 "I also want to set my credit card payment to come from my checking."]
        actions = self.run_two(texts, {"bill_type": "credit_card", "source_account": "checking"})
        self.assertEqual([a for a, _ in actions], ["tool_call", "tool_call"])
        self.assertEqual(actions[1][1], {"bill_type": "credit_card", "source_account": "checking"})

    def test_recitation_still_passes_every_check(self):
        for later in ("I might also set my credit card payment to come from my checking.",
                      "Don't set my credit card payment to come from my checking."):
            texts = ["I want to change my mortgage autopay so it pulls from savings.", later]
            with self.subTest(later=later):
                actions = self.run_two(texts, {"bill_type": "credit_card", "source_account": "checking"})
                # The hedge or negation keeps the whole turn conservative; no credit-card write either way.
                self.assertNotIn(("tool_call", {"bill_type": "credit_card", "source_account": "checking"}), actions)
        texts = ["I want to change my mortgage autopay so it pulls from savings.", "My credit card is fine as it is."]
        actions = self.run_two(texts, {"bill_type": "credit_card", "source_account": "checking"})
        self.assertEqual([a for a, _ in actions], ["tool_call", "clarification_request"])


class RecitationDuplicateTests(unittest.TestCase):
    def test_recitation_never_repeats_an_already_dispatched_write(self):
        texts = ["Add item J nine to my cart. Add item K two to my cart."]
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.tools = deepcopy(TOOLS)
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": texts[0], "end_of_turn": True}}]
        agent._dispatch(step("add_to_cart", {"product_id": "J9", "quantity": 1}, ["0.0"]))
        agent._dispatch(step("add_to_cart", {"product_id": "J9", "quantity": 1}, ["0.1"]))  # a second J9
        actions = []
        while not agent.out_queue.empty():
            event = agent.out_queue.get_nowait()
            actions.append((event["action"], (event["payload"].get("args") or {}).get("product_id")))
        self.assertEqual([a for a in actions if a[0] == "tool_call"], [("tool_call", "J9")])


class RecitationMultiCommandTests(unittest.TestCase):
    def actions(self, text, args, cited):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.tools = deepcopy(TOOLS)
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": text, "end_of_turn": True}}]
        agent._dispatch(step("update_identity_doc", args, cited))
        out = []
        while not agent.out_queue.empty():
            out.append(agent.out_queue.get_nowait()["action"])
        return out

    def test_each_write_uses_its_own_command_clause(self):
        text = ("Update my passport number to P one one two two because I renewed it, "
                "and change my driver license number to D L nine zero nine zero.")
        every = [row["clause_id"] for row in turn_clauses([(0, text)])]
        self.assertEqual(self.actions(text, {"doc_type": "driver_license", "doc_number": "DL9090"}, every), ["tool_call"])
        self.assertEqual(self.actions(text, {"doc_type": "passport", "doc_number": "P1122"}, every), ["tool_call"])
        # A value stated nowhere is still refused.
        self.assertEqual(self.actions(text, {"doc_type": "visa", "doc_number": "V77"}, every), ["clarification_request"])


class RecitationPredicateTests(unittest.TestCase):
    def actions(self, text, args):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.tools = deepcopy(TOOLS)
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": text, "end_of_turn": True}}]
        every = [row["clause_id"] for row in turn_clauses([(0, text)])]
        agent._dispatch(step("update_search_filter", args, every))
        out = []
        while not agent.out_queue.empty():
            out.append(agent.out_queue.get_nowait()["action"])
        return out

    def test_affirmed_filter_is_recited_out_of_a_multi_command_span(self):
        text = "First set the filter so pets are allowed, and set the max price to 3,000."
        self.assertEqual(self.actions(text, {"filter_name": "pets_allowed", "value": "true"}), ["tool_call"])
        negated = "First set the filter so pets are not allowed, and set the max price to 3,000."
        self.assertEqual(self.actions(negated, {"filter_name": "pets_allowed", "value": "true"}), ["clarification_request"])


class CommandSelectionTests(unittest.TestCase):
    def test_the_command_whose_stretch_states_the_values_is_chosen(self):
        text = ("First set the filter so pets are allowed and set the max price to 3,000, then search for places. "
                "Wait, actually change the max price to 3500 instead.")
        every = [row["clause_id"] for row in turn_clauses([(0, text)])]
        gate = GateV2Tests()
        gate.accepted([text], step("update_search_filter", {"filter_name": "max_price", "value": "3500"}, every))
        # The later "wait, actually ... instead" restates the max price, which the cited request
        # also named, and never the pets write, so re-citation leaves the pets write standing ...
        gate.accepted([text], step("update_search_filter", {"filter_name": "pets_allowed", "value": "true"}, every))
        # ... while a correction that names no other cited target still voids the earlier command.
        swap = "Add J9 to my cart. Wait, add K2 instead."
        gate.rejected([swap], step("add_to_cart", {"product_id": "J9", "quantity": 1}, ["0.0"]))
        plain = "First set the filter so pets are allowed and set the max price to 3,000."
        plain_every = [row["clause_id"] for row in turn_clauses([(0, plain)])]
        gate.accepted([plain], step("update_search_filter", {"filter_name": "pets_allowed", "value": "true"}, plain_every))
        gate.accepted([plain], step("update_search_filter", {"filter_name": "max_price", "value": "3000"}, plain_every))
        # The superseded 3,000 and a value in no stretch stay refused.
        gate.rejected([text], step("update_search_filter", {"filter_name": "max_price", "value": "3000"}, every))
        gate.rejected([text], step("update_search_filter", {"filter_name": "min_bedrooms", "value": "3"}, every))
