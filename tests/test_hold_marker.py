"""A turn ending on a hold marker waits briefly before planning; new speech cancels it."""
import asyncio
from copy import deepcopy
import unittest

from participant.agent import _HOLD_MARKER, ParticipantAgent

TOOLS = {"search_flights": {"kind": "read_only", "description": "Search for available flights to a destination.",
                            "args": {"destination": {"type": "string", "required": True},
                                     "date": {"type": "string", "required": True}}}}


class Planner:
    clause_citations = True
    follow_up_rounds = 0

    def __init__(self):
        self.contexts = []

    async def setup(self): pass
    async def close(self): pass

    async def plan(self, context):
        self.contexts.append(deepcopy(context))
        return {"intent": "", "slots": {}, "tool_calls": [], "response": "ok"}


class HoldMarkerTest(unittest.IsolatedAsyncioTestCase):
    def test_marker_shapes(self):
        for text in ("It's looking at flights to Miami on October 5th. Uh, wait.", "Uh, wait.", "hold on",
                     "Let me think.", "wait no actually", "so, sorry"):
            self.assertIsNotNone(_HOLD_MARKER.search(text), text)
        for text in ("Wait for the delivery and track order C one.", "Book it, I can't wait.",
                     "Make it one.", "Track order A B C one two three."):
            self.assertIsNone(_HOLD_MARKER.search(text), text)

    async def run_turns(self, turns, gap):
        planner = Planner()
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue(), planner=planner)
        agent.hold_seconds = 0.3
        task = asyncio.create_task(agent.run())
        events = []
        try:
            await agent.in_queue.put({"event_type": "tool_manifest", "payload": {"tools": TOOLS}})
            for index, text in enumerate(turns):
                if index:
                    await asyncio.sleep(gap)
                    await agent.in_queue.put({"event_type": "interruption", "payload": {"text": ""}})
                await agent.in_queue.put({"event_type": "user_speech_chunk",
                                          "payload": {"text": text, "end_of_turn": True}})
            while True:
                try:
                    events.append(await asyncio.wait_for(agent.out_queue.get(), 1.0))
                except asyncio.TimeoutError:
                    break
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return planner, events

    async def test_hold_then_continuation_plans_only_the_complete_turn(self):
        planner, events = await self.run_turns(["Look up flights to Miami on October 5th. Uh, wait.",
                                                "Make it October 7th instead."], gap=0.05)
        self.assertEqual(len(planner.contexts), 1, "the held plan must be cancelled by the continuation")
        texts = " ".join(str(m["payload"].get("text", "")) for m in planner.contexts[0]["messages"])
        self.assertIn("October 7th", texts)
        self.assertIn("planning_held", [event["action"] for event in events])

    async def test_hold_without_continuation_still_plans(self):
        planner, _ = await self.run_turns(["Look up flights to Miami on October 5th. Uh, wait."], gap=0)
        self.assertEqual(len(planner.contexts), 1)

    async def test_plain_turn_is_not_held(self):
        planner, events = await self.run_turns(["Look up flights to Miami on October 5th."], gap=0)
        self.assertEqual(len(planner.contexts), 1)
        self.assertNotIn("planning_held", [event["action"] for event in events])


if __name__ == "__main__":
    unittest.main()
