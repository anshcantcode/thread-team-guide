"""Reads with the same arguments still need fresh results across requests."""
import asyncio
from copy import deepcopy
import unittest
from unittest.mock import patch

from participant.agent import ParticipantAgent


TOOL_NAME = "current_temperature"
TOOL = {
    "kind": "read_only",
    "description": "Read the current temperature.",
    "args": {"location": {"type": "string", "required": True}},
}
MANIFEST = {TOOL_NAME: TOOL}
STEP = {"api_name": TOOL_NAME, "args": {"location": "Seattle"}}


class MutableReadFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        self.agent.state = {"intent": "get_temperature", "slots": {"location": "Seattle"}}
        self.agent._handle({"event_type": "tool_manifest", "payload": {"tools": deepcopy(MANIFEST)}})

    def drain(self):
        events = []
        while not self.agent.out_queue.empty():
            events.append(self.agent.out_queue.get_nowait())
        return events

    def new_turn(self, text):
        with patch.object(self.agent, "_start_plan"):
            self.agent._handle({"event_type": "user_speech_chunk",
                                "payload": {"text": text, "end_of_turn": True}})

    def dispatch_read(self):
        self.assertTrue(self.agent._dispatch(deepcopy(STEP)))
        events = self.drain()
        calls = [event["payload"] for event in events if event["action"] == "tool_call"]
        self.assertEqual(len(calls), 1, events)
        return calls[0]

    def succeed(self, call, temperature):
        self.agent._result({
            **call,
            "status": "success",
            "result": {"status": "success", "temperature_c": temperature},
        })

    def test_same_mutable_args_dispatch_again_and_use_the_new_result(self):
        self.new_turn("Check Seattle's current temperature.")
        first = self.dispatch_read()
        self.succeed(first, 18)
        self.drain()

        self.new_turn("Read the current temperature again now.")
        second = self.dispatch_read()
        self.assertNotEqual(first["call_id"], second["call_id"])
        self.succeed(second, 23)

        self.assertEqual(self.agent.operations[second["call_id"]]["revision"], self.agent.revision)
        self.assertEqual(self.agent.operations[second["call_id"]]["result"]["temperature_c"], 23)

    def test_same_turn_duplicate_read_stays_idempotent(self):
        self.new_turn("Check Seattle's current temperature.")
        first = self.dispatch_read()
        self.succeed(first, 18)
        self.drain()

        self.assertTrue(self.agent._dispatch(deepcopy(STEP)))
        events = self.drain()

        self.assertFalse(any(event["action"] == "tool_call" for event in events))
        self.assertEqual(len(self.agent.operations), 1)
        self.assertEqual([row["call_id"] for row in self.agent.tool_results], [first["call_id"]])

    def test_late_superseded_read_cannot_supply_a_later_request(self):
        self.new_turn("Check Seattle's current temperature.")
        old = self.dispatch_read()

        self.new_turn("Read the current temperature again now.")
        current = self.dispatch_read()
        self.succeed(old, 18)
        self.drain()
        self.assertEqual(self.agent.operations[old["call_id"]]["result"]["temperature_c"], 18)
        self.assertFalse(any(row["call_id"] == old["call_id"] for row in self.agent.tool_results))

        self.new_turn("Read the current temperature once more.")
        latest = self.dispatch_read()

        self.assertNotEqual(old["call_id"], latest["call_id"])
        self.assertNotEqual(current["call_id"], latest["call_id"])
        self.assertEqual(self.agent.operations[old["call_id"]]["revision"], 1)
        self.assertEqual(self.agent.operations[latest["call_id"]]["revision"], self.agent.revision)

    def test_changed_manifest_requires_a_new_read(self):
        self.new_turn("Check Seattle's current temperature.")
        old = self.dispatch_read()
        self.succeed(old, 18)
        self.drain()

        changed_manifest = deepcopy(MANIFEST)
        changed_manifest[TOOL_NAME]["description"] = "Read the live temperature at a location."
        self.agent._handle({"event_type": "tool_manifest", "payload": {"tools": changed_manifest}})
        current = self.dispatch_read()

        self.assertNotEqual(old["call_id"], current["call_id"])
        self.assertEqual(self.agent.operations[current["call_id"]]["revision"], self.agent.revision)

    def test_updated_results_with_a_proposed_read_use_a_fresh_result(self):
        self.new_turn("Check Seattle's temperature.")
        old = self.dispatch_read()
        self.succeed(old, 18)
        self.drain()

        self.agent.state["slots"]["sort"] = "temperature"
        self.new_turn("Fetch updated results for Seattle and sort those results by temperature.")
        step = {**deepcopy(STEP), "response_template": "Sorted result: {temperature_c} C."}
        self.assertTrue(self.agent._dispatch(step))
        events = self.drain()

        calls = [event["payload"] for event in events if event["action"] == "tool_call"]
        self.assertEqual(len(calls), 1, events)
        current = calls[0]
        self.assertNotEqual(old["call_id"], current["call_id"])
        self.succeed(current, 23)

        self.assertEqual(self.agent.operations[current["call_id"]]["revision"], self.agent.revision)
        self.assertEqual(self.agent.operations[current["call_id"]]["result"]["temperature_c"], 23)
        self.assertEqual(self.agent.tool_results[-1]["call_id"], current["call_id"])
        self.assertEqual(self.agent.tool_results[-1]["revision"], self.agent.revision)
        final = self.drain()
        self.assertTrue(any(event["action"] == "final_response" and "23" in event["payload"]["text"]
                            for event in final), final)


if __name__ == "__main__":
    unittest.main()
