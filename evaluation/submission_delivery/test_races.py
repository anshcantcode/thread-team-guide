"""Independent offline race checks. Scripted decisions are controller evidence only.

No holdout values or answer files are imported. HTTP is mocked; the accompanying
runner additionally denies sockets and records per-test outcomes and identities.
"""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from participant.agent import ParticipantAgent
from participant.planner import Planner
from tests import test_participant_controller as controller_helpers


READ = {"kind": "read_only", "description": "List storage totes by aisle.", "args": {
    "aisle": {"type": "string", "required": True}}}
WRITE = {"kind": "state_modifying", "description": "Reserve a tote for a person.", "args": {
    "tote_id": {"type": "string", "required": True, "description": "A ref returned by scan_totes."},
    "person": {"type": "string", "required": True}}}
TOOLS = {"scan_totes": READ, "reserve_tote": WRITE}
NOTE = {"create_note": {"kind": "state_modifying", "description": "Create a note.", "args": {
    "text": {"type": "string", "required": True}}, "delay_range_ms": [0, 8000]}}


def scan(aisle="D8", **extra):
    return {"api_name": "scan_totes", "args": {"aisle": aisle}, **extra}


def continuation():
    return {"api_name": "reserve_tote", "args": {"person": "Tamsin"},
            "select": {"path": "totes", "where": {"finish": "matte", "sealed": True}},
            "bindings": {"tote_id": "ref"}, "authorization": {"quote": "reserve the sealed matte tote for Tamsin"}}


def note(text="check latch", **extra):
    return {"intent": "note", "slots": {}, "tool_calls": [{"api_name": "create_note", "args": {"text": text},
            "authorization": {"quote": "Create a note"}, **extra}]}


def completion(value):
    return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(value)}]}}]})


def decision(**extra):
    return {"intent": "inspect", "slots": {}, "observations": [], "tool_calls": [],
            "clarification": None, "response": None, **extra}


class QueueChecks(unittest.IsolatedAsyncioTestCase):
    # Reuse queue plumbing only. Inheriting ControllerTests would silently rerun
    # its test methods and inflate the independent test denominator.
    asyncSetUp = controller_helpers.ControllerTests.asyncSetUp
    asyncTearDown = controller_helpers.ControllerTests.asyncTearDown
    start = controller_helpers.ControllerTests.start
    event = controller_helpers.ControllerTests.event
    speak = controller_helpers.ControllerTests.speak
    output = controller_helpers.ControllerTests.output
    result = controller_helpers.ControllerTests.result
    drain = controller_helpers.ControllerTests.drain

    async def settled(self, predicate):
        async def wait():
            while not predicate():
                await asyncio.sleep(0)
        await asyncio.wait_for(wait(), 0.6)
        # Drain the current loop's synchronous result/continuation work.
        for _ in range(6):
            await asyncio.sleep(0)


