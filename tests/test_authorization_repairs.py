"""Write-gate repairs: re-cited values keep their own cited command, stuttered commands
count once, and a participle key said in its active form ("allow pets") is grounded.

Invented tools and sentences; no benchmark recordings, labels or scenario text.
"""
import asyncio
from copy import deepcopy
import unittest

from participant.agent import ParticipantAgent, _affirmed_predicate, _said_as_phrase, _verb_object_pattern
from participant.authorization import authorization_grant, turn_clauses

TOOLS = {
    "search_goods": {"kind": "read_only", "description": "Search the catalog.", "args": {
        "query": {"type": "string", "required": True, "description": "What to look for"},
        "max_price": {"type": "number", "required": False, "description": "Price ceiling"}}},
    "track_parcel": {"kind": "read_only", "description": "Track a parcel.", "args": {
        "parcel_id": {"type": "string", "required": True, "description": "Parcel identifier"}}},
    "update_library_card": {"kind": "state_modifying", "description": "Update library card details.", "args": {
        "card_number": {"type": "string", "required": True, "description": "The library card identifier"}}},
    "add_to_basket": {"kind": "state_modifying", "description": "Add an item to the basket.", "args": {
        "item_id": {"type": "string", "required": True, "description": "ID of the item"}}},
    "update_alert_setting": {"kind": "state_modifying", "description": "Update an alert setting.", "args": {
        "setting_name": {"type": "string", "required": True, "description": "Setting key to change"},
        "value": {"type": "string", "required": True, "description": "Setting value"}}},
}


def run(texts, step):
    agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
    agent.tools = deepcopy(TOOLS)
    agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": text}} for text in texts]
    agent._dispatch(deepcopy(step))
    events = []
    while not agent.out_queue.empty():
        events.append(agent.out_queue.get_nowait())
    return events


def calls(events):
    return [(e["payload"]["api_name"], e["payload"]["args"]) for e in events if e["action"] == "tool_call"]


class RecitedValueKeepsItsCitedCommand(unittest.TestCase):
    TEXT = "My new library card number is K77. Could you swap out the old one and put this new one on file?"

    def test_value_stated_before_the_cited_command_is_written(self):
        events = run([self.TEXT], {"api_name": "update_library_card", "args": {"card_number": "K77"},
                                   "authorization": {"clauses": ["0.1"]}})
        self.assertEqual(calls(events), [("update_library_card", {"card_number": "K77"})])

    def test_recitation_never_borrows_an_uncited_command(self):
        texts = [(0, self.TEXT)]
        clauses = turn_clauses(texts)
        value_clause = next(row["clause_id"] for row in clauses if "k77" in row["text"])
        step = {"api_name": "update_library_card", "args": {"card_number": "K77"},
                "authorization": {"clauses": [value_clause]}}
        trace = []
        # Attachment limited to a clause the proposal never cited: refused.
        self.assertIsNone(authorization_grant(step, TOOLS["update_library_card"], texts, trace=trace,
                                              allow_attachment=frozenset({"9.9"})))
        self.assertEqual(trace, ["no command verb in or before the cited clauses"])
        # No attachment at all (the earlier rule): refused.
        self.assertIsNone(authorization_grant(step, TOOLS["update_library_card"], texts, allow_attachment=False))

    def test_a_status_question_cannot_lend_a_command(self):
        events = run(["My new library card number is K77. What does the old one say?"],
                     {"api_name": "update_library_card", "args": {"card_number": "K77"},
                      "authorization": {"clauses": ["0.0"]}})
        self.assertEqual(calls(events), [])


class RepeatedCommandCountsOnce(unittest.TestCase):
    def test_stuttered_command_is_one_command(self):
        texts = ["Item Q4 to my basket.", "Add to basket, add to basket, add to basket."]
        events = run(texts, {"api_name": "add_to_basket", "args": {"item_id": "Q4"},
                             "authorization": {"clauses": ["0.0", "1.0", "1.1", "1.2"]}})
        self.assertEqual(calls(events), [("add_to_basket", {"item_id": "Q4"})])

    def test_different_commands_are_not_collapsed(self):
        texts = ["Add Q4 to my basket, add Q5 to my basket."]
        step = {"api_name": "add_to_basket", "args": {"item_id": "Q6"},
                "authorization": {"clauses": ["0.0", "0.1"]}}
        self.assertEqual(calls(run(texts, step)), [])


class ParticipleKeyInActiveForm(unittest.TestCase):
    def test_active_form_grounds_a_participle_key(self):
        self.assertTrue(_said_as_phrase("pets_allowed", "show me places that allow pets"))
        self.assertTrue(_said_as_phrase("pets_allowed", "somewhere that allows my pet"))
        self.assertTrue(_said_as_phrase("smoking_permitted", "hotels that permit smoking"))
        self.assertTrue(_said_as_phrase("parking_required", "I require parking"))
        # The original in-order copular form still counts.
        self.assertTrue(_said_as_phrase("pets_allowed", "pets are allowed"))

    def test_negated_or_unrelated_forms_do_not(self):
        self.assertFalse(_said_as_phrase("pets_allowed", "places that don't allow pets"))
        self.assertFalse(_said_as_phrase("pets_allowed", "never allow pets"))
        self.assertFalse(_said_as_phrase("pets_allowed", "allow me to see the pool"))
        self.assertIsNone(_verb_object_pattern("max_price"))
        self.assertIsNone(_verb_object_pattern("allowed"))

    def test_true_value_affirmed_by_active_form_only(self):
        args = {"setting_name": "alerts_enabled", "value": "true"}
        self.assertTrue(_affirmed_predicate(args, "value", "just enable alerts for me"))
        self.assertFalse(_affirmed_predicate(args, "value", "please do not enable alerts"))

    def test_setting_named_in_active_form_is_written(self):
        events = run(["Could you update my alert setting so that it only enables alerts?"],
                     {"api_name": "update_alert_setting", "args": {"setting_name": "alerts_enabled", "value": "true"},
                      "authorization": {"clauses": ["0.0"]}})
        self.assertEqual(calls(events), [("update_alert_setting", {"setting_name": "alerts_enabled", "value": "true"})])


class OutrightLookupWithAConditionalFilter(unittest.TestCase):
    TEXT = ("So search for a kettle first. If you find one that's under $40, go ahead and add two to the "
            "basket. But if everything's over 40, forget the kettle and track parcel Z9 for me instead.")

    def test_outright_search_runs_with_the_threshold_folded_in(self):
        events = run([self.TEXT], {"api_name": "search_goods", "args": {"query": "kettle", "max_price": 40}})
        self.assertEqual(calls(events), [("search_goods", {"query": "kettle", "max_price": 40})])

    def test_lookup_named_only_inside_the_condition_still_waits(self):
        events = run([self.TEXT], {"api_name": "track_parcel", "args": {"parcel_id": "Z9"}})
        self.assertEqual(calls(events), [])


if __name__ == "__main__":
    unittest.main()
