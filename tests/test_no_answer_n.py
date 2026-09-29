"""Task N: invented utterances and in-memory tools; exercise the real run loop.

Superseded speech segments may be silent. Every completed, current user turn
must receive a final_response or clarification_request, not just a filler.
"""
import asyncio
from copy import deepcopy
import inspect
import unittest

from participant.agent import ParticipantAgent


TOOLS = {
    "search_catalog": {"kind": "read_only", "description": "Search the catalog.",
                       "delay_range_ms": [0, 0],
                       "args": {"query": {"type": "string", "required": True}}},
    "track_order": {"kind": "read_only", "description": "Track an order.",
                    "delay_range_ms": [0, 0],
                    "args": {"order_id": {"type": "string", "required": True}}},
    "add_to_cart": {"kind": "state_modifying", "description": "Add a product to the cart.",
                    "delay_range_ms": [0, 0],
                    "args": {"product_id": {"type": "string", "required": True},
                             "quantity": {"type": "integer", "default": 1}}},
    "book_ticket": {"kind": "state_modifying", "description": "Book a passenger ticket.",
                    "delay_range_ms": [0, 0],
                    "args": {"passenger_name": {"type": "string", "required": True}}},
}


def step(name, args, **extra):
    return {"api_name": name, "args": args, **extra}


def decision(*calls):
    return {"intent": "request", "slots": {}, "tool_calls": list(calls)}


def read(query="brass compass", **extra):
    return step("search_catalog", {"query": query}, **extra)


def track(**extra):
    return step("track_order", {"order_id": "RD83"}, **extra)


class ScriptPlanner:
    clause_citations = True

    def __init__(self, plans, rounds=2):
        self.plans = list(plans)
        self.follow_up_rounds = rounds
        self.contexts = []

    async def setup(self):
        pass

    async def close(self):
        pass

    async def plan(self, context):
        self.contexts.append(deepcopy(context))
        plan = self.plans.pop(0) if self.plans else decision()
        result = plan(context) if callable(plan) else deepcopy(plan)
        return await result if inspect.isawaitable(result) else result


async def run_turn(text, plans, *, tools=None, hook=None, rounds=2, quiet=0.15):
    """Same queue/result harness as test_follow_up_round, with scripted races.

    hook(event, agent) returns None for the default tool receipt, or a list of
    queued input events (including [] to leave a call pending). Allow the 50 ms
    correction grace plus Windows timer granularity before declaring silence.
    No network/SDK.
    """
    planner = plans if isinstance(plans, ScriptPlanner) else ScriptPlanner(plans, rounds)
    agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue(), planner=planner)
    task = asyncio.create_task(agent.run())
    events = []
    try:
        await agent.in_queue.put({"event_type": "tool_manifest", "payload": {"tools": tools or TOOLS}})
        payload = text if isinstance(text, dict) else {"text": text, "end_of_turn": True}
        await agent.in_queue.put({"event_type": "user_speech_chunk", "payload": payload})
        while True:
            try:
                event = await asyncio.wait_for(agent.out_queue.get(), quiet)
            except asyncio.TimeoutError:
                break
            events.append(event)
            inputs = hook(event, agent) if hook else None
            if inspect.isawaitable(inputs):
                inputs = await inputs
            if inputs is None and event["action"] == "tool_call":
                call = event["payload"]
                inputs = [{"event_type": "tool_result", "payload": {
                    "call_id": call["call_id"], "api_name": call["api_name"], "status": "success",
                    "result": {"status": "success", "product_id": "BR64", "price": 18,
                               **call["args"]}}}]
            for incoming in inputs or []:
                await agent.in_queue.put(incoming)
        if task.done() and not task.cancelled():
            task.result()  # A crashed controller is a failure, not a quiet success.
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    return events, agent, planner