class ControllerRaceTests(QueueChecks):
    async def test_no_replacement_interruption_cancels_lookup_and_rejects_late_result(self):
        agent = await self.start(lambda _: {"tool_calls": [scan()]}, tools=TOOLS)
        await self.speak(agent, "List totes in aisle D8.")
        call = await self.output(agent, "tool_call")
        await self.event(agent, "interruption")
        cancel = await self.output(agent, "cancel_tool")
        self.assertEqual(cancel["payload"]["call_id"], call["payload"]["call_id"])
        await self.output(agent, "filler_speech")
        await self.result(agent, call, {"totes": [{"ref": "obsolete-result"}]})
        await self.settled(lambda: agent.operations[call["payload"]["call_id"]]["status"] == "success")
        self.assertEqual(len(agent.planner.contexts), 1, "An empty interruption must not replan the old request")
        self.assertFalse([row for row in self.drain(agent) if row["action"] in {"tool_call", "final_response"}])

    async def clarification_with_pending(self, followup):
        def plan(context):
            if context.get("planning_error"):
                return {"clarification": "Which tote specification should I use?", "slots": {}}
            return {"tool_calls": [scan("D8", after_result=continuation()), scan("E3", **followup)]}
        agent = await self.start(plan, tools=TOOLS)
        await self.speak(agent, "Scan aisles D8 and E3, then reserve the sealed matte tote for Tamsin.")
        fast = await self.output(agent, "tool_call")
        slow = await self.output(agent, "tool_call")
        await self.result(agent, fast, {"totes": []})
        await self.output(agent, "clarification_request")
        self.drain(agent)
        await self.result(agent, slow, {"totes": [{"ref": "TOTE-698", "finish": "matte", "sealed": True}]})
        await self.settled(lambda: agent.operations[slow["payload"]["call_id"]]["status"] == "success")
        return agent, self.drain(agent)

    async def test_clarification_does_not_allow_late_success_to_finish_the_suspended_request(self):
        _, actions = await self.clarification_with_pending({})
        self.assertFalse([row for row in actions if row["action"] in {"final_response", "tool_call"}],
                         "A late sibling result published after an unresolved clarification: " + repr(actions))

    async def test_clarification_prevents_late_result_from_dispatching_a_write(self):
        agent, actions = await self.clarification_with_pending({"after_result": continuation()})
        writes = [row for row in actions if row["action"] == "tool_call" and row["payload"]["api_name"] == "reserve_tote"]
        self.assertEqual(writes, [], "A delayed sibling continued the write after a clarification")
        self.assertFalse([op for op in agent.operations.values() if op["kind"] == "state_modifying"])

    async def test_new_identical_authorization_after_success_is_a_new_effect(self):
        agent = await self.start(lambda _: note(), tools=NOTE)
        await self.speak(agent, "Create a note saying check latch.")
        first = await self.output(agent, "tool_call")
        await self.result(agent, first, {"note_id": "NT-401"})
        await self.output(agent, "final_response")
        await self.speak(agent, "Create a note saying check latch. This is an additional note.")
        await self.settled(lambda: len(agent.planner.contexts) == 2 and agent._plan_task is None)
        calls = [row for row in self.drain(agent) if row["action"] == "tool_call"]
        self.assertEqual(len(calls), 1, "A fresh explicit user grant was swallowed by the previous successful operation")
        self.assertEqual(calls[0]["payload"]["args"], first["payload"]["args"])
        self.assertNotEqual(calls[0]["payload"]["call_id"], first["payload"]["call_id"])

    async def test_selected_write_uses_actual_second_result_row_and_all_predicates(self):
        agent = await self.start(lambda _: {"tool_calls": [scan(after_result=continuation())]}, tools=TOOLS)
        await self.speak(agent, "Scan D8 and reserve the sealed matte tote for Tamsin.")
        call = await self.output(agent, "tool_call")
        await self.result(agent, call, {"totes": [
            {"ref": "NOT-SEALED", "finish": "matte", "sealed": False},
            {"ref": "ACTUAL-975", "finish": "matte", "sealed": True}]})
        write = await self.output(agent, "tool_call")
        self.assertEqual(write["payload"]["args"], {"tote_id": "ACTUAL-975", "person": "Tamsin"})
        self.assertEqual(agent.operations[write["payload"]["call_id"]]["step"]["result_bindings"]["tote_id"],
                         {"call_id": call["payload"]["call_id"], "path": "totes.1.ref"})

    async def test_ambiguous_actual_rows_do_not_fall_back_to_the_first_write(self):
        def plan(context):
            return {"clarification": "Which of the two totes?"} if context.get("planning_error") else {"tool_calls": [scan(after_result=continuation())]}
        agent = await self.start(plan, tools=TOOLS)
        await self.speak(agent, "Scan D8 and reserve the sealed matte tote for Tamsin.")
        call = await self.output(agent, "tool_call")
        await self.result(agent, call, {"totes": [
            {"ref": "AMBIGUOUS-1", "finish": "matte", "sealed": True},
            {"ref": "AMBIGUOUS-2", "finish": "matte", "sealed": True}]})
        await self.output(agent, "clarification_request")
        self.assertFalse([op for op in agent.operations.values() if op["kind"] == "state_modifying"])

    async def test_forged_result_binding_is_rejected_even_with_a_valid_current_grant(self):
        agent = await self.start(lambda _: {"tool_calls": [scan()]}, tools=TOOLS)
        await self.speak(agent, "Scan D8 and reserve the sealed matte tote for Tamsin.")
        call = await self.output(agent, "tool_call")
        await self.result(agent, call, {"totes": [{"ref": "ACTUAL-816", "finish": "matte", "sealed": True}]})
        await self.output(agent, "final_response")
        agent._dispatch({"api_name": "reserve_tote", "args": {"tote_id": "FABRICATED-815", "person": "Tamsin"},
                         "authorization": {"quote": "reserve the sealed matte tote for Tamsin"},
                         "result_bindings": {"tote_id": {"call_id": call["payload"]["call_id"], "path": "totes.0.ref"}}},
                        selection={"finish": "matte", "sealed": True})
        await self.output(agent, "clarification_request")
        self.assertFalse([op for op in agent.operations.values() if op["kind"] == "state_modifying"])

    async def test_late_successful_write_is_recorded_without_speech_or_continuation(self):
        def plan(context):
            if context["revision"] == 1:
                return note(response_template="ORIGINAL TEMPLATE MUST NOT REPLAY {note_id}",
                            after_result={"api_name": "create_note", "args": {"text": "not-authorized"}})
            return {"intent": "inspect_panel", "slots": {"panel": "H19"}, "clarification": "Which sensor on panel H19?"}
        agent = await self.start(plan, tools=NOTE)
        await self.speak(agent, "Create a note saying check latch.")
        call = await self.output(agent, "tool_call")
        await self.event(agent, "interruption")
        await self.output(agent, "cancel_tool")
        await self.output(agent, "filler_speech")
        await self.speak(agent, "Inspect the sensor on panel H19.")
        await self.output(agent, "clarification_request")
        current = deepcopy(agent.state)
        await self.result(agent, call, {"note_id": "LATE-670"})
        await self.settled(lambda: agent.operations[call["payload"]["call_id"]]["status"] == "success")
        actions = self.drain(agent)
        await self.result(agent, call, {"note_id": "LATE-670"})
        await self.settled(lambda: agent.in_queue.empty())
        actions.extend(self.drain(agent))
        self.assertFalse([row for row in actions if row["action"] == "tool_call"])
        self.assertEqual(agent.snapshot()["actions"][0]["result"]["note_id"], "LATE-670")
        self.assertEqual(agent.state, current, "Late success must preserve the current request/clarification")
        self.assertEqual(actions, [], "A stale completion must not ground speech or resume the old effect")

    async def test_write_watchdog_expires_at_exact_boundary_only_once(self):
        agent = await self.start(lambda _: note(), tools=NOTE)
        await self.speak(agent, "Create a note saying check latch.")
        call = await self.output(agent, "tool_call")
        op = agent.operations[call["payload"]["call_id"]]
        deadline = op["deadline"]
        with patch("participant.agent.time.monotonic", return_value=deadline-0.000001):
            agent._expire_writes()
        self.assertEqual(op["status"], "pending")
        self.assertEqual(self.drain(agent), [])
        with patch("participant.agent.time.monotonic", return_value=deadline):
            agent._expire_writes()
            agent._expire_writes()
        self.assertEqual(op["status"], "unknown")
        self.assertEqual(len([row for row in self.drain(agent) if row["action"] == "final_response"]), 1)


class PlannerBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        env = patch.dict(os.environ, {"SECRET_GEMINI_API_KEY": "offline-nonsecret-sentinel", "PARTICIPANT_PREWARM": "0",
                                     "PARTICIPANT_IMAGE_EMBEDDING": "0", "PARTICIPANT_MEDIA_ROOT": str(self.root)}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    async def planner(self, handler):
        planner = Planner(transport=httpx.MockTransport(handler))
        await planner.setup()
        self.addAsyncCleanup(planner.close)
        return planner

    def context(self, event_type, payload):
        return {"revision": 1, "current_turn_start": 0, "state": {"intent": "", "slots": {}}, "tool_results": [],
                "actions": [], "observations": [], "latest_frame_index": None, "tools": TOOLS,
                "messages": [{"message_index": 0, "revision": 1, "event_type": event_type, "payload": payload}]}

    async def test_cancelled_transport_cannot_publish_its_late_success(self):
        started, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def handler(request):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()
                return completion(decision(response="Obsolete transport success"))
        planner = await self.planner(handler)
        task = asyncio.create_task(planner.plan(self.context("user_speech_chunk", {"text": "Inspect aisle D8.", "end_of_turn": True})))
        self.addAsyncCleanup(asyncio.gather, task, return_exceptions=True)
        await asyncio.wait_for(started.wait(), 0.6)
        task.cancel()
        await asyncio.wait_for(cancelled.wait(), 0.6)
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        for _ in range(12):
            await asyncio.sleep(0)
        self.assertEqual(planner.evidence[-1]["status"], "cancelled")
        self.assertEqual(planner._audio_cache, {})
        self.assertFalse([job for job in planner._pending_tasks if not job.done()])

    async def test_invalid_media_reaches_clarification_without_any_http_request(self):
        requests = []
        async def denied(request):
            requests.append(request.method)
            self.fail("Invalid media attempted HTTP")
        for name, event_type, key in (("broken.wav", "user_audio_chunk", "audio_ref"), ("broken.png", "video_frame", "image_ref")):
            with self.subTest(media=event_type):
                (self.root/name).write_bytes(b"not decodable media")
                planner = await self.planner(denied)
                agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue(), planner=planner)
                task = asyncio.create_task(agent.run())
                try:
                    await agent.in_queue.put({"event_type": "tool_manifest", "payload": {"tools": TOOLS}})
                    await agent.in_queue.put({"event_type": event_type, "payload": {key: name, "end_of_turn": True}})
                    if event_type == "video_frame":
                        await agent.in_queue.put({"event_type": "user_speech_chunk", "payload": {"text": "Inspect this storage label.", "end_of_turn": True}})
                    while True:
                        action = await asyncio.wait_for(agent.out_queue.get(), 0.8)
                        self.assertNotEqual(action["action"], "tool_call")
                        if action["action"] == "clarification_request":
                            break
                    self.assertEqual(agent.operations, {})
                    self.assertEqual(planner.evidence[-1]["status"], "media_error")
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(requests, [])


if __name__ == "__main__":
    unittest.main()
