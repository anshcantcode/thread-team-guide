"""Unstated required search filters require clarification, never invented values."""
import asyncio
from copy import deepcopy
import unittest

from participant.agent import ParticipantAgent
from participant.schema import unstated_search_filters
from participant.spoken import spoken_result


TOOLS = {
    "search_homes": {"kind": "read_only", "args": {
        "town": {"type": "string", "required": True},
        "rooms": {"type": "integer", "required": True},
        "ceiling": {"type": "number", "required": True}}},
    "search_catalog": {"kind": "read_only", "args": {"shelf_id": {"type": "string", "required": True},
                                                     "term": {"type": "string", "required": True}}},
    "lookup_parcel": {"kind": "read_only", "args": {"tracking": {"type": "string", "required": True},
                                                    "carrier": {"type": "string", "required": True}}},
    "reserve_locker": {"kind": "state_modifying", "description": "Reserve a locker.",
                       "args": {"person": {"type": "string", "required": True},
                                "size": {"type": "string", "required": True}}},
}


class Planner:
    async def setup(self): pass
    async def close(self): pass
    async def plan(self, context): return {"response": "No proposal."}


class SchemaTests(unittest.TestCase):
    def test_only_search_reads_with_a_stated_filter_leave_others_unspecified(self):
        self.assertEqual(unstated_search_filters("search_homes", TOOLS["search_homes"], {"town": "Leeds", "ceiling": 900}),
                         ["rooms"])
        self.assertEqual(unstated_search_filters("search_homes", TOOLS["search_homes"], {"rooms": 2}), ["town", "ceiling"])
        # Nothing stated: ask, do not run an empty search.
        self.assertEqual(unstated_search_filters("search_homes", TOOLS["search_homes"], {}), [])
        # Identifiers are never left unspecified.
        self.assertEqual(unstated_search_filters("search_catalog", TOOLS["search_catalog"], {"term": "lamps"}), [])
        # A lookup that is not a search, and any write, still need every required value.
        self.assertEqual(unstated_search_filters("lookup_parcel", TOOLS["lookup_parcel"], {"tracking": "ZX-18"}), [])
        self.assertEqual(unstated_search_filters("reserve_locker", TOOLS["reserve_locker"], {"person": "Amara"}), [])


class DispatchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue(), planner=Planner())
        self.agent.tools = deepcopy(TOOLS)
        self.agent._handle({"event_type": "user_speech_chunk",
                            "payload": {"text": "Find homes in Leeds under 900 a month.", "end_of_turn": True}})

    async def asyncTearDown(self):
        await self.agent.close()

    def actions(self):
        rows = []
        while not self.agent.out_queue.empty():
            rows.append(self.agent.out_queue.get_nowait())
        return rows

    async def test_search_with_an_unstated_required_filter_asks_without_inventing_it(self):
        self.agent._dispatch({"api_name": "search_homes", "args": {"town": "Leeds", "ceiling": 900}})
        events = self.actions()
        self.assertFalse([event for event in events if event["action"] == "tool_call"])
        clarification = [event for event in events if event["action"] == "clarification_request"]
        self.assertEqual(len(clarification), 1)
        self.assertIn("args.rooms: missing required argument", clarification[0]["payload"]["text"])

    async def test_numbers_of_other_requests_cannot_supply_an_unstated_required_filter(self):
        self.agent._handle({"event_type": "user_speech_chunk", "payload": {"text":
            "Find homes in Leeds under 900. Then check the drive to my office. If it's over 15 minutes, "
            "raise my ceiling to 1200.", "end_of_turn": True}})
        self.agent._dispatch({"api_name": "search_homes", "args": {"town": "Leeds", "ceiling": 900}})
        events = self.actions()
        self.assertFalse([event for event in events if event["action"] == "tool_call"])
        clarification = [event for event in events if event["action"] == "clarification_request"]
        self.assertEqual(len(clarification), 1)
        self.assertIn("args.rooms: missing required argument", clarification[0]["payload"]["text"])

    async def test_an_unused_number_in_the_search_sentence_still_needs_repair(self):
        self.agent._handle({"event_type": "user_speech_chunk", "payload": {"text":
            "Find two homes in York under 700.", "end_of_turn": True}})
        self.agent._dispatch({"api_name": "search_homes", "args": {"town": "York", "ceiling": 700}})
        self.assertFalse([e for e in self.actions() if e["action"] == "tool_call"])

    async def test_non_search_lookup_still_asks_for_a_missing_value(self):
        self.agent._dispatch({"api_name": "lookup_parcel", "args": {"tracking": "ZX-18"}})
        events = self.actions()
        self.assertFalse([e for e in events if e["action"] == "tool_call"])
        self.assertTrue([e for e in events if e["action"] == "clarification_request"])


class SpokenTests(unittest.TestCase):
    def test_apartment_receipt_names_the_unspecified_filter(self):
        result = {"status": "success", "city": "Leeds", "results": [{"id": "FLAT4", "price": 800.0, "beds": None}]}
        self.assertEqual(spoken_result("search_apartments", {"city": "Leeds", "max_price": 900}, result),
                         "I searched for apartments in Leeds with a maximum monthly rent of 900, with no bedroom count "
                         "specified. I found apartment FLAT4, at a monthly rent of 800.")

    def test_receipt_falls_back_when_the_result_contradicts_an_unspecified_filter(self):
        result = {"status": "success", "city": "Leeds", "results": [{"id": "FLAT4", "price": 800.0, "beds": 2}]}
        self.assertIsNone(spoken_result("search_apartments", {"city": "Leeds", "max_price": 900}, result))


if __name__ == "__main__":
    unittest.main()
