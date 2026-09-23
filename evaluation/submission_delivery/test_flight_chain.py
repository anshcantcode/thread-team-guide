"""Independent, offline checks of the documented flight command shortcut.

The ordinary Planner and ParticipantAgent run unchanged. Only the model-generation
boundary is mocked; it records the complete fallback context and asks for clarity.
Values below are newly authored public test data, not private holdout content.
"""
import asyncio
from copy import deepcopy
import os
import tempfile
import unittest
from unittest.mock import patch

import httpx

from participant.agent import ParticipantAgent
from participant.planner import Planner
from tests import test_participant_controller as queue_helpers


# The supplied kit's documented TOOL_REGISTRY contracts, without scenario data.
TOOLS = {
    "flight_search": {
        "kind": "read_only", "delay_range_ms": [1500, 3000],
        "description": "Search flights to a destination city on a given date.",
        "args": {
            "destination": {"type": "string", "required": True,
                            "description": "Destination city name or airport code."},
            "date": {"type": "string", "required": False,
                     "description": "Departure date, free-form (e.g. 'tomorrow', '2026-09-12')."}}},
    "book_flight": {
        "kind": "state_modifying", "delay_range_ms": [800, 1600],
        "description": "Book a specific flight returned by flight_search.",
        "args": {
            "flight_id": {"type": "string", "required": True,
                          "description": "A flight id returned by flight_search."},
            "passenger_name": {"type": "string", "required": True,
                               "description": "Full name of the passenger."}}},
}
TEXT = "Find flights to Dakar and book the 8 AM one for Nia."
FALLBACK = {"observations": [], "intent": "", "slots": {}, "tool_calls": [],
            "clarification": "Please clarify the flight selection.", "response": None}


def context(text=TEXT):
    return {"revision": 1, "current_turn_start": 0,
            "messages": [{"message_index": 0, "revision": 1, "event_type": "user_speech_chunk",
                          "payload": {"text": text, "end_of_turn": True}}],
            "state": {"intent": "", "slots": {}}, "actions": [], "tool_results": [],
            "observations": [], "latest_frame_index": None, "tools": deepcopy(TOOLS)}


