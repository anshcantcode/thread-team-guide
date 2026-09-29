"""Bounded follow-up planning after results settle (guidance v2 candidate)."""
import asyncio
from copy import deepcopy
import unittest
from unittest.mock import patch

from participant.agent import ParticipantAgent

TOOLS = {
    "search_products": {"kind": "read_only", "description": "Search products.",
                        "args": {"query": {"type": "string", "required": True}}},
    "track_order": {"kind": "read_only", "description": "Track an order.",
                    "args": {"order_id": {"type": "string", "required": True}}},
    "add_to_cart": {"kind": "state_modifying", "description": "Add an item to the shopping cart.",
                    "args": {"product_id": {"type": "string", "required": True, "description": "ID of the product"},
                             "quantity": {"type": "integer", "required": False, "default": 1}}},
}


class Planner:
    clause_citations = True

    def __init__(self, decisions, rounds=2):
        self.decisions, self.follow_up_rounds, self.contexts = list(decisions), rounds, []

    async def setup(self): pass
    async def close(self): pass

    async def plan(self, context):
        self.contexts.append(deepcopy(context))
        decide = self.decisions.pop(0) if self.decisions else (lambda context: {"intent": "done", "slots": {}, "tool_calls": []})
        return decide(context)


class FollowUpTests(unittest.IsolatedAsyncioTestCase):
    def test_cancelled_deferred_write_cannot_resume_from_a_late_lookup(self):
        for same_turn in (False, True):
            for text in ("Search for a kettle and add one of the results to my cart.",
                         "Search for a kettle. If it is under 50 dollars, add one to my cart."):
                with self.subTest(same_turn=same_turn, text=text):
                    agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue(), planner=Planner([]))
                    agent.tools = deepcopy(TOOLS)
                    agent._logical_turn = "cart-turn"
                    agent.messages = [{"event_type": "user_speech_chunk", "payload": {
                        "text": text, "end_of_turn": True, "logical_turn": "cart-turn"}}]
                    write = {"api_name": "add_to_cart", "args": {"product_id": "KT1", "quantity": 1},
                             "authorization": {"quote": text}}
                    agent._dispatch_plan([{"api_name": "search_products", "args": {"query": "kettle"}}, write])
                    before = [agent.out_queue.get_nowait() for _ in range(agent.out_queue.qsize())]
                    self.assertEqual([event["action"] for event in before], ["tool_call", "write_deferred"])
                    cancellation = {"text": "Never mind, don't add anything.", "end_of_turn": True}
                    if same_turn:
                        cancellation["logical_turn"] = "cart-turn"
                    with patch.object(agent, "_start_plan") as start:
                        agent._handle({"event_type": "user_speech_chunk", "payload": cancellation})
                        start.reset_mock()
                        agent._result({"call_id": "call-1", "api_name": "search_products", "status": "success",
                                       "result": {"products": [{"product_id": "KT1", "price": 29.0}]}})
                        start.assert_not_called()
                        # Even a fresh faulty planner repeating the old proposal
                        # cannot use the completed lookup to revive this write.
                        agent._dispatch(write)
                    after = [agent.out_queue.get_nowait() for _ in range(agent.out_queue.qsize())]
                    self.assertFalse(any(event["action"] == "tool_call" for event in after), after)
                    self.assertEqual(agent.operations["call-1"]["status"], "success")
                    self.assertEqual(len(agent.operations), 1)

    async def run_turn(self, text, planner, results):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue(), planner=planner)
        task = asyncio.create_task(agent.run())
        events = []
        try:
            await agent.in_queue.put({"event_type": "tool_manifest", "payload": {"tools": TOOLS}})
            await agent.in_queue.put({"event_type": "user_speech_chunk", "payload": {"text": text, "end_of_turn": True}})
            while True:
                try:
                    event = await asyncio.wait_for(agent.out_queue.get(), 1.0)
                except asyncio.TimeoutError:
                    break
                events.append(event)
                if event["action"] == "tool_call":
                    payload = event["payload"]
                    await agent.in_queue.put({"event_type": "tool_result", "payload": {
                        "call_id": payload["call_id"], "api_name": payload["api_name"], "status": "success",
                        "result": {"status": "success", **results[payload["api_name"]]}}})
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return events

    async def test_remaining_step_runs_after_the_first_result(self):
        def first(context):
            return {"intent": "search", "slots": {}, "tool_calls": [{"api_name": "search_products",
                    "args": {"query": "tea kettle"}, "response_template": "Found {products.0.name}."}]}
        def follow(context):
            self.assertTrue(context["planning_error"].startswith("Follow-up round"))
            clause = context["current_clauses"][-1]["clause_id"]
            return {"intent": "add", "slots": {}, "tool_calls": [{"api_name": "add_to_cart",
                    "args": {"product_id": "KT1", "quantity": 1}, "authorization": {"clauses": [clause]},
                    "response_template": "Added {product_id}."}]}
        planner = Planner([first, follow])
        events = await self.run_turn("Search for a tea kettle and add one of the results to my cart.", planner,
                                     {"search_products": {"products": [{"product_id": "KT1", "name": "Tea kettle"}]},
                                      "add_to_cart": {"product_id": "KT1", "quantity": 1}})
        self.assertEqual([e["payload"]["api_name"] for e in events if e["action"] == "tool_call"],
                         ["search_products", "add_to_cart"])
        self.assertEqual(len(planner.contexts), 3)  # first plan, one useful follow-up, one empty follow-up

    async def conditional_lookup(self, price):
        text = ("Search for a teapot first. If you find one under 30 dollars, add one to my cart. "
                "But if everything's over 30 dollars, forget it and track order Q7 instead.")
        def first(context):
            return {"intent": "shop", "slots": {}, "tool_calls": [
                {"api_name": "search_products", "args": {"query": "teapot"}, "response_template": "Found {products.0.name}."},
                {"api_name": "track_order", "args": {"order_id": "Q7"}, "response_template": "Order {order_id}."}]}
        planner = Planner([first])
        events = await self.run_turn(text, planner, {
            "search_products": {"products": [{"product_id": "TP1", "name": "Teapot", "price": price}]},
            "track_order": {"order_id": "Q7"}})
        return [e["payload"]["api_name"] for e in events if e["action"] == "tool_call"]

    async def test_lookup_inside_a_false_price_condition_is_skipped(self):
        self.assertEqual(await self.conditional_lookup(19.0), ["search_products"])

    async def test_lookup_inside_a_true_price_condition_runs_after_the_search(self):
        self.assertEqual(await self.conditional_lookup(45.0), ["search_products", "track_order"])

    async def test_follow_up_names_requests_no_call_handled(self):
        def first(context):
            return {"intent": "track", "slots": {}, "tool_calls": [{"api_name": "track_order",
                    "args": {"order_id": "Q9"}, "response_template": "Order {order_id}."}]}
        seen = []
        def follow(context):
            seen.append(context["planning_error"])
            return {"intent": "done", "slots": {}, "tool_calls": []}
        planner = Planner([first, follow])
        await self.run_turn("Track order Q9 for me. Then search for a copper teapot. You know, it's a gift.", planner,
                            {"track_order": {"order_id": "Q9"}})
        self.assertIn('no call has handled yet: "then search for a copper teapot."', seen[0])
        self.assertNotIn("track order q9", seen[0])
        self.assertNotIn("gift", seen[0])

    async def test_a_lookup_reusing_a_value_does_not_handle_a_change_request(self):
        def first(context):
            return {"intent": "search", "slots": {}, "tool_calls": [{"api_name": "search_products",
                    "args": {"query": "kettle 40"}, "response_template": "Found {products.0.name}."}]}
        seen = []
        def follow(context):
            seen.append(context["planning_error"])
            return {"intent": "done", "slots": {}, "tool_calls": []}
        planner = Planner([first, follow])
        await self.run_turn("Update my budget filter to kettle 40 please, then search for a kettle 40.", planner,
                            {"search_products": {"products": [{"product_id": "K4", "name": "Kettle"}]}})
        self.assertIn("update my budget filter to kettle 40 please", seen[0])

    async def test_follow_up_does_not_add_a_lookup_built_only_from_another_tools_values(self):
        def first(context):
            return {"intent": "track", "slots": {}, "tool_calls": [{"api_name": "track_order",
                    "args": {"order_id": "Q9"}, "response_template": "Order {order_id}."}]}
        def follow(context):
            return {"intent": "more", "slots": {}, "tool_calls": [
                {"api_name": "search_products", "args": {"query": "Q9"}, "response_template": "Found."},
                {"api_name": "search_products", "args": {"query": "gift wrap"}, "response_template": "Found."}]}
        planner = Planner([first, follow])
        events = await self.run_turn("Track order Q9 and find me gift wrap and a greeting card service.", planner,
                                     {"track_order": {"order_id": "Q9"},
                                      "search_products": {"products": [{"product_id": "G1", "name": "Gift wrap"}]}})
        self.assertEqual([e["payload"]["args"] for e in events if e["action"] == "tool_call"],
                         [{"order_id": "Q9"}, {"query": "gift wrap"}])

    async def test_second_unbindable_copy_does_not_preempt_the_running_repair(self):
        add = {"api_name": "add_to_cart", "args": {"product_id": "{items.0.id}", "quantity": 1},
               "response_template": "Added."}
        def first(context):
            clause = context["current_clauses"][-1]["clause_id"]
            step = dict(add, authorization={"clauses": [clause]})
            return {"intent": "shop", "slots": {}, "tool_calls": [
                {"api_name": "search_products", "args": {"query": "kettle"}, "response_template": "Found.", "after_result": step},
                {"api_name": "track_order", "args": {"order_id": "Q9"}, "response_template": "Order.", "after_result": step}]}
        def repair(context):
            clause = context["current_clauses"][-1]["clause_id"]
            return {"intent": "add", "slots": {}, "tool_calls": [{"api_name": "add_to_cart",
                    "args": {"product_id": "KT1", "quantity": 1}, "authorization": {"clauses": [clause]},
                    "response_template": "Added {product_id}."}]}
        planner = Planner([first, repair])
        events = await self.run_turn("Search for a kettle and track order Q9. Add the kettle you find to my cart.", planner,
                                     {"search_products": {"products": [{"product_id": "KT1", "name": "Kettle"}]},
                                      "track_order": {"order_id": "Q9"}, "add_to_cart": {"product_id": "KT1", "quantity": 1}})
        self.assertIn(("add_to_cart", {"product_id": "KT1", "quantity": 1}),
                      [(e["payload"]["api_name"], e["payload"]["args"]) for e in events if e["action"] == "tool_call"])

    async def test_politeness_if_is_not_a_lookup_condition(self):
        def first(context):
            return {"intent": "search", "slots": {}, "tool_calls": [{"api_name": "search_products",
                    "args": {"query": "desk lamp"}, "response_template": "Found {products.0.name}."}]}
        events = await self.run_turn("I want a desk lamp under forty dollars if possible. What do you have?",
                                     Planner([first]), {"search_products": {"products": [{"product_id": "L1", "name": "Lamp"}]}})
        self.assertEqual([e["payload"]["api_name"] for e in events if e["action"] == "tool_call"], ["search_products"])

    async def test_an_unsettleable_conditional_lookup_asks_instead_of_hanging(self):
        def first(context):
            return {"intent": "track", "slots": {}, "tool_calls": [{"api_name": "track_order",
                    "args": {"order_id": "Q7"}, "response_template": "Order {order_id}."}]}
        events = await self.run_turn("If the weather clears up, track order Q7.", Planner([first]),
                                     {"track_order": {"order_id": "Q7"}})
        self.assertFalse([e for e in events if e["action"] == "tool_call"])
        self.assertTrue([e for e in events if e["action"] == "clarification_request"])

    async def test_follow_up_names_extracted_values_no_call_used(self):
        def first(context):
            return {"intent": "track", "slots": {"first_order": "Q9", "second_order": "W4"},
                    "tool_calls": [{"api_name": "track_order", "args": {"order_id": "Q9"},
                                    "response_template": "Order {order_id}."}]}
        def follow(context):
            self.assertIn("no call has used yet: second_order=W4.", context["planning_error"])
            self.assertNotIn("first_order", context["planning_error"])
            return {"intent": "track", "slots": {}, "tool_calls": [{"api_name": "track_order",
                    "args": {"order_id": "W4"}, "response_template": "Order {order_id}."}]}
        planner = Planner([first, follow])
        events = await self.run_turn("Track order Q9 and order W4.", planner, {"track_order": {"order_id": "Q9"}})
        self.assertEqual([e["payload"]["args"] for e in events if e["action"] == "tool_call"],
                         [{"order_id": "Q9"}, {"order_id": "W4"}])
        # Once every extracted value is used, the next follow-up names nothing.
        self.assertNotIn("Slots you extracted", planner.contexts[-1]["planning_error"])

    async def test_empty_follow_up_is_silent_and_bounded(self):
        def first(context):
            return {"intent": "track", "slots": {}, "tool_calls": [{"api_name": "track_order",
                    "args": {"order_id": "Q9"}, "response_template": "Order {order_id}."}]}
        planner = Planner([first])
        events = await self.run_turn("Track order Q9.", planner, {"track_order": {"order_id": "Q9"}})
        spoken = [e for e in events if e["action"] in {"final_response", "clarification_request"}]
        self.assertEqual(len(spoken), 1)
        self.assertEqual(len(planner.contexts), 2)

    async def test_follow_up_cannot_repeat_a_completed_call(self):
        def first(context):
            return {"intent": "track", "slots": {}, "tool_calls": [{"api_name": "track_order",
                    "args": {"order_id": "Q9"}, "response_template": "Order {order_id}."}]}
        def again(context):
            return {"intent": "track", "slots": {}, "tool_calls": [{"api_name": "track_order",
                    "args": {"order_id": "Q9"}, "response_template": "Order {order_id}."}]}
        planner = Planner([first, again, again])
        events = await self.run_turn("Track order Q9.", planner, {"track_order": {"order_id": "Q9"}})
        self.assertEqual(sum(e["action"] == "tool_call" for e in events), 1)
        self.assertEqual(sum(e["action"] == "final_response" for e in events), 1)  # not re-announced
        self.assertLessEqual(len(planner.contexts), 3)

    async def test_disabled_without_planner_opt_in(self):
        def first(context):
            return {"intent": "track", "slots": {}, "tool_calls": [{"api_name": "track_order",
                    "args": {"order_id": "Q9"}, "response_template": "Order {order_id}."}]}
        planner = Planner([first], rounds=0)
        await self.run_turn("Track order Q9.", planner, {"track_order": {"order_id": "Q9"}})
        self.assertEqual(len(planner.contexts), 1)


if __name__ == "__main__":
    unittest.main()