class NoAnswerNTests(unittest.IsolatedAsyncioTestCase):
    def answered(self, events, revision=None):
        relevant = [e for e in events if revision is None or e["state_snapshot"]["revision"] == revision]
        self.assertTrue(any(e["action"] in {"final_response", "clarification_request"}
                            and e["payload"].get("text", "").strip() for e in relevant), relevant)

    async def check(self, text, plans, **kwargs):
        events, agent, planner = await run_turn(text, plans, **kwargs)
        self.answered(events, agent.revision)
        return events, agent, planner

    async def test_unverified_read_without_dependency_answers(self):
        await self.check("If my parcel has cleared customs, track order RD83.", [decision(track())])

    async def test_all_conditional_reads_without_dependency_answer(self):
        await self.check("If my parcel has cleared customs, track order RD83. "
                         "If my travel permit arrives, search for a brass compass.",
                         [decision(track(), read())])

    async def test_false_read_alone_answers(self):
        await self.check("Track order RD83. Actually, don't track order RD83.", [decision(track())])

    async def test_conditional_read_before_successful_lookup_answers(self):
        await self.check("If all prices exceed 25 dollars, track order RD83. Search for a brass compass.",
                         [decision(track(), read())])

    async def test_held_read_after_failed_lookup_answers(self):
        def error(event, agent):
            if event["action"] == "tool_call":
                return [{"event_type": "tool_result", "payload": {
                    **event["payload"], "status": "error", "result": {"error": "not_found"}}}]
        await self.check("Search for a brass compass. If all prices exceed 25 dollars, track order RD83.",
                         [decision(read(), track())], hook=error)

    async def test_unsubmitted_current_read_answers(self):
        def refuse(event, agent):
            if event["action"] == "tool_call":
                return [{"event_type": "tool_not_submitted", "payload": event["payload"]}]
        await self.check("Search for a brass compass.", [decision(read())], hook=refuse)

    async def test_unsubmitted_current_write_answers(self):
        def refuse(event, agent):
            if event["action"] == "tool_call":
                return [{"event_type": "tool_not_submitted", "payload": event["payload"]}]
        await self.check("Add product BR64 to my cart.", [decision(step("add_to_cart",
                         {"product_id": "BR64", "quantity": 1}, authorization={"clauses": ["0.0"]}))], hook=refuse)

    async def stale_lookup(self, corrected, proposal, *, receipt=False):
        def revise(event, agent):
            if event["action"] == "tool_call" and event["payload"]["call_id"] == "call-1":
                return [{"event_type": "user_speech_chunk", "payload": {
                    "text": corrected, "end_of_turn": True, "logical_turn": "parcel-turn"}}]
            if receipt and event["action"] in {"read_held", "write_deferred"}:
                return [{"event_type": "tool_result", "payload": {
                    "call_id": "call-1", "api_name": "search_catalog", "status": "success",
                    "result": {"price": 18, "product_id": "BR64"}}}]
        return await self.check({"text": "Search for a brass compass.", "end_of_turn": True,
                                 "logical_turn": "parcel-turn"},
                                [decision(read()), decision(proposal)], hook=revise)

    async def test_unverified_read_does_not_wait_for_cancelled_revision(self):
        await self.stale_lookup("If my permit arrives, track order RD83.", track())

    async def test_price_read_does_not_wait_for_cancelled_revision(self):
        await self.stale_lookup("If all prices exceed 25 dollars, track order RD83.", track())

    async def test_false_read_not_silenced_by_cancelled_revision(self):
        await self.stale_lookup("Don't track order RD83.", track())

    async def test_late_old_lookup_cannot_strand_current_read(self):
        await self.stale_lookup("If all prices exceed 25 dollars, track order RD83.", track(), receipt=True)

    async def test_deferred_write_does_not_wait_for_cancelled_revision(self):
        await self.stale_lookup("Once you find something, add it to my cart.", step("add_to_cart",
                               {"product_id": "BR64", "quantity": 1}, authorization={"clauses": ["1.0", "1.1"]}))

    async def test_transcript_revision_waiting_for_submission_receipt_answers(self):
        write = step("add_to_cart", {"product_id": "BR64", "quantity": 1}, authorization={"clauses": ["0.0"]})
        def revise(event, agent):
            if event["action"] == "tool_call":
                return [{"event_type": "user_speech_chunk", "payload": {
                    "text": "Add product BR64 to my cart.", "end_of_turn": True,
                    "utterance_id": "cart-utterance", "transcript_revision": 2}}]
        await self.check({"text": "Add product BR64 to my cart.", "end_of_turn": True,
                         "utterance_id": "cart-utterance", "transcript_revision": 1},
                         [decision(write), decision(write)], hook=revise, quiet=0.65)

    async def test_missing_read_receipt_has_bounded_answer(self):
        await self.check("Search for a brass compass.", [decision(read())],
                         hook=lambda event, agent: [], quiet=0.65)

    async def test_malformed_read_receipt_has_bounded_answer(self):
        def malformed(event, agent):
            if event["action"] == "tool_call":
                return [{"event_type": "tool_result", "payload": {
                    **event["payload"], "status": "success", "result": None}}]
        await self.check("Search for a brass compass.", [decision(read())], hook=malformed, quiet=0.65)

    async def test_late_read_receipt_is_kept_without_resuming_expired_write(self):
        write = step("add_to_cart", {"product_id": "BR64", "quantity": 1},
                     authorization={"clauses": ["0.1"]})
        sent = False
        def late(event, agent):
            nonlocal sent
            if event["action"] == "tool_call":
                return []
            if event["action"] == "final_response" and not sent:
                sent = True
                return [{"event_type": "tool_result", "payload": {
                    "call_id": "call-1", "api_name": "search_catalog", "status": "success",
                    "result": {"product_id": "BR64"}}}]
        events, agent, planner = await self.check(
            "Search for a brass compass and add product BR64 to my cart.",
            [decision(read(after_result=write)), decision(write)], hook=late, quiet=0.65)
        self.assertEqual([e["payload"]["api_name"] for e in events if e["action"] == "tool_call"], ["search_catalog"])
        self.assertEqual(agent.operations["call-1"]["status"], "success")
        self.assertEqual(agent.state["slots"]["product_id"], "BR64")
        self.assertEqual(len(planner.contexts), 1)

    async def test_retained_consumer_without_receipt_has_bounded_answer(self):
        def revise(event, agent):
            if event["action"] == "tool_call":
                return [{"event_type": "user_speech_chunk", "payload": {
                    "text": "Keep searching for a brass compass.", "end_of_turn": True}}]
        await self.check("Search for a brass compass.",
                         [decision(read()), decision(read(retain_call_id="call-1"))], hook=revise, quiet=0.65)

    async def refreshed_write(self, kind):
        write = step("add_to_cart", {"product_id": "BR64", "quantity": 1},
                     authorization={"clauses": ["0.0"]})
        def refresh(event, agent):
            if event["action"] == "tool_call":
                changed = deepcopy(TOOLS)
                changed["add_to_cart"]["delay_range_ms"] = [0, 10]
                payload = {"tools": changed} if kind == "tool_manifest" else {"frame_id": "new-view"}
                return [{"event_type": kind, "payload": payload},
                        {"event_type": "tool_result", "payload": {
                            **event["payload"], "status": "success", "result": {"receipt_id": "OLD-RECEIPT"}}}]
        events, agent, _ = await self.check("Add product BR64 to my cart.",
                                           [decision(write), decision(write)], hook=refresh, quiet=0.8)
        self.assertEqual(sum(e["action"] == "tool_call" for e in events), 1)
        self.assertEqual(agent.operations["call-1"]["result"]["receipt_id"], "OLD-RECEIPT")
        self.assertFalse(any("OLD-RECEIPT" in e["payload"].get("text", "") for e in events))

    async def test_manifest_refresh_cannot_leave_original_user_waiting(self):
        await self.refreshed_write("tool_manifest")

    async def test_frame_refresh_cannot_leave_original_user_waiting(self):
        await self.refreshed_write("video_frame")

    async def test_transcript_receipt_before_deadline_still_dispatches_replacement(self):
        write = step("add_to_cart", {"product_id": "BR64", "quantity": 1}, authorization={"clauses": ["0.0"]})
        revised = False
        async def revise(event, agent):
            nonlocal revised
            if event["action"] == "tool_call" and not revised:
                revised = True
                return [{"event_type": "user_speech_chunk", "payload": {
                    "text": "Add product BR64 to my cart.", "end_of_turn": True,
                    "utterance_id": "cart-utterance", "transcript_revision": 2}}]
        def replanned(context):
            return decision(write)
        # The existing executor-race suite covers prompt receipts; this control
        # delivers one after the revised plan has actually deferred.
        async def revised_plan(context):
            async def receipt():
                await asyncio.sleep(0.025)
                await active[0].in_queue.put({"event_type": "tool_not_submitted", "payload": {
                    "call_id": "call-1", "api_name": "add_to_cart"}})
            scheduled.append(asyncio.create_task(receipt()))
            return decision(write)
        active, scheduled = [], []
        async def hook(event, agent):
            if not active:
                active.append(agent)
            return await revise(event, agent)
        try:
            events, agent, _ = await self.check({"text": "Add product BR64 to my cart.", "end_of_turn": True,
                                               "utterance_id": "cart-utterance", "transcript_revision": 1},
                                              [decision(write), revised_plan, replanned], hook=hook)
            self.assertEqual(agent.operations["call-1"]["status"], "not_submitted")
            self.assertEqual(sum(e["action"] == "tool_call" for e in events), 2)
            self.assertEqual(sum(e["action"] == "final_response" for e in events), 1)
        finally:
            await asyncio.gather(*scheduled)

    async def test_empty_follow_up_after_nonpublic_chain_answers(self):
        await self.check("Search for a brass compass and track order RD83.",
                         [decision(read(after_result=track())), decision()])

    async def test_borrowed_lookup_only_follow_up_keeps_answer(self):
        await self.check("Track order RD83 and see about delivery assistance.",
                         [decision(track()), decision(read("RD83"))])

    async def test_deferred_binding_then_empty_follow_up_answers(self):
        await self.check("Search for a brass compass and add one of the results to my cart.",
                         [decision(read(), step("add_to_cart", {"product_id": "BR64", "quantity": 1},
                                               authorization={"clauses": ["0.1"]})), decision()])

    async def test_repair_with_no_calls_answers(self):
        await self.check("Search for a brass compass and add one of the results to my cart.",
                         [decision(read(after_result=step("add_to_cart", {},
                                        bindings={"product_id": "missing.identifier"}))), decision()])

    async def test_second_bad_continuation_during_repair_answers(self):
        bad = step("add_to_cart", {}, bindings={"product_id": "missing.identifier"})
        async def repair(context):
            await asyncio.sleep(0.02)
            return decision()
        await self.check("Search for a brass compass and track order RD83.",
                         [decision(read(after_result=bad), track(after_result=bad)), repair])

    async def test_conflicting_name_is_answered_inside_plan(self):
        text = "Book a ticket for Selma Voss. Use Salma Voss for the passenger name."
        await self.check(text, [decision(step("book_ticket", {"passenger_name": "Salma Voss"},
                                             authorization={"clauses": ["0.0", "0.1"]}))])

    async def test_multiple_rejected_steps_still_answer(self):
        await self.check("Please help with a parcel.", [decision(step("missing_tool", {}), track())])

    async def test_planner_self_cancellation_answers(self):
        async def cancelled(context):
            raise asyncio.CancelledError
        await self.check("Search for a brass compass.", [cancelled])

    async def test_invalid_single_call_audio_observations_answer(self):
        planner = ScriptPlanner([{"observations": None, "tool_calls": []}])
        planner.audio_mode = "single_call_reads"
        await self.check("Please help with a parcel.", planner)


if __name__ == "__main__":
    unittest.main()
