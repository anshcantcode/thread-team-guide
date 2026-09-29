"""Authored ASR/controller regressions; no provider, audio model, or benchmark data."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import threading
import unittest

from participant.agent import ParticipantAgent
from thread_agent.fdb3 import ControllerBridge


TOOLS = {"reserve_locker": {"kind": "state_modifying", "description": "Reserve a locker for a person.",
                             "args": {"person": {"type": "string", "required": True}}}}


def speech(text, revision=0, *, final=False, utterance="utterance-a"):
    return {"event_type": "user_speech_chunk", "payload": {"text": text, "end_of_turn": final,
            "utterance_id": utterance, "transcript_revision": revision}}


def proposal(person="Amara", quote=None):
    return {"intent": "reserve", "slots": {"person": person}, "tool_calls": [{"api_name": "reserve_locker",
            "args": {"person": person}, "authorization": {"quote": quote or "Reserve a locker for " + person},
            "response_template": "Receipt {receipt}."}]}


class Planner:
    def __init__(self): self.contexts = []
    async def setup(self): pass
    async def close(self): pass
    async def plan(self, context):
        self.contexts.append(deepcopy(context))
        return {"response": "No action proposed."}


class TranscriptRevisionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.planner = Planner()
        self.agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue(), planner=self.planner)
        self.agent.tools = deepcopy(TOOLS)

    async def asyncTearDown(self):
        await self.agent.close()

    def actions(self, kind):
        rows = []
        while not self.agent.out_queue.empty():
            item = self.agent.out_queue.get_nowait()
            if item["action"] == kind: rows.append(item)
        return rows

    async def test_provisional_hypotheses_never_plan_append_words_or_authorize(self):
        self.agent._handle(speech("Reserve a locker for Amara", 1))
        self.agent._handle(speech("Reserve a locker for Nila", 2))
        await asyncio.sleep(0)
        self.agent._apply(proposal("Amara"))  # Adversarial stale proposal cannot dispatch.
        self.assertIsNone(self.agent._plan_task)
        self.assertEqual(self.planner.contexts, [])
        self.assertEqual(self.agent.operations, {})
        self.assertEqual(len(self.agent.messages), 1)
        self.assertEqual(self.agent.messages[0]["payload"]["text"], "")
        self.assertNotIn("Amara", repr(self.agent._user_texts()))
        self.assertNotIn("Nila", repr(self.agent._user_texts()))

    async def test_only_new_final_replaces_whole_text_and_authorizes(self):
        self.agent._handle(speech("Reserve a locker for Amara", 1))
        self.agent._handle(speech("Reserve a locker for Nila", 2, final=True))
        self.agent._apply(proposal("Nila"))
        calls = self.actions("tool_call")
        self.assertEqual([c["payload"]["args"] for c in calls], [{"person": "Nila"}])
        self.assertEqual(self.agent._user_texts(), [(0, "Reserve a locker for Nila")])
        self.assertEqual(len(self.agent.messages), 1)
        self.assertEqual(self.agent.messages[0]["revision"], self.agent.revision)

    async def test_replaced_grant_cannot_be_used_by_stale_planner(self):
        self.agent._handle(speech("Reserve a locker for Amara", 1))
        self.agent._handle(speech("Do not reserve a locker for Amara", 2, final=True))
        self.agent._apply(proposal("Amara"))
        self.assertEqual(self.agent.operations, {})
        self.assertTrue(self.actions("clarification_request"))

    async def test_duplicate_and_out_of_order_finals_do_not_reopen_or_append(self):
        final = speech("Reserve a locker for Nila", 8, final=True)
        self.agent._handle(final)
        self.agent._apply(proposal("Nila"))
        revision, messages = self.agent.revision, deepcopy(self.agent.messages)
        for event in [final, speech("Reserve a locker for Amara", 7, final=True),
                      speech("Reserve a locker for Amara", 8, final=True), speech("unfinished", 4)]:
            self.agent._handle(event)
        self.assertEqual(self.agent.revision, revision)
        self.assertEqual(self.agent.messages, messages)
        self.assertEqual(len(self.agent.operations), 1)

    async def test_same_revision_final_is_not_a_monotonic_update(self):
        self.agent._handle(speech("Reserve a locker for Amara", 3))
        self.agent._handle(speech("Reserve a locker for Nila", 3, final=True))
        self.assertTrue(self.agent._turn_open)
        self.assertIsNone(self.agent._plan_task)
        self.assertEqual(self.agent._user_texts(), [(0, "")])

    async def test_revised_final_removes_old_slots_and_observations(self):
        self.agent.state = {"intent": "earlier", "slots": {"location": "West annex"}}
        self.agent._handle(speech("Reserve a locker for Amara", 1, final=True))
        self.agent._apply({"intent": "reserve", "slots": {"person": "Amara"}, "response": "Checking."})
        self.agent.observations[0] = {"transcript": "obsolete", "type": "audio"}
        self.agent._handle(speech("Reserve a locker for Nila", 2, final=True))
        self.assertEqual(self.agent.state, {"intent": "earlier", "slots": {"location": "West annex"}})
        self.assertEqual(self.agent.observations, {})
        self.assertNotIn("Amara", repr(self.agent._context()))

    async def test_partial_after_final_cancels_pending_plan_and_removes_authority(self):
        self.agent._handle(speech("Reserve a locker for Amara", 1, final=True))
        old = self.agent._plan_task
        self.agent._handle(speech("Wait", 2))
        await asyncio.sleep(0)
        self.assertTrue(old.cancelled())
        self.assertIsNone(self.agent._plan_task)
        self.assertEqual(self.agent.messages[0]["payload"]["text"], "")
        self.agent._apply(proposal("Amara"))
        self.assertEqual(self.agent.operations, {})

    async def test_actor_discards_late_plan_for_replaced_final(self):
        entered = asyncio.Event()
        async def plan(context):
            text = context["messages"][-1]["payload"]["text"]
            if "Amara" in text:
                entered.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    return proposal("Amara")  # A badly behaved planner swallows cancellation.
            return proposal("Nila")
        self.planner.plan = plan
        task = asyncio.create_task(self.agent.run())
        try:
            await self.agent.in_queue.put(speech("Reserve a locker for Amara", 1, final=True))
            await asyncio.wait_for(entered.wait(), 1)
            await self.agent.in_queue.put(speech("Reserve a locker for Nila", 2, final=True))
            async with asyncio.timeout(1):
                while True:
                    event = await self.agent.out_queue.get()
                    if event["action"] == "tool_call": break
            self.assertEqual(event["payload"]["args"], {"person": "Nila"})
            self.assertEqual(len(self.agent.operations), 1)
            self.assertNotIn("Amara", repr(self.agent._context()))
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_retired_utterance_cannot_change_newer_turn(self):
        self.agent._handle(speech("Reserve a locker for Amara", 1, final=True))
        self.agent._handle(speech("Reserve a locker for Nila", 1, final=True, utterance="utterance-b"))
        before = deepcopy(self.agent._context())
        self.agent._handle(speech("Reserve a locker for Cora", 99, final=True))
        self.assertEqual(self.agent._context(), before)
        self.agent._apply(proposal("Nila"))
        self.assertEqual(self.actions("tool_call")[0]["payload"]["args"], {"person": "Nila"})

    async def test_submitted_outcome_retained_and_revised_final_cannot_duplicate_effect(self):
        self.agent._handle(speech("Reserve a locker for Amara", 1, final=True))
        self.agent._apply(proposal("Amara"))
        self.actions("tool_call")
        self.agent._handle(speech("Reserve a locker for Nila", 2, final=True))
        self.agent._handle({"event_type": "tool_result", "payload": {"call_id": "call-1", "api_name": "reserve_locker",
                            "status": "success", "result": {"status": "success", "receipt": "real-receipt"}}})
        self.agent._apply(proposal("Nila"))
        self.assertEqual(len(self.agent.operations), 1)
        self.assertEqual(self.agent.operations["call-1"]["result"]["receipt"], "real-receipt")
        self.assertEqual(self.actions("tool_call"), [])

    async def test_proven_not_submitted_allows_new_final_with_same_grant(self):
        self.agent._handle(speech("Reserve a locker for Amara", 1, final=True))
        self.agent._apply(proposal("Amara"))
        self.agent.operations["call-1"]["status"] = "not_submitted"
        self.agent._handle(speech("Reserve a locker for Amara", 2, final=True))
        self.agent._apply(proposal("Amara"))
        self.assertEqual(len(self.agent.operations), 2)
        self.assertEqual(self.agent.operations["call-2"]["status"], "pending")

    async def test_not_submitted_grant_is_released_once_not_for_each_replacement_tool(self):
        self.agent.tools["reserve_locker_alternate"] = deepcopy(TOOLS["reserve_locker"])
        self.agent._handle(speech("Reserve a locker for Amara", 1, final=True))
        self.agent._apply(proposal("Amara"))
        self.agent.operations["call-1"]["status"] = "not_submitted"
        self.actions("tool_call")
        self.agent._handle(speech("Reserve a locker for Amara", 2, final=True))
        decision = proposal("Amara")
        alternate = deepcopy(decision["tool_calls"][0])
        alternate["api_name"] = "reserve_locker_alternate"
        decision["tool_calls"].append(alternate)
        self.agent._apply(decision)
        calls = self.actions("tool_call")
        self.assertEqual([call["payload"]["api_name"] for call in calls], ["reserve_locker"])
        self.assertEqual(len(self.agent.operations), 2)

    async def test_admitted_operation_rejects_not_submitted_notification(self):
        self.agent._handle(speech("Reserve a locker for Amara", 1, final=True))
        self.agent._apply(proposal("Amara"))
        self.agent.operations["call-1"]["execution_admitted"] = True
        self.agent._handle(speech("Reserve a locker for Nila", 2, final=True))
        self.agent._handle({"event_type": "tool_not_submitted", "payload": {"call_id": "call-1", "api_name": "reserve_locker"}})
        self.assertEqual(self.agent.operations["call-1"]["status"], "cancel_requested")
        self.agent._apply(proposal("Nila"))
        self.assertEqual(len(self.agent.operations), 1)

    async def test_mismatched_not_submitted_notification_cannot_release_grant(self):
        self.agent._handle(speech("Reserve a locker for Amara", 1, final=True))
        self.agent._apply(proposal("Amara"))
        before = deepcopy(self.agent._consumed_grants)
        for payload in [{"call_id": "call-1", "api_name": "other"}, {"call_id": "missing", "api_name": "reserve_locker"}, {"call_id": []}]:
            self.agent._handle({"event_type": "tool_not_submitted", "payload": payload})
        self.assertEqual(self.agent.operations["call-1"]["status"], "pending")
        self.assertEqual(self.agent._consumed_grants, before)

    async def test_not_submitted_receipt_cannot_reopen_a_newer_provisional_turn(self):
        self.agent._handle(speech("Reserve a locker for Amara", 1, final=True))
        self.agent._apply(proposal("Amara"))
        self.agent._handle(speech("Reserve a locker for Nila", 2, final=True))
        self.agent._apply(proposal("Nila"))
        self.assertEqual(self.agent._deferred_transcript_revision, self.agent.revision)
        self.agent._handle(speech("Reserve a locker for", 3))
        self.agent._handle({"event_type": "tool_not_submitted", "payload": {"call_id": "call-1", "api_name": "reserve_locker"}})
        self.assertTrue(self.agent._turn_open)
        self.assertIsNone(self.agent._plan_task)
        self.assertIsNone(self.agent._deferred_transcript_revision)
        self.assertEqual(self.agent.operations["call-1"]["status"], "not_submitted")
        self.assertEqual(len(self.agent.operations), 1)

    async def test_internal_barrier_follows_queued_correction_and_ledger_receipt(self):
        self.agent._handle(speech("Reserve a locker for Amara", 1, final=True))
        self.agent._apply(proposal("Amara"))
        observed = []
        agent = self.agent
        class Barrier(asyncio.Event):
            def set(self):
                observed.append((agent.operations["call-1"]["status"], agent._user_texts()))
                super().set()
        ready = Barrier()
        # Deliberately put the barrier before the receipt and correction in one batch.
        await agent.in_queue.put({"event_type": "controller_barrier", "payload": {"ready": ready}})
        await agent.in_queue.put({"event_type": "tool_not_submitted", "payload": {"call_id": "call-1", "api_name": "reserve_locker"}})
        await agent.in_queue.put(speech("Reserve a locker for Nila", 2, final=True))
        task = asyncio.create_task(agent.run())
        try:
            await asyncio.wait_for(ready.wait(), 1)
            self.assertEqual(observed, [("not_submitted", [(0, "Reserve a locker for Nila")])])
            self.assertTrue(all(message["event_type"] != "controller_barrier" for message in agent.messages))
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_legacy_chunks_still_append_and_retire_versioned_input(self):
        self.agent._handle(speech("Old", 1))
        for text, final in [("Reserve a locker", False), ("for Amara", True)]:
            self.agent._handle({"event_type": "user_speech_chunk", "payload": {"text": text, "end_of_turn": final}})
        self.assertEqual([m["payload"]["text"] for m in self.agent.messages], ["", "Reserve a locker", "for Amara"])
        before = deepcopy(self.agent.messages)
        self.agent._handle(speech("Revived old text", 9, final=True))
        self.assertEqual(self.agent.messages, before)
        self.agent._apply(proposal("Amara"))
        self.assertEqual(len(self.agent.operations), 1)

    async def test_malformed_revision_metadata_never_falls_back_to_legacy_authority(self):
        for update in [{"utterance_id": ""}, {"utterance_id": 9}, {"transcript_revision": True},
                       {"transcript_revision": -1}, {"transcript_revision": "4"}, {"end_of_turn": "yes"}]:
            event = speech("Reserve a locker for Amara", 4, final=True)
            event["payload"].update(update)
            self.agent._handle(event)
        for missing in ("utterance_id", "transcript_revision"):
            event = speech("Reserve a locker for Amara", 4, final=True)
            event["payload"].pop(missing)
            self.agent._handle(event)
        self.assertEqual(self.agent.messages, [])
        self.assertEqual(self.agent.revision, 0)


class ClarificationClaimTests(unittest.TestCase):
    def test_unsubmitted_send_note_cannot_claim_sent_in_clarification(self):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.tools = {"send_note": {"kind": "state_modifying", "description": "Send a note.", "args": {}}}
        agent._apply({"clarification": "I sent the note. Would you like anything else?"})
        event = agent.out_queue.get_nowait()
        self.assertEqual(event["action"], "clarification_request")
        self.assertEqual(event["payload"]["text"], "I do not have a successful tool result confirming that action.")
        self.assertEqual(agent.operations, {})


class TranscriptExecutorRaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_saturated_executor_replans_latest_final_after_old_call_not_submitted(self):
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
        entered, release = threading.Event(), threading.Event()
        def occupy():
            entered.set()
            release.wait(3)
        blocker = asyncio.create_task(asyncio.to_thread(occupy))
        latest_planned = asyncio.Event()
        class RevisionPlanner(Planner):
            async def plan(self, context):
                text = context["messages"][-1]["payload"]["text"]
                person = "Nila" if "Nila" in text else "Amara"
                if person == "Nila": latest_planned.set()
                return proposal(person)
        class Registry:
            def __init__(self): self.calls = []
            def call(self, name, **args):
                self.calls.append((name, args))
                return {"status": "success", "receipt": "confirmed"}
        registry = Registry()
        bridge = ControllerBridge(TOOLS, registry, RevisionPlanner())
        await bridge.start()
        try:
            async with asyncio.timeout(1):
                while not entered.is_set(): await asyncio.sleep(.001)
                await bridge.incoming.put(speech("Reserve a locker for Amara", 1, final=True))
                while not bridge.executions: await asyncio.sleep(.001)
                await bridge.incoming.put(speech("Reserve a locker for Nila", 2, final=True))
                await latest_planned.wait()
                while bridge.controller._deferred_transcript_revision is None: await asyncio.sleep(.001)
            self.assertEqual(registry.calls, [])
            self.assertFalse(any(event["action"] == "final_response" for event in bridge.events))
            release.set()
            await blocker
            async with asyncio.timeout(1):
                while not registry.calls: await asyncio.sleep(.001)
            self.assertEqual(registry.calls, [("reserve_locker", {"person": "Nila"})])
            self.assertEqual(bridge.controller.operations["call-1"]["status"], "not_submitted")
        finally:
            release.set()
            await blocker
            await bridge.close()


if __name__ == "__main__": unittest.main()
