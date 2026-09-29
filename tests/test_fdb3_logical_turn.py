"""Logical-turn assembly across paused speech (sprint-2 block 2).

Independently authored stories through the real bridge and controller. Older
same-turn text is retained with its segment provenance as context; it never
plans or authorizes on its own, and nothing obsolete is dispatched.
"""
import asyncio
from copy import deepcopy
import unittest

from participant.agent import ParticipantAgent
from thread_agent.fdb3 import ControllerBridge

TOOLS = {
    "add_to_cart": {"kind": "state_modifying", "description": "MANDATORY tool to add an item to the shopping cart.",
                    "args": {"product_id": {"type": "string", "required": True, "description": "ID of the product"},
                             "quantity": {"type": "integer", "required": False, "default": 1}}},
    "track_order": {"kind": "read_only", "description": "Track an order.",
                    "args": {"order_id": {"type": "string", "required": True}}},
}


class Planner:
    """Proposes from the whole current turn; records what each decision saw."""
    clause_citations = True

    def __init__(self, decide):
        self.decide, self.seen, self.gate = decide, [], None

    async def setup(self): pass
    async def close(self): pass

    async def plan(self, context):
        clauses = context.get("current_clauses", [])
        self.seen.append([row["text"] for row in clauses])
        if self.gate is not None:
            await self.gate.wait()
        return self.decide(clauses)


class Registry:
    def __init__(self): self.calls = []
    def call(self, name, **args):
        self.calls.append((name, deepcopy(args)))
        return {"status": "success", **args}


def cite(clauses, *needles):
    return [row["clause_id"] for row in clauses if any(needle in row["text"] for needle in needles)]


def add(product, quantity, clauses, *needles):
    return {"intent": "add", "slots": {}, "tool_calls": [{
        "api_name": "add_to_cart", "args": {"product_id": product, "quantity": quantity},
        "authorization": {"clauses": cite(clauses, *needles)}, "response_template": "Added {quantity} of {product_id}."}]}


