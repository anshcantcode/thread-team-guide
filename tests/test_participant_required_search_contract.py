"""A read-only search runs with what the user said; required filters never become guesses.

A required filter the user never narrowed by runs unspecified (None at the executor), a
named-but-omitted field or an unused spoken number is asked for, and a planner's invented
value is removed rather than sent. Invented values and in-memory executors; no benchmark
recordings or labels.
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

    async def test_unstated_required_filter_runs_unspecified_never_guessed(self):
        for missing, text, args in (
            ("desks", "Find workrooms in Clifton under 850.", {"district": "Clifton", "budget": 850}),
            ("budget", "Find workrooms in Clifton with three desks.", {"district": "Clifton", "desks": 3}),
            ("district", "Find workrooms with three desks under 850.", {"desks": 3, "budget": 850}),
        ):
            with self.subTest(missing=missing):
                events = self.dispatch(text, "search_workrooms", args)
                self.assertEqual([event["payload"]["args"] for event in events if event["action"] == "tool_call"],
                                 [args])
                self.assertFalse([event for event in events if event["action"] == "clarification_request"])

    async def test_search_narrowed_by_too_few_filters_is_asked_about(self):
        # One of three required filters stated: too vague to be the requested search.
        events = self.dispatch("Find workrooms in Clifton.", "search_workrooms", {"district": "Clifton"})
        self.assertFalse([event for event in events if event["action"] == "tool_call"])
        self.assertEqual([event["payload"]["text"] for event in events if event["action"] == "clarification_request"],
                         ["Could you tell me the desks and the budget?"])

    async def test_named_but_omitted_field_is_asked_for_in_contract_words(self):
        events = self.dispatch("Find workrooms in Clifton with three desks within my budget.", "search_workrooms",
                               {"district": "Clifton", "desks": 3})
        self.assertFalse([event for event in events if event["action"] == "tool_call"])
        clarification = [event for event in events if event["action"] == "clarification_request"]
        self.assertEqual([event["payload"]["text"] for event in clarification], ["Could you tell me the budget?"])
        self.assertEqual(clarification[0]["payload"]["validation"],
                         {"api_name": "search_workrooms", "problems": ["args.budget: missing required argument"]})

    async def test_unused_spoken_number_is_asked_for(self):
        events = self.dispatch("Find workrooms in Clifton with three desks under 900.", "search_workrooms",
                               {"district": "Clifton", "desks": 3})
        self.assertFalse([event for event in events if event["action"] == "tool_call"])
        self.assertEqual([event["payload"]["text"] for event in events if event["action"] == "clarification_request"],
                         ["Could you tell me the budget?"])

    async def test_actual_optional_filter_can_be_omitted(self):
        events = self.dispatch("Find woven linen.", "search_materials", {"query": "woven linen"})
        self.assertEqual([event["payload"]["args"] for event in events if event["action"] == "tool_call"],
                         [{"query": "woven linen"}])

    async def test_removed_invented_required_filter_runs_unspecified(self):
        text = "Find workrooms in Clifton with three desks."
        context = {"tools": TOOLS, "messages": [{"event_type": "user_speech_chunk", "payload": {"text": text}}]}
        proposal = {"api_name": "search_workrooms", "args": {"district": "Clifton", "desks": 3, "budget": 4000}}
        corrected = drop_unstated_search_filters({"tool_calls": [proposal]}, context)["tool_calls"][0]
        self.assertNotIn("budget", corrected["args"])
        events = self.dispatch(text, corrected["api_name"], corrected["args"])
        self.assertEqual([event["payload"]["args"] for event in events if event["action"] == "tool_call"],
                         [{"district": "Clifton", "desks": 3}])

    async def test_bridge_passes_unstated_filter_as_none_and_asks_when_the_backend_needs_it(self):
        registry = Registry()
        planner = Planner({"api_name": "search_workrooms", "args": {"district": "Clifton", "desks": 3}})
        bridge = ControllerBridge(deepcopy(TOOLS), registry, planner)
        await bridge.start()
        try:
            answer = await bridge.response("Find workrooms in Clifton with three desks.", timeout=2)
            # The executor receives every declared filter, the unstated one as None, never a guess.
            self.assertEqual(registry.calls, [("search_workrooms", {"district": "Clifton", "desks": 3, "budget": None})])
            # This backend cannot search without a budget; speech asks for it, never an error code.
            self.assertEqual(answer, "I could not get results for that search with what I have. "
                                     "Could you tell me the budget?")
            self.assertNotIn("exception", answer)
        finally:
            await bridge.close()


if __name__ == "__main__":
    unittest.main()
