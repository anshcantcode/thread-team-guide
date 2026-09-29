"""Independent read-consumer regressions; no model, provider or benchmark data."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import threading
import unittest

from participant.agent import ParticipantAgent


TOOLS = {
    "lookup_shelf": {"kind": "read_only", "args": {"studio": {"type": "string", "required": True}}},
    "lookup_parcel": {"kind": "read_only", "args": {"tracking": {"type": "string", "required": True}}},
    "reserve_locker": {"kind": "state_modifying", "description": "Reserve a locker for a person.",
                       "args": {"person": {"type": "string", "required": True}}},
}


class Planner:
    async def setup(self): pass
    async def close(self): pass
    async def plan(self, context): return {"response": "No proposal."}


def lookup(**extra):
    return {"api_name": "lookup_shelf", "args": {"studio": "North"},
            "response_template": "Shelf {shelf}.", **extra}


def write():
    return {"api_name": "reserve_locker", "args": {"person": "Amara"},
            "authorization": {"quote": "Reserve a locker for Amara"}}


class ReadRetentionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue(), planner=Planner())
        self.agent.tools = deepcopy(TOOLS)
        self.turn("Find the shelf in North and parcel ZX-18.")

    async def asyncTearDown(self):
        await self.agent.close()

    def turn(self, text):
        self.agent._handle({"event_type": "user_speech_chunk", "payload": {"text": text, "end_of_turn": True}})

    def events(self, action):
        # Preserve other event types for subsequent assertions.
        rows, other = [], []
        while not self.agent.out_queue.empty():
            event = self.agent.out_queue.get_nowait()
            (rows if event["action"] == action else other).append(event)
        for event in other:
            self.agent.out_queue.put_nowait(event)
        return rows

    def start(self, step=None, *, admitted=True):
        self.agent._dispatch(step or lookup())
        call_id = self.events("tool_call")[-1]["payload"]["call_id"]
        if admitted:
            self.agent.operations[call_id]["execution_admitted"] = True
        return call_id

    def result(self, call_id, status="success", **result):
        self.agent._result({"call_id": call_id, "api_name": self.agent.operations[call_id]["api_name"],
                            "status": status, "result": {"status": status, **result}})

    def receipt(self, call_id):
        self.agent._not_submitted({"call_id": call_id, "api_name": self.agent.operations[call_id]["api_name"]})

    def retain(self, source, **extra):
        return self.agent._dispatch(lookup(retain_call_id=source, **extra))

    async def test_unrelated_read_retained_once_and_fresh_consumer_presents_actual_result(self):
        source = self.start(lookup(response_template="Old shelf {shelf}."))
        original = deepcopy(self.agent.operations[source])
        self.turn("Keep the shelf lookup; use parcel ZX-73 instead.")
        self.assertTrue(self.retain(source, response_template="Current shelf {shelf}."))
        self.agent._dispatch({"api_name": "lookup_parcel", "args": {"tracking": "ZX-73"}})
        self.assertEqual([e["payload"]["api_name"] for e in self.events("tool_call")], ["lookup_parcel"])
        self.result(source, shelf="S-42")
        self.assertEqual([e["payload"]["text"] for e in self.events("final_response")], ["Current shelf S-42."])
        self.assertEqual(self.agent.operations[source]["revision"], original["revision"])
        self.assertEqual(self.agent.operations[source]["step"], original["step"])
        consumer = self.agent.tool_results[0]
        self.assertEqual(consumer["retained_from_call_id"], source)
        self.assertEqual(consumer["revision"], self.agent.revision)
        self.assertNotEqual(consumer["call_id"], source)

    async def test_repeated_retention_same_turn_and_duplicate_results_do_not_duplicate_output(self):
        source = self.start()
        self.turn("Keep that lookup.")
        self.retain(source)
        self.retain(source)
        self.assertEqual(len(self.agent.operations), 2)
        self.result(source, shelf="S-42")
        self.result(source, shelf="CONFLICT")
        self.assertEqual(len(self.events("final_response")), 1)
        self.assertEqual(self.agent.operations[source]["result"]["shelf"], "S-42")
        self.assertEqual(self.events("tool_call"), [])

    async def test_same_revision_retention_is_outside_correction_contract(self):
        source = self.start(lookup(response_template="Original {shelf}."))
        self.assertFalse(self.retain(source, response_template="Fresh {shelf}."))
        self.assertEqual(len(self.agent.operations), 1)
        self.assertEqual(self.events("tool_call"), [])

    async def test_dependency_change_after_retention_retires_consumer(self):
        source = self.start()
        self.turn("Keep that lookup.")
        self.retain(source)
        self.agent.tools["lookup_shelf"]["description"] = "Changed service."
        self.result(source, shelf="S-42")
        self.assertEqual(self.events("final_response"), [])
        self.assertEqual(self.agent.tool_results, [])

    async def test_invalidated_consumer_cannot_supply_identifier_to_fresh_authorized_write(self):
        self.agent.tools["reserve_locker"]["args"]["locker_id"] = {"type": "string", "required": True}
        self.agent._append_message("video_frame", {"frame": "image"})
        self.agent._latest_frame = len(self.agent.messages) - 1
        index = self.agent._latest_frame
        self.agent.observations[index] = {"message_index": index, "type": "image", "visible_text": ["North"]}
        source = self.start()
        self.turn("Keep the shelf lookup then Reserve a locker for Amara")
        self.retain(source)
        consumer = list(self.agent.operations)[-1]
        self.agent._apply({"observations": [{"message_index": index, "type": "image", "visible_text": ["South"]}],
                           "response": "Checking the revised observation."})
        self.result(source, shelf="S-42", locker_id="OLD")
        step = write()
        step["args"]["locker_id"] = "OLD"
        step["result_bindings"] = {"locker_id": {"call_id": consumer, "path": "locker_id"}}
        self.agent._dispatch(step)
        self.assertEqual(self.events("tool_call"), [])
        self.assertEqual(self.agent.operations[source]["status"], "success")
        self.assertEqual(self.agent.operations[consumer]["status"], "invalidated")

    async def test_invalidated_consumer_does_not_block_fresh_same_turn_read(self):
        source = self.start()
        self.turn("Keep that lookup.")
        self.retain(source)
        self.agent.tools["lookup_shelf"]["description"] = "Changed service."
        self.result(source, shelf="OLD")
        self.agent._dispatch(lookup())
        self.assertEqual(len(self.events("tool_call")), 1)
        self.assertEqual(self.events("final_response"), [])

    async def test_later_observation_change_removes_successful_consumer_from_binding_and_context(self):
        self.agent.tools["reserve_locker"]["args"]["locker_id"] = {"type": "string", "required": True}
        self.agent._append_message("video_frame", {"frame": "image"})
        self.agent._latest_frame = len(self.agent.messages) - 1
        index = self.agent._latest_frame
        self.agent.observations[index] = {"message_index": index, "type": "image", "visible_text": ["North"]}
        source = self.start()
        self.turn("Keep the shelf lookup then Reserve a locker for Amara")
        self.retain(source)
        consumer = list(self.agent.operations)[-1]
        self.result(source, shelf="S-42", locker_id="OLD")
        self.assertEqual(self.agent.operations[consumer]["status"], "success")
        self.agent._apply({"observations": [{"message_index": index, "type": "image", "visible_text": ["South"]}],
                           "response": "Checking the revised observation."})
        step = write()
        step["args"]["locker_id"] = "OLD"
        step["result_bindings"] = {"locker_id": {"call_id": consumer, "path": "locker_id"}}
        self.agent._dispatch(step)
        self.assertEqual(self.events("tool_call"), [])
        self.assertEqual(self.agent.operations[consumer]["status"], "invalidated")
        self.assertEqual(self.agent._context()["tool_results"], [])

    async def test_dependency_change_after_success_does_not_replay_cached_readout(self):
        source = self.start()
        self.turn("Keep the lookup.")
        self.retain(source)
        self.result(source, shelf="OLD")
        self.events("final_response")
        self.agent.tools["lookup_shelf"]["description"] = "Changed service."
        self.agent._dispatch(lookup())
        self.assertEqual(len(self.events("tool_call")), 1)
        self.assertEqual(self.events("final_response"), [])

    async def test_omitted_or_later_cancelled_consumer_never_speaks(self):
        source = self.start()
        self.turn("Keep that lookup.")
        self.retain(source)
        self.turn("Cancel the shelf task.")
        self.result(source, shelf="S-42")
        self.assertEqual(self.events("final_response"), [])
        self.assertEqual(self.agent.tool_results, [])
        self.assertEqual(self.agent.operations[source]["status"], "success")

    async def test_old_continuation_never_resumes(self):
        self.turn("Find a shelf then Reserve a locker for Amara")
        source = self.start(lookup(after_result=write()))
        self.turn("Keep only the shelf lookup.")
        self.retain(source)
        self.result(source, shelf="S-42")
        self.assertEqual(self.events("tool_call"), [])
        self.assertEqual(len(self.events("final_response")), 1)

    async def test_new_continuation_requires_fresh_authority(self):
        self.turn("Find a shelf then Reserve a locker for Amara")
        source = self.start()
        self.turn("Keep only the shelf lookup.")
        self.retain(source, after_result=write())
        self.result(source, shelf="S-42")
        self.assertEqual(self.events("tool_call"), [])
        self.assertTrue(self.events("clarification_request"))
        self.assertEqual(self.agent._consumed_grants, set())

    async def test_fresh_authority_can_authorize_new_continuation(self):
        source = self.start()
        self.turn("Keep the shelf lookup then Reserve a locker for Amara")
        self.retain(source, after_result=write())
        self.result(source, shelf="S-42")
        self.assertEqual([e["payload"]["api_name"] for e in self.events("tool_call")], ["reserve_locker"])

    async def test_unknown_write_not_upgraded_or_retried_by_read_retention(self):
        self.turn("Reserve a locker for Amara")
        effect = self.start(write())
        self.result(effect, "error", error="timeout")
        self.turn("Find the shelf.")
        source = self.start()
        self.turn("Keep the lookup then Reserve a locker for Amara")
        self.retain(source, after_result=write())
        self.result(source, shelf="S-42")
        self.assertEqual(self.events("tool_call"), [])
        self.assertEqual(self.agent.operations[effect]["status"], "unknown")

    async def test_changed_args_or_api_are_rejected(self):
        for extra in ({"args": {"studio": "South"}}, {"api_name": "lookup_parcel", "args": {"tracking": "ZX-18"}}):
            with self.subTest(extra=extra):
                source = self.start()
                self.turn("Keep that lookup.")
                self.assertFalse(self.retain(source, **extra))
                self.assertEqual(self.events("tool_call"), [])
                self.turn("Find the shelf again.")

    async def test_changed_manifest_is_rejected(self):
        source = self.start()
        self.turn("Keep that lookup.")
        self.agent.tools["lookup_shelf"]["description"] = "Different data service."
        self.assertFalse(self.retain(source))
        self.assertEqual(self.events("tool_call"), [])

    async def test_changed_frame_or_observation_is_rejected(self):
        self.agent._append_message("video_frame", {"frame": "first"})
        self.agent._latest_frame = len(self.agent.messages) - 1
        source = self.start()
        self.turn("Keep that lookup.")
        self.agent.observations[self.agent._latest_frame] = {"visible_text": ["Changed label"]}
        self.assertFalse(self.retain(source))
        self.assertEqual(self.events("tool_call"), [])

    async def test_new_frame_and_audio_source_are_rejected(self):
        for media in ("video_frame", "user_audio_chunk"):
            with self.subTest(media=media):
                source = self.start()
                self.turn("Keep that lookup.")
                self.agent._append_message(media, {"data": "new"})
                if media == "video_frame":
                    self.agent._latest_frame = len(self.agent.messages) - 1
                self.assertFalse(self.retain(source))
                self.assertEqual(self.events("tool_call"), [])
                self.turn("Find the shelf again.")

    async def test_changed_result_evidence_is_rejected(self):
        source = self.start(lookup(result_evidence={"path": "title", "contains": "First"}))
        self.turn("Keep that lookup.")
        self.assertFalse(self.retain(source, result_evidence={"path": "title", "contains": "Second"}))
        self.assertEqual(self.events("tool_call"), [])

    async def test_equal_values_from_changed_result_binding_cannot_retain(self):
        first = self.start()
        self.result(first, shelf="North", other="North")
        self.turn("Use North for another lookup.")
        source = self.start(lookup(result_bindings={"studio": {"call_id": first, "path": "shelf"}}))
        self.turn("Keep the lookup for North.")
        self.assertFalse(self.retain(source, result_bindings={"studio": {"call_id": first, "path": "other"}}))
        self.assertEqual(self.events("tool_call"), [])

    async def test_consumer_cannot_receive_fabricated_result_before_source(self):
        source = self.start()
        self.turn("Keep that lookup.")
        self.retain(source)
        consumer = list(self.agent.operations)[-1]
        self.result(consumer, shelf="FABRICATED")
        self.assertEqual(self.agent.operations[consumer]["status"], "pending")
        self.assertEqual(self.events("final_response"), [])
        self.result(source, shelf="S-42")
        self.assertEqual(self.agent.operations[consumer]["result"]["shelf"], "S-42")

    async def test_newer_retention_uses_only_latest_consumer(self):
        source = self.start()
        self.turn("Keep the lookup.")
        self.retain(source, response_template="Superseded {shelf}.")
        self.turn("Keep the lookup with this latest response.")
        self.retain(source, response_template="Latest {shelf}.")
        self.result(source, shelf="S-42")
        self.assertEqual([e["payload"]["text"] for e in self.events("final_response")], ["Latest S-42."])
        self.assertEqual(self.events("tool_call"), [])

    async def test_completed_result_is_not_a_cross_turn_cache(self):
        source = self.start()
        self.result(source, shelf="S-42")
        self.turn("Keep that lookup.")
        self.assertFalse(self.retain(source))
        self.assertEqual(self.events("tool_call"), [])

    async def test_fresh_lookup_without_retention_executes_again(self):
        source = self.start()
        self.turn("Refresh the shelf lookup.")
        self.agent._dispatch(lookup())
        self.assertEqual(len(self.events("tool_call")), 1)
        self.assertNotIn("retained_from_call_id", list(self.agent.operations.values())[-1])
        self.assertEqual(self.agent.operations[source]["status"], "cancel_requested")

    async def test_explicit_refresh_cannot_retain(self):
        source = self.start()
        self.turn("Refresh the shelf lookup.")
        self.assertFalse(self.retain(source, refresh=True))
        self.assertEqual(self.events("tool_call"), [])

    async def test_fresh_session_has_no_retention_source(self):
        self.assertFalse(self.retain("call-918"))
        self.assertEqual(self.agent.operations, {})

    async def test_queued_source_waits_for_trusted_receipt_then_dispatches_current_read(self):
        source = self.start(admitted=False)
        self.turn("Keep the shelf lookup.")
        self.assertTrue(self.retain(source))
        self.assertEqual(self.events("tool_call"), [])
        self.receipt(source)
        calls = self.events("tool_call")
        self.assertEqual(len(calls), 1)
        current = self.agent.operations[calls[0]["payload"]["call_id"]]
        self.assertEqual(current["revision"], self.agent.revision)
        self.assertNotIn("retain_call_id", current["step"])
        self.assertNotIn("retained_from_call_id", current)
        self.receipt(source)
        self.assertEqual(self.events("tool_call"), [])

    async def test_missing_receipt_does_not_assume_unadmitted(self):
        source = self.start(admitted=False)
        self.turn("Keep that lookup.")
        self.retain(source)
        await asyncio.sleep(0)
        self.assertEqual(self.events("tool_call"), [])
        self.assertEqual(self.agent.operations[source]["status"], "cancel_requested")

    async def test_newer_correction_retires_deferred_read(self):
        source = self.start(admitted=False)
        self.turn("Keep that lookup.")
        self.retain(source)
        self.turn("Cancel the shelf task.")
        self.receipt(source)
        self.assertEqual(self.events("tool_call"), [])

    async def test_changed_dependency_before_receipt_prevents_dispatch(self):
        source = self.start(admitted=False)
        self.turn("Keep that lookup.")
        self.retain(source)
        self.agent.tools["lookup_shelf"]["description"] = "Changed service."
        self.receipt(source)
        self.assertEqual(self.events("tool_call"), [])

    async def test_known_not_submitted_source_dispatches_fresh_read(self):
        source = self.start(admitted=False)
        self.turn("Keep that lookup.")
        self.receipt(source)
        self.assertTrue(self.retain(source))
        self.assertEqual(len(self.events("tool_call")), 1)

    async def test_late_actual_result_for_unconfirmed_admission_does_not_retry(self):
        source = self.start(admitted=False)
        self.turn("Keep that lookup.")
        self.retain(source)
        self.result(source, shelf="S-42")
        self.assertEqual(self.events("tool_call"), [])
        self.assertTrue(self.events("clarification_request"))

    async def test_current_retained_read_transient_failure_gets_one_fresh_retry(self):
        source = self.start()
        self.turn("Keep that lookup.")
        self.retain(source)
        self.result(source, "error", error="timeout")
        calls = self.events("tool_call")
        self.assertEqual(len(calls), 1)
        self.result(calls[0]["payload"]["call_id"], "error", error="timeout")
        self.assertEqual(self.events("tool_call"), [])


class ReadRetentionBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, *, queued):
        from thread_agent.fdb3 import ControllerBridge

        class ScriptedPlanner(Planner):
            async def plan(self, context):
                if len(context["messages"]) == 1:
                    return {"tool_calls": [lookup()]}
                source = next(op for op in context["actions"] if op["api_name"] == "lookup_shelf")
                return {"tool_calls": [lookup(retain_call_id=source["call_id"]),
                                      {"api_name": "lookup_parcel", "args": {"tracking": "ZX-73"},
                                       "response_template": "Parcel {parcel}."}]}

        release = threading.Event()

        class Registry:
            def __init__(self): self.calls = []
            def call(self, name, **args):
                self.calls.append((name, args))
                if name == "lookup_shelf":
                    if not queued:
                        release.wait(3)
                    return {"status": "success", "shelf": "S-42"}
                return {"status": "success", "parcel": "P-73"}

        async def until(predicate):
            async with asyncio.timeout(3):
                while not predicate():
                    await asyncio.sleep(.005)

        registry = Registry()
        bridge = ControllerBridge(TOOLS, registry, ScriptedPlanner())
        occupied = None
        if queued:
            asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=1))
            occupied = asyncio.get_running_loop().run_in_executor(None, release.wait, 3)
        await bridge.start()
        try:
            await bridge.submit("Find the shelf in North.")
            await until(lambda: bool(bridge.controller.operations) if queued else bool(registry.calls))
            source = next(iter(bridge.controller.operations))
            answer = asyncio.create_task(bridge.response("Keep the shelf lookup; use parcel ZX-73 instead.", timeout=3))
            marker = "awaiting_not_submitted_call_id" if queued else "retained_from_call_id"
            await until(lambda: any(marker in op for op in bridge.controller.operations.values()))
            release.set()
            text = await answer
            self.assertIn("Shelf S-42.", text)
            self.assertIn("Parcel P-73.", text)
            self.assertEqual([name for name, _ in registry.calls].count("lookup_shelf"), 1)
            self.assertEqual([name for name, _ in registry.calls].count("lookup_parcel"), 1)
            self.assertEqual(bridge.controller.operations[source]["status"], "not_submitted" if queued else "success")
        finally:
            release.set()
            if occupied is not None:
                await occupied
            await bridge.close()

    async def test_admitted_read_runs_once_across_correction(self):
        await self.exercise(queued=False)

    async def test_saturated_executor_replaces_only_after_trusted_not_submitted(self):
        await self.exercise(queued=True)


if __name__ == "__main__":
    unittest.main()