class FlightCommandTests(unittest.IsolatedAsyncioTestCase):
    # Reuse queue operations, not the old TestCase (which would collect old tests).
    event = queue_helpers.ControllerTests.event
    speak = queue_helpers.ControllerTests.speak
    output = queue_helpers.ControllerTests.output
    result = queue_helpers.ControllerTests.result
    drain = queue_helpers.ControllerTests.drain

    async def asyncSetUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        env = patch.dict(os.environ, {"SECRET_GEMINI_API_KEY": "offline-flight-nonsecret-sentinel",
                         "PARTICIPANT_PREWARM": "0", "PARTICIPANT_IMAGE_EMBEDDING": "0",
                         "PARTICIPANT_MEDIA_ROOT": self.media.name}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.planners, self.agents = [], []

    async def asyncTearDown(self):
        for agent, task in self.agents:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self.assertTrue(agent._closed)
        for planner in self.planners:
            await planner.close()

    async def planner(self):
        def no_http(request):
            self.fail("Unexpected HTTP request in an offline flight shortcut test")
        planner = Planner(transport=httpx.MockTransport(no_http))
        captured = []

        async def generation_boundary(current, record, started):
            captured.append(deepcopy(current))
            return deepcopy(FALLBACK)

        mock = patch.object(planner, "_generate", side_effect=generation_boundary)
        mock.start()
        self.addCleanup(mock.stop)
        self.planners.append(planner)
        await planner.setup()
        return planner, captured

    async def start(self):
        planner, captured = await self.planner()
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue(), planner=planner)
        self.agents.append((agent, asyncio.create_task(agent.run())))
        await self.event(agent, "tool_manifest", {"tools": deepcopy(TOOLS)})
        return agent, captured

    async def settled(self, predicate):
        async def wait():
            while not predicate():
                await asyncio.sleep(0)
        await asyncio.wait_for(wait(), 0.6)
        for _ in range(6):
            await asyncio.sleep(0)

    async def assert_fallback(self, planner, captured, current):
        original, before = deepcopy(current), len(captured)
        result = await planner.plan(current)
        self.assertEqual(captured[before:], [original], "The entire request must reach the model boundary")
        self.assertEqual(current, original, "The local shortcut mutated a deferred request")
        self.assertEqual(result, FALLBACK)

    async def test_open_values_and_noon_midnight_minutes(self):
        planner, captured = await self.planner()
        cases = [
            ("Find flights to Valparaíso on Friday and book the 12 AM one for Élodie.",
             {"destination": "Valparaíso", "date": "Friday"}, "00:00", "Élodie"),
            ("Search for flights to Dakar then reserve the 12 PM one for kwame.",
             {"destination": "Dakar"}, "12:00", "kwame"),
            ("Please find me a flight to Busan for Sunday and book the 7:43 PM one for Seo-jun.",
             {"destination": "Busan", "date": "Sunday"}, "19:43", "Seo-jun"),
            ("Can you find flights to Reykjavík and reserve the 1:05 am one for O'Rourke.",
             {"destination": "Reykjavík"}, "01:05", "O'Rourke"),
        ]
        for text, args, depart, person in cases:
            with self.subTest(text=text):
                before = len(captured)
                proposed = await planner.plan(context(text))
                self.assertEqual(len(captured), before, "Supported syntax missed the local path")
                self.assertEqual(len(proposed["tool_calls"]), 1)
                search = proposed["tool_calls"][0]
                self.assertEqual((search["api_name"], search["args"]), ("flight_search", args))
                book = search["after_result"]
                self.assertEqual((book["api_name"], book["args"]), ("book_flight", {"passenger_name": person}))
                self.assertEqual(book["select"], {"path": "flights", "where": {"depart": depart}})
                self.assertEqual(book["bindings"], {"flight_id": "flight_id"})
                self.assertEqual(book["authorization"]["quote"], text)

    async def test_extra_constraints_cannot_be_absorbed_into_passenger_name(self):
        planner, captured = await self.planner()
        for suffix in ("using miles", "excluding codeshares", "carrying lithium batteries",
                       "wheelchair assistance", "refundable only", "Carrying Lithium Batteries"):
            with self.subTest(suffix=suffix):
                await self.assert_fallback(planner, captured, context(TEXT[:-1] + " " + suffix + "."))

    async def test_negation_conditions_references_corrections_and_quotations_defer(self):
        planner, captured = await self.planner()
        texts = [
            TEXT.replace("and book", "and do not book"),
            TEXT[:-1] + " if it costs less than 300 dollars.",
            TEXT.replace("for Nia", "for her"),
            TEXT.replace("for Nia", "for myself"),
            TEXT.replace("for Nia", "for she"),
            TEXT.replace("for Nia", "for my"),
            TEXT.replace("for Nia", "for neither"),
            TEXT.replace("Nia", "Siobhán O'Rourke"),
            TEXT[:-1] + " Actually use the 9 AM one.",
            'My colleague said "' + TEXT + '"',
            TEXT.replace("Dakar", '"San José"'),
            TEXT.replace("Nia", '"Nia"'),
            TEXT.replace("to Dakar", "from Accra to Dakar"),
            TEXT[:-1] + " then cancel my old booking.",
        ]
        for text in texts:
            with self.subTest(text=text):
                await self.assert_fallback(planner, captured, context(text))

    async def test_invalid_12_hour_times_defer_without_repairing_the_user(self):
        planner, captured = await self.planner()
        for time in ("0 AM", "13 PM", "8:60 AM", "8:5 AM"):
            with self.subTest(time=time):
                await self.assert_fallback(planner, captured, context(TEXT.replace("8 AM", time)))

    async def test_prior_context_open_turn_media_and_broken_fragment_provenance_defer(self):
        planner, captured = await self.planner()
        variants = {}
        current = context()
        current["current_turn_start"] = 1
        variants["later_turn"] = current
        current = context()
        current["state"]["slots"] = {"destination": "Accra"}
        variants["prior_slots"] = current
        current = context()
        current["messages"][0]["payload"]["end_of_turn"] = False
        variants["unfinished_text"] = current
        current = context()
        current["messages"][0]["event_type"] = "user_audio_chunk"
        variants["audio_with_incidental_text"] = current
        current = context()
        current["latest_frame_index"] = 0
        variants["image_context"] = current
        current = context()
        current["actions"] = [{"api_name": "flight_search", "status": "success"}]
        variants["prior_action"] = current
        current = context()
        current["messages"][0]["revision"] = 0
        variants["stale_revision"] = current
        current = context()
        current["messages"][0]["payload"] = {"text": "Find flights to Da", "end_of_turn": False}
        current["messages"].append({"message_index": 1, "revision": 1, "event_type": "user_speech_chunk",
                                    "payload": {"text": TEXT[len("Find flights to Da"):], "end_of_turn": True}})
        variants["split_inside_literal"] = current
        for label, current in variants.items():
            with self.subTest(boundary=label):
                await self.assert_fallback(planner, captured, current)

    async def test_changed_tool_contracts_defer_with_full_manifest(self):
        planner, captured = await self.planner()
        changes = [
            ("flight_search", ("kind",), "state_modifying"),
            ("flight_search", ("args", "max_fare"), {"type": "number", "required": False}),
            ("flight_search", ("result_shape",), {"flights": [{"flight_id": "string", "depart": "number", "price_usd": "number"}]}),
            ("book_flight", ("args", "seat"), {"type": "string", "required": False}),
            ("book_flight", ("args", "flight_id", "type"), "integer"),
            ("book_flight", ("args", "passenger_name", "description"), "An internal passenger account identifier, not a name."),
            ("book_flight", ("description",), "Cancel a specific flight returned by flight_search."),
            ("book_flight", ("result_shape",), {"receipt": "string"}),
        ]
        for tool, path, value in changes:
            with self.subTest(tool=tool, field=".".join(path)):
                current = context()
                target = current["tools"][tool]
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = value
                await self.assert_fallback(planner, captured, current)

    async def test_real_controller_binds_the_unique_actual_row_in_a_fragmented_turn(self):
        agent, captured = await self.start()
        await self.speak(agent, "Find flights to Dakar ", end=False)
        await self.settled(lambda: len(agent.messages) == 1)
        self.assertEqual(self.drain(agent), [])
        await self.speak(agent, "and book the 8 AM one for Nia.")
        search = await self.output(agent, "tool_call")
        self.assertEqual(search["payload"]["args"], {"destination": "Dakar"})
        self.assertEqual(len(agent.operations), 1, "Booking was dispatched before results")
        rows = {"flights": [{"flight_id": "UNSELECTED-352", "depart": "08:30", "price_usd": 120},
                            {"flight_id": "LIVE-9741", "depart": "08:00", "price_usd": 340}]}
        await self.result(agent, search, rows)
        book = await self.output(agent, "tool_call")
        self.assertEqual(book["payload"]["api_name"], "book_flight")
        self.assertEqual(book["payload"]["args"], {"flight_id": "LIVE-9741", "passenger_name": "Nia"})
        operation = agent.operations[book["payload"]["call_id"]]
        self.assertEqual(operation["step"]["result_bindings"]["flight_id"],
                         {"call_id": search["payload"]["call_id"], "path": "flights.1.flight_id"})
        await self.result(agent, book, {"booking_id": "RECEIPT-612", "flight_id": "LIVE-9741"})
        final = await self.output(agent, "final_response")
        self.assertIn("RECEIPT-612", final["payload"]["text"])
        await self.result(agent, search, rows)
        await self.settled(lambda: agent.in_queue.empty())
        self.assertEqual(len(agent.operations), 2, "Repeated result dispatched another booking")
        self.assertEqual(captured, [], "The supported replay unexpectedly used the model")

    async def test_missing_ambiguous_or_unbindable_returned_rows_never_book(self):
        options = {
            "empty": [],
            "no_exact_time": [{"flight_id": "MISMATCH-2", "depart": "8:00", "price_usd": 180}],
            "ambiguous": [{"flight_id": value, "depart": "08:00", "price_usd": 180}
                          for value in ("DUPE-41", "DUPE-92")],
            "missing_id": [{"depart": "08:00", "price_usd": 180}],
            "wrong_id_type": [{"flight_id": 914, "depart": "08:00", "price_usd": 180}],
        }
        for label, rows in options.items():
            with self.subTest(result=label):
                agent, captured = await self.start()
                await self.speak(agent, TEXT)
                search = await self.output(agent, "tool_call")
                await self.result(agent, search, {"flights": rows})
                await self.output(agent, "clarification_request")
                self.assertFalse([op for op in agent.operations.values() if op["kind"] == "state_modifying"])
                if label == "wrong_id_type":
                    self.assertEqual(captured, [], "Invalid bound types should reach the ordinary schema refusal")
                else:
                    self.assertEqual(len(captured), 1, "Unselectable result should make one bounded repair attempt")
                    self.assertTrue(captured[0].get("planning_error"))
                    self.assertEqual(captured[0]["tool_results"][0]["result"]["flights"], rows)

    async def test_correction_queued_with_result_prevents_old_booking(self):
        agent, captured = await self.start()
        await self.speak(agent, TEXT)
        search = await self.output(agent, "tool_call")
        # Queue the result first; the controller must still apply the correction first.
        await self.result(agent, search, {"flights": [{"flight_id": "OLD-884", "depart": "08:00", "price_usd": 180}]})
        await self.speak(agent, "Actually, do not book anything.")
        await self.output(agent, "clarification_request")
        await self.settled(lambda: agent.operations[search["payload"]["call_id"]]["status"] == "success")
        self.assertFalse([op for op in agent.operations.values() if op["kind"] == "state_modifying"])
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["messages"][-1]["payload"]["text"], "Actually, do not book anything.")
