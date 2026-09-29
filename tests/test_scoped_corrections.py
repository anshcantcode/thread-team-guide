"""Corrections of another target, and values dictated across segments; invented wording only."""
import unittest

from participant.agent import ParticipantAgent
from participant.authorization import authorization_grant

FILTER = {"kind": "state_modifying", "description": "Update a search filter.",
          "args": {"filter_name": {"type": "string", "required": True}, "value": {"type": "string", "required": True}}}
AUTOPAY = {"kind": "state_modifying", "description": "Change which account pays a bill.",
           "args": {"bill_type": {"type": "string", "required": True}, "source_account": {"type": "string", "required": True}}}
DOC = {"kind": "state_modifying", "description": "Update an identity document number.",
       "args": {"doc_type": {"type": "string", "required": True}, "doc_number": {"type": "string", "required": True}}}

TURN = [(4, "Okay, first set the filter so balconies are included and set the max rent to 2,000. "
            "Then look in Lisbon. Wait, actually change the max rent to 2400 instead. Lisbon costs more.")]


def grant(tool, args, clauses, texts=TURN):
    trace = []
    step = {"api_name": "x", "args": args, "authorization": {"clauses": clauses}}
    return authorization_grant(step, tool, texts, trace=trace), trace


class ScopedCorrectionTests(unittest.TestCase):
    def test_correction_of_another_target_leaves_this_write_standing(self):
        self.assertTrue(grant(FILTER, {"filter_name": "balconies_included", "value": "true"}, ["4.1"])[0])
        self.assertTrue(grant(FILTER, {"filter_name": "max_rent", "value": "2400"}, ["4.4"])[0])

    def test_superseded_value_is_still_voided(self):
        self.assertFalse(grant(FILTER, {"filter_name": "max_rent", "value": "2000"}, ["4.1"])[0])

    def test_pronoun_or_whole_correction_still_voids(self):
        for text in ("Move my rent autopay to checking. Wait, actually make it savings instead.",
                     "Move my rent autopay to checking. Wait, never mind.",
                     "Move my rent autopay to checking and my phone to savings. Wait, no, rent should use savings too."):
            with self.subTest(text=text):
                self.assertFalse(grant(AUTOPAY, {"bill_type": "rent", "source_account": "checking"}, ["1.0"],
                                       [(1, text)])[0])

    def test_negated_correction_naming_this_target_voids(self):
        texts = [(2, "Include balconies and set bedrooms to two. Wait, actually no balconies.")]
        self.assertFalse(grant(FILTER, {"filter_name": "balconies_included", "value": "true"}, ["2.0"], texts)[0])


class SegmentedValueTests(unittest.TestCase):
    def agent(self, texts):
        agent = ParticipantAgent.__new__(ParticipantAgent)
        agent.operations, agent.tools = {}, {"update_identity_doc": DOC}
        agent._user_texts = lambda: texts
        return agent

    def test_value_fragment_between_cited_clauses_completes_the_dictation(self):
        texts = [(3, "My new permit number is KQ."), (5, "7310."), (6, "Please swap the old one for this one.")]
        step = {"api_name": "update_identity_doc", "args": {"doc_type": "permit", "doc_number": "KQ7310"},
                "authorization": {"clauses": ["3.0", "6.0"]}}
        agent = self.agent(texts)
        self.assertEqual(agent._binding_error(step, DOC, step["args"], True, None), "")

    def test_a_worded_segment_between_citations_does_not_lend_values(self):
        texts = [(3, "My new permit number is KQ."), (5, "Actually it was 7310 before the move."),
                 (6, "Please swap the old one for this one.")]
        step = {"api_name": "update_identity_doc", "args": {"doc_type": "permit", "doc_number": "KQ7310"},
                "authorization": {"clauses": ["3.0", "6.0"]}}
        agent = self.agent(texts)
        self.assertIn("cannot invent", agent._binding_error(step, DOC, step["args"], True, None))


if __name__ == "__main__":
    unittest.main()
