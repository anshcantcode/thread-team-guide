import unittest
from copy import deepcopy
from thread_agent.fdb3 import normalize_read_identifiers, spelled_identifier


class IdentifierTests(unittest.TestCase):
    def test_spelling_and_explicit_separator(self):
        self.assertEqual(spelled_identifier("R, Q, 7, 4"),"RQ74")
        self.assertEqual(spelled_identifier("Z dash 8"),"Z-8")
        self.assertEqual(spelled_identifier("J underscore 6"),"J_6")

    def test_prose_numeric_lists_and_existing_ids_unchanged(self):
        for value in ("North annex", "17, 24", "R7-22", "red, green", "RJ, 72", "R dot 7", "R, Q,", ""):
            self.assertEqual(spelled_identifier(value),value)

    def test_only_identifier_reads_are_normalized_and_slots_follow(self):
        decision = {"slots":{"parcel_id":"M, 4"},"tool_calls":[{"api_name":"lookup", "args":{"parcel_id":"M, 4","query":"P, 8"}}]}
        tools={"lookup":{"kind":"read_only","args":{"parcel_id":{"type":"string"},"query":{"type":"string"}}}}
        actual=normalize_read_identifiers(deepcopy(decision),{"tools":tools})
        self.assertEqual(actual["slots"]["parcel_id"],"M4")
        self.assertEqual(actual["tool_calls"][0]["args"]["query"],"P, 8")
        tools["lookup"]["kind"]="state_modifying"
        self.assertEqual(normalize_read_identifiers(deepcopy(decision),{"tools":tools}),decision)

    def test_explicit_literal_punctuation_is_preserved(self):
        decision={"tool_calls":[{"api_name":"lookup","args":{"parcel_id":"M, 4"}}]}
        context={"tools":{"lookup":{"kind":"read_only","args":{"parcel_id":{}}}},
                 "messages":[{"payload":{"text":"Use the literal identifier M, 4, including the comma."}}]}
        self.assertEqual(normalize_read_identifiers(deepcopy(decision),context),decision)


if __name__ == "__main__": unittest.main()
