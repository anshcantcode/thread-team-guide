"""Required search arguments are contractual even when the user omitted a filter.

Invented values and in-memory executors; no benchmark recordings or labels.
"""
import asyncio
from copy import deepcopy
import unittest

from participant.agent import ParticipantAgent
from thread_agent.fdb3 import ControllerBridge, drop_unstated_search_filters


TOOLS = {
    "search_workrooms": {
        "kind": "read_only",
        "args": {
            "district": {"type": "string", "required": True},
            "desks": {"type": "integer", "required": True},
            "budget": {"type": "number", "required": True},
        },
    },
    "search_materials": {
        "kind": "read_only",
        "args": {
            "query": {"type": "string", "required": True},
            "ceiling": {"type": "number", "required": False},
        },
    },
}


class Planner:
    def __init__(self, proposal):
        self.proposal = proposal

    async def setup(self):
        pass

    async def close(self):
        pass

    async def plan(self, context):
        return {"tool_calls": [deepcopy(self.proposal)]}


class Registry:
    def __init__(self):
        self.calls = []

    def call(self, name, **args):
        self.calls.append((name, deepcopy(args)))
        return {"status": "success", "remaining_budget": args["budget"] - 35}


class RequiredSearchContractTests(unittest.IsolatedAsyncioTestCase):
    def dispatch(self, text, name, args):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.tools = deepcopy(TOOLS)
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": text}}]
        agent._dispatch({"api_name": name, "args": args})
        events = []
        while not agent.out_queue.empty():
            events.append(agent.out_queue.get_nowait())
        return events

    async def test_missing_required_scalar_never_dispatches_or_becomes_null(self):
        for missing, text, args in (
            ("desks", "Find workrooms in Clifton under 850.", {"district": "Clifton", "budget": 850}),
            ("budget", "Find workrooms in Clifton with three desks.", {"district": "Clifton", "desks": 3}),
            ("district", "Find workrooms with three desks under 850.", {"desks": 3, "budget": 850}),
        ):
            with self.subTest(missing=missing):
                events = self.dispatch(text, "search_workrooms", args)
                self.assertFalse([event for event in events if event["action"] == "tool_call"])
                clarification = [event for event in events if event["action"] == "clarification_request"]
                self.assertEqual(len(clarification), 1)
                # Spoken in the contract's words; the validator's message is evidence only.
                self.assertEqual(clarification[0]["payload"]["text"], f"Could you tell me the {missing}?")
                self.assertEqual(clarification[0]["payload"]["validation"],
                                 {"api_name": "search_workrooms",
                                  "problems": [f"args.{missing}: missing required argument"]})

    async def test_actual_optional_filter_can_be_omitted(self):
        events = self.dispatch("Find woven linen.", "search_materials", {"query": "woven linen"})
        self.assertEqual([event["payload"]["args"] for event in events if event["action"] == "tool_call"],
                         [{"query": "woven linen"}])

    async def test_removed_invented_required_filter_requires_clarification(self):
        text = "Find workrooms in Clifton with three desks."
        context = {"tools": TOOLS, "messages": [{"event_type": "user_speech_chunk", "payload": {"text": text}}]}
        proposal = {"api_name": "search_workrooms", "args": {"district": "Clifton", "desks": 3, "budget": 4000}}
        corrected = drop_unstated_search_filters({"tool_calls": [proposal]}, context)["tool_calls"][0]
        self.assertNotIn("budget", corrected["args"])
        events = self.dispatch(text, corrected["api_name"], corrected["args"])
        self.assertFalse([event for event in events if event["action"] == "tool_call"])
        self.assertTrue([event for event in events if event["action"] == "clarification_request"])

    async def test_bridge_never_invokes_backend_with_missing_required_filter(self):
        registry = Registry()
        planner = Planner({"api_name": "search_workrooms", "args": {"district": "Clifton", "desks": 3}})
        bridge = ControllerBridge(deepcopy(TOOLS), registry, planner)
        await bridge.start()
        try:
            answer = await bridge.response("Find workrooms in Clifton with three desks.", timeout=2)
            self.assertEqual(answer, "Could you tell me the budget?")
            self.assertEqual([event["payload"]["validation"]["problems"] for event in bridge.events
                              if event["action"] == "clarification_request"],
                             [["args.budget: missing required argument"]])
            self.assertEqual(registry.calls, [])
            self.assertEqual(bridge.calls, [])
        finally:
            await bridge.close()


if __name__ == "__main__":
    unittest.main()
