"""User casing restored, conflicting heard name spellings asked about; invented wording only."""
import unittest

from participant.agent import ParticipantAgent
from thread_agent.fdb3 import restore_user_case

BOOK = {"kind": "state_modifying", "description": "Book a ticket for a passenger.",
        "args": {"passenger_name": {"type": "string", "required": True}}}


def context(text):
    return {"tools": {}, "current_turn_start": 0, "messages": [{"payload": {"text": text}}]}


def decision(args):
    return {"intent": "x", "slots": {}, "tool_calls": [{"api_name": "t", "args": dict(args)}]}


class UserCaseTests(unittest.TestCase):
    def fixed(self, args, said):
        return restore_user_case(decision(args), context(said))["tool_calls"][0]["args"]

    def test_lowercase_copy_takes_the_users_form(self):
        said = "Set my town filter to Ashford. Walk from Ashford Quay to the Old Mill."
        self.assertEqual(self.fixed({"value": "ashford", "origin": "ashford quay", "to": "the old mill"}, said),
                         {"value": "Ashford", "origin": "Ashford Quay", "to": "the Old Mill"})

    def test_planner_casing_and_unmatched_values_are_kept(self):
        said = "Set my town filter to Ashford."
        self.assertEqual(self.fixed({"value": "ASHFORD", "other": "kent"}, said), {"value": "ASHFORD", "other": "kent"})

    def test_inconsistent_surface_forms_are_left_alone(self):
        said = "Book it for rowan. Yes, Rowan."
        self.assertEqual(self.fixed({"name": "rowan"}, said), {"name": "rowan"})


class ConflictingSpellingTests(unittest.TestCase):
    def agent(self, text):
        agent = ParticipantAgent.__new__(ParticipantAgent)
        agent._user_texts = lambda: [(1, text)]
        return agent

    def test_two_near_spellings_of_the_name_ask(self):
        agent = self.agent("Sorry, the passenger is Tamsin Reyes, not Ola. Use Tamsen Reyes for the ticket.")
        self.assertIn("Which name should I use?", agent._conflicting_spelling({"passenger_name": "Tamsen Reyes"}))

    def test_a_clearly_different_retracted_name_does_not_ask(self):
        agent = self.agent("Book it for Ola Reyes. Sorry, the passenger is Tamsin Reyes, not Ola.")
        self.assertEqual(agent._conflicting_spelling({"passenger_name": "Tamsin Reyes"}), "")

    def test_non_name_fields_and_single_words_are_ignored(self):
        agent = self.agent("Use checking, I mean checkings.")
        self.assertEqual(agent._conflicting_spelling({"source_account": "checking"}), "")
        agent = self.agent("Book it for Tamsin. Tamsen.")
        self.assertEqual(agent._conflicting_spelling({"passenger_name": "Tamsin"}), "")


if __name__ == "__main__":
    unittest.main()