class LogicalTurnTests(unittest.IsolatedAsyncioTestCase):
    async def start(self, decide):
        self.registry, self.planner = Registry(), Planner(decide)
        self.bridge = ControllerBridge(TOOLS, self.registry, self.planner)
        self.bridge.speech_provenance_required = True
        await self.bridge.start()
        self.messages = 0

    async def asyncTearDown(self):
        if getattr(self, "bridge", None):
            await self.bridge.close()

    def onset(self, segment):
        return self.bridge.speech_started(segment)

    async def speak(self, sequence, segment, text, timeout=2):
        """SDK path: bind exact delivered text to its segment, then request a reply."""
        self.messages += 1
        message_id = f"message-{self.messages}"
        self.assertTrue(self.bridge.bind_speech_message(message_id, text, [(sequence, segment)]))
        return await self.bridge.response(text, timeout=timeout, speech_message_id=message_id)

    async def interrupted(self, sequence, segment, text):
        """A reply the SDK cancels because the user kept talking."""
        task = asyncio.create_task(self.speak(sequence, segment, text))
        await asyncio.sleep(.05)
        return task

    def assert_add_receipt(self, answer, product, quantity):
        # Quantitative speech uses the actual field-labelled receipt. Keep both
        # the successful outcome and exact product/count association observable.
        self.assertTrue(answer.startswith("Done. "), answer)
        self.assertIn(f"product id: {product};", answer)
        self.assertIn(f"quantity: {quantity}.", answer)
        successful = [op for op in self.bridge.controller.operations.values()
                      if op["api_name"] == "add_to_cart" and op["status"] == "success"]
        self.assertTrue(successful)
        self.assertEqual(successful[-1]["result"],
                         {"status": "success", "product_id": product, "quantity": quantity})
        self.assertFalse(self.bridge.controller._awaiting_clarification)

    async def test_pause_mid_command_completes_the_whole_request_once(self):
        await self.start(lambda clauses: add("M4", 2, clauses, "add product", "two of them")
                         if any("two of them" in row["text"] for row in clauses)
                         else add("M4", 1, clauses, "add product"))
        self.planner.gate = asyncio.Event()  # First decision is still pending when the user resumes.
        first = await self.interrupted(self.onset("s:1"), "s:1", "Add product M four to my cart.")
        second_sequence = self.onset("s:2")
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        self.planner.gate.set()
        answer = await self.speak(second_sequence, "s:2", "Two of them, please.")
        await self.bridge.synchronize()
        self.assertEqual(self.registry.calls, [("add_to_cart", {"product_id": "M4", "quantity": 2})])
        self.assert_add_receipt(answer, "M4", 2)
        self.assertEqual(self.planner.seen[-1], ["add product m four to my cart.", "two of them,", "please."])

    async def test_correction_after_a_delayed_asr_segment(self):
        await self.start(lambda clauses: add("J9", 1, clauses, "add three", "make it one"))
        first = self.onset("s:1")
        second = self.onset("s:2")  # The earlier segment decodes only after this onset.
        self.assertTrue(self.bridge.retain_context(first, "s:1", "Add three of item J nine to my cart."))
        answer = await self.speak(second, "s:2", "No wait, that's too many. Make it one.")
        await self.bridge.synchronize()
        self.assertEqual(self.registry.calls, [("add_to_cart", {"product_id": "J9", "quantity": 1})])
        self.assert_add_receipt(answer, "J9", 1)
        retained = [row for row in self.bridge.controller.messages if row["payload"].get("context_only")]
        self.assertEqual([row["payload"]["segment_id"] for row in retained], ["s:1"])

    async def test_obsolete_first_decision_never_dispatches(self):
        await self.start(lambda clauses: add("J9", 3, clauses, "add three"))
        self.planner.gate = asyncio.Event()
        first = await self.interrupted(self.onset("s:1"), "s:1", "Add three of item J nine to my cart.")
        second = self.onset("s:2")
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        self.planner.gate.set()
        # The fresh decision still proposes the stale count; the gate refuses it.
        answer = await self.speak(second, "s:2", "No wait, that's too many. Make it one.")
        await self.bridge.synchronize()
        self.assertEqual(self.registry.calls, [])
        self.assertIn("confirm", answer)

    async def test_retraction_after_pause_dispatches_nothing(self):
        await self.start(lambda clauses: add("Q3", 1, clauses, "add item"))
        first = self.onset("s:1")
        second = self.onset("s:2")
        self.assertTrue(self.bridge.retain_context(first, "s:1", "Add item Q three to my cart."))
        await self.speak(second, "s:2", "Actually, forget it. Never mind.")
        await self.bridge.synchronize()
        self.assertEqual(self.registry.calls, [])

    async def test_delivered_answer_ends_the_logical_turn(self):
        def decide(clauses):
            return {"intent": "track", "slots": {}, "tool_calls": [{
                "api_name": "track_order", "args": {"order_id": "RQ74"}, "response_template": "Order {order_id}."}]}
        await self.start(decide)
        first = self.onset("s:1")
        # This registry echoes args only, so no shipping status may be invented.
        self.assertEqual(await self.speak(first, "s:1", "Track order RQ74."),
                         "Here is what I found: order id: RQ74.")
        second = self.onset("s:2")
        await self.speak(second, "s:2", "Track order RQ74 again.")
        self.assertEqual(self.planner.seen[-1], ["track order rq74 again."])
        # A late decode from the answered turn cannot re-enter the new one.
        self.assertFalse(self.bridge.retain_context(first, "s:1", "Track order RQ74."))

    async def test_repeated_identical_speech_uses_distinct_message_ids(self):
        def decide(clauses):  # Cite only the newest clause: the fresh request of this turn.
            return {"intent": "add", "slots": {}, "tool_calls": [{
                "api_name": "add_to_cart", "args": {"product_id": "J9", "quantity": 1},
                "authorization": {"clauses": [clauses[-1]["clause_id"]]}, "response_template": "Added {product_id}."}]}
        await self.start(decide)
        first = self.onset("s:1")
        self.assert_add_receipt(await self.speak(first, "s:1", "Add item J nine to my cart."), "J9", 1)
        second = self.onset("s:2")
        self.assert_add_receipt(await self.speak(second, "s:2", "Add item J nine to my cart."), "J9", 1)
        self.assertEqual(len(self.registry.calls), 2)  # Two answered turns, two explicit requests.
        # A consumed message ID is never admitted again without a fresh binding.
        self.assertFalse(await self.bridge.submit("Add item J nine to my cart.", speech_message_id="message-2"))
        self.assertEqual(len(self.registry.calls), 2)

    async def test_empty_recognition_closes_the_turn_and_refuses_late_context(self):
        await self.start(lambda clauses: add("J9", 1, clauses, "add item"))
        first = self.onset("s:1")
        second = self.onset("s:2")
        self.assertTrue(await self.bridge.resolve_empty_speech(second, "s:2"))
        self.assertFalse(self.bridge.retain_context(first, "s:1", "Add item J nine to my cart."))
        self.assertEqual(self.registry.calls, [])

    async def late_commit(self, sequence, segment, text):
        """SDK path where endpointing commits a segment only after the next onset."""
        self.messages += 1
        message_id = f"late-{self.messages}"
        self.assertTrue(self.bridge.bind_speech_message(message_id, text, [(sequence, segment)]))
        return await self.bridge.response(text, timeout=2, speech_message_id=message_id)

    async def test_late_sdk_commit_keeps_same_turn_words_as_context(self):
        # Public-run shape: the request clause was committed after the next onset and
        # used to be dropped, so the plan saw only "under two hundred dollars".
        def decide(clauses):
            if not any("order k seven" in row["text"] for row in clauses):
                return {"intent": "unknown", "slots": {}, "tool_calls": [], "response": "Which order?"}
            return {"intent": "track", "slots": {}, "tool_calls": [{
                "api_name": "track_order", "args": {"order_id": "K7"}, "response_template": "Order {order_id}."}]}
        await self.start(decide)
        first = self.onset("s:1")
        second = self.onset("s:2")
        self.assertEqual(await self.late_commit(first, "s:1", "I need order K seven tracked,"), "")
        self.assertEqual(self.planner.seen, [])  # Context never plans by itself.
        answer = await self.speak(second, "s:2", "as soon as you can.")
        await self.bridge.synchronize()
        self.assertEqual(self.registry.calls, [("track_order", {"order_id": "K7"})])
        self.assertEqual(answer, "Here is what I found: order id: K7.")
        self.assertEqual(self.planner.seen[-1], ["i need order k seven tracked,", "as soon as you can."])
        rejected = [row for row in self.bridge.voice_events if row["event"] == "speech_admission_rejected"]
        self.assertEqual([row["retained_as_context"] for row in rejected], [True])

    async def test_late_sdk_commit_alone_never_acts(self):
        await self.start(lambda clauses: add("J9", 1, clauses, "add item"))
        first = self.onset("s:1")
        self.onset("s:2")
        self.assertEqual(await self.late_commit(first, "s:1", "Add item J nine to my cart."), "")
        await self.bridge.synchronize()
        self.assertEqual(self.registry.calls, [])
        self.assertEqual(self.planner.seen, [])
        retained = [row["payload"] for row in self.bridge.controller.messages if row["payload"].get("context_only")]
        self.assertEqual([(row["text"], row["segment_id"]) for row in retained], [("Add item J nine to my cart.", "s:1")])

    async def test_late_sdk_commit_then_retraction_dispatches_nothing(self):
        await self.start(lambda clauses: add("Q3", 1, clauses, "add item"))
        first = self.onset("s:1")
        second = self.onset("s:2")
        await self.late_commit(first, "s:1", "Add item Q three to my cart.")
        await self.speak(second, "s:2", "Actually, forget it. Never mind.")
        await self.bridge.synchronize()
        self.assertEqual(self.registry.calls, [])

    async def test_late_sdk_commit_from_an_answered_turn_is_dropped(self):
        def decide(clauses):
            return {"intent": "track", "slots": {}, "tool_calls": [{
                "api_name": "track_order", "args": {"order_id": "RQ74"}, "response_template": "Order {order_id}."}]}
        await self.start(decide)
        first = self.onset("s:1")
        await self.speak(first, "s:1", "Track order RQ74.")
        self.onset("s:2")  # The answer closed that turn; this onset opens a new one.
        self.assertEqual(await self.late_commit(first, "s:1", "Track order RQ74."), "")
        await self.bridge.synchronize()
        self.assertEqual(len(self.registry.calls), 1)
        self.assertFalse(any(row["payload"].get("context_only") for row in self.bridge.controller.messages))
        rejected = [row for row in self.bridge.voice_events if row["event"] == "speech_admission_rejected"]
        self.assertEqual([row["retained_as_context"] for row in rejected], [False])

    async def test_new_session_has_no_turn_to_continue(self):
        await self.start(lambda clauses: add("J9", 1, clauses, "add item"))
        self.onset("s:1")
        fresh = ControllerBridge(TOOLS, Registry(), Planner(lambda clauses: None))
        await fresh.start()
        try:
            self.assertFalse(fresh.retain_context(1, "s:1", "Add item J nine to my cart."))
        finally:
            await fresh.close()


