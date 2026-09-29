"""The copied-contract-example guard; invented example values only."""
import unittest

from participant.agent import ParticipantAgent

TRACK = {"kind": "read_only", "description": "Track a parcel.",
         "args": {"order_id": {"type": "string", "required": True,
                               "description": "Order identifier to track (e.g. 'KLM34')"}}}


def copied(texts, value):
    agent = ParticipantAgent.__new__(ParticipantAgent)
    agent.operations, agent.tools = {}, {"track_order": TRACK}
    agent._user_texts = lambda: texts
    return agent._copied_schema_example(TRACK, {"order_id": value}, "track_order")


class CopiedExampleTests(unittest.TestCase):
    def test_an_unsaid_contract_example_is_a_copy(self):
        self.assertTrue(copied([(1, "Can you track my order please?")], "KLM34"))

    def test_the_example_said_plainly_or_spelled_across_segments_is_the_users(self):
        self.assertFalse(copied([(1, "Track order KLM34.")], "KLM34"))
        self.assertFalse(copied([(1, "So can you track order?"), (2, "K-L-M-3-4 for me,")], "KLM34"))
        self.assertFalse(copied([(1, "Track order K, L, M, three, four.")], "KLM34"))


if __name__ == "__main__":
    unittest.main()
