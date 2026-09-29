"""A guessed result template in a continuation triggers one repair from actual results."""
import asyncio
import unittest

from participant.agent import ParticipantAgent

TOOLS = {
    "search_products": {"kind": "read_only", "description": "Search products.",
                        "args": {"query": {"type": "string", "required": True}}},
    "add_to_cart": {"kind": "state_modifying", "description": "Add an item to the shopping cart.",
                    "args": {"product_id": {"type": "string", "required": True, "description": "ID of the product"},
                             "quantity": {"type": "integer", "required": False, "default": 1}}},
}


class Planner:
    clause_citations = True

    def __init__(self):
        self.contexts = []

    async def setup(self): pass
    async def close(self): pass

    async def plan(self, context):
        self.contexts.append(context)
        clause = context["current_clauses"][0]["clause_id"]
        if context.get("planning_error"):
            call_id = context["actions"][0]["call_id"]
            return {"intent": "add", "slots": {}, "tool_calls": [{
                "api_name": "add_to_cart", "args": {"product_id": "PROD1", "quantity": 1},
                "result_bindings": {"product_id": {"call_id": call_id, "path": "products.0.product_id"}},
                "authorization": {"clauses": [clause]}, "response_template": "Added {product_id}."}]}
        return {"intent": "add", "slots": {}, "tool_calls": [{
            "api_name": "search_products", "args": {"query": "copper kettle"}, "response_template": "",
            "after_result": {"api_name": "add_to_cart", "args": {"product_id": "{items.0.id}", "quantity": 1},
                             "authorization": {"clauses": [clause]}, "response_template": "Added {product_id}."}}]}


class PlaceholderContinuationTests(unittest.IsolatedAsyncioTestCase):
    async def test_placeholder_is_repaired_from_the_actual_result_not_dispatched(self):
        planner = Planner()
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue(), planner=planner)
        task = asyncio.create_task(agent.run())
        try:
            await agent.in_queue.put({"event_type": "tool_manifest", "payload": {"tools": TOOLS}})
            await agent.in_queue.put({"event_type": "user_speech_chunk", "payload": {
                "text": "Search for a copper kettle and add one of the result to my cart.", "end_of_turn": True}})
            calls = []
            while len(calls) < 2:
                event = await asyncio.wait_for(agent.out_queue.get(), 3)
                self.assertNotEqual(event["action"], "clarification_request", event)
                if event["action"] == "tool_call":
                    calls.append(event["payload"])
                    if event["payload"]["api_name"] == "search_products":
                        await agent.in_queue.put({"event_type": "tool_result", "payload": {
                            "call_id": event["payload"]["call_id"], "api_name": "search_products", "status": "success",
                            "result": {"status": "success", "products": [
                                {"product_id": "PROD1", "name": "copper kettle Premium", "price": 30}]}}})
            self.assertEqual([call["api_name"] for call in calls], ["search_products", "add_to_cart"])
            self.assertEqual(calls[1]["args"], {"product_id": "PROD1", "quantity": 1})
            self.assertTrue(planner.contexts[-1]["planning_error"])
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()


class ProvenanceRecoveryTests(unittest.TestCase):
    def dispatch(self, products):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.tools = dict(TOOLS)
        text = "Search for a copper kettle and add one of the result to my cart."
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": text, "end_of_turn": True}}]
        agent.operations["call-1"] = {"kind": "read_only", "status": "success", "revision": agent.revision,
                                      "request_start": 0, "call_id": "call-1", "key": "k", "api_name": "search_products",
                                      "result": {"status": "success", "products": products}}
        agent._dispatch({"api_name": "add_to_cart", "args": {"product_id": "PROD1", "quantity": 1},
                         "authorization": {"quote": "add one of the result to my cart"}, "response_template": "x"})
        return [agent.out_queue.get_nowait() for _ in range(agent.out_queue.qsize())]

    def test_unique_delivered_identifier_gains_exact_provenance(self):
        events = self.dispatch([{"product_id": "PROD1", "name": "copper kettle Premium"}])
        self.assertEqual([event["action"] for event in events], ["tool_call"], events)
        self.assertEqual(events[0]["payload"]["args"]["product_id"], "PROD1")

    def test_ambiguous_or_absent_identifier_stays_refused(self):
        for products in ([{"product_id": "PROD1"}, {"product_id": "PROD1"}], [{"product_id": "PROD2"}]):
            with self.subTest(products=products):
                self.assertEqual([event["action"] for event in self.dispatch(products)], ["clarification_request"])