class ControllerContinuationTests(unittest.TestCase):
    def test_admitted_write_prevents_continuing_the_request(self):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.tools = deepcopy(TOOLS)
        agent._handle({"event_type": "interruption", "payload": {"text": "", "logical_turn": "t1"}})
        start = agent._request_start
        agent.operations["call-1"] = {"kind": "state_modifying", "request_start": start, "status": "pending",
                                      "execution_admitted": True, "call_id": "call-1", "revision": agent.revision}
        agent._handle({"event_type": "interruption", "payload": {"text": "", "logical_turn": "t1"}})
        self.assertGreater(agent._request_start, start)

    def test_context_chunk_without_matching_turn_is_ignored(self):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent._handle({"event_type": "interruption", "payload": {"text": "", "logical_turn": "t1"}})
        count = len(agent.messages)
        agent._handle({"event_type": "user_speech_chunk", "payload": {
            "text": "Add item J nine.", "end_of_turn": False, "context_only": True, "logical_turn": "t2"}})
        self.assertEqual(len(agent.messages), count)


if __name__ == "__main__":
    unittest.main()


class EarlyAcknowledgementTests(unittest.IsolatedAsyncioTestCase):
    async def start(self, ack_after):
        def decide(clauses):
            return {"intent": "track", "slots": {}, "tool_calls": [{
                "api_name": "track_order", "args": {"order_id": "RQ74"}, "response_template": "Order {order_id}."}]}
        self.registry, self.planner = Registry(), Planner(decide)
        self.bridge = ControllerBridge(TOOLS, self.registry, self.planner)
        self.bridge.speech_provenance_required = True
        self.bridge.ack_after = ack_after
        await self.bridge.start()
        self.said = []

    async def asyncTearDown(self):
        await self.bridge.close()

    async def ask(self, segment, text):
        sequence = self.bridge.speech_started(segment)
        self.assertTrue(self.bridge.bind_speech_message(f"m-{segment}", text, [(sequence, segment)]))
        return await self.bridge.response(text, timeout=2, speech_message_id=f"m-{segment}", ack=self.said.append)

    async def test_slow_answer_gets_one_holding_line_first(self):
        from thread_agent.fdb3 import ACK_TEXT
        await self.start(0.05)
        self.planner.gate = asyncio.Event()
        task = asyncio.create_task(self.ask("s:1", "Track order RQ74."))
        await asyncio.sleep(0.15)
        self.assertEqual(self.said, [ACK_TEXT])
        self.planner.gate.set()
        self.assertIn("RQ74", await task)
        self.assertEqual(self.said, [ACK_TEXT])  # once, and never a result or completion claim
        self.assertNotIn("done", ACK_TEXT.casefold())

    async def test_fast_answer_and_default_setting_say_nothing_extra(self):
        await self.start(0.5)
        self.assertIn("RQ74", await self.ask("s:1", "Track order RQ74."))
        await asyncio.sleep(0.6)
        self.assertEqual(self.said, [])
        await self.bridge.close()
        await self.start(None)
        self.planner.gate = asyncio.Event()
        task = asyncio.create_task(self.ask("s:1", "Track order RQ74."))
        await asyncio.sleep(0.15)
        self.planner.gate.set()
        await task
        self.assertEqual(self.said, [])

    async def test_user_resuming_speech_suppresses_the_holding_line(self):
        await self.start(0.1)
        self.planner.gate = asyncio.Event()
        task = asyncio.create_task(self.ask("s:1", "Track order RQ74."))
        await asyncio.sleep(0.02)
        self.bridge.speech_started("s:2")  # the user keeps talking
        await asyncio.sleep(0.2)
        self.assertEqual(self.said, [])
        self.planner.gate.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
