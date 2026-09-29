"""Independent SDK-playback context controls; all HTTP uses MockTransport."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest

import httpx

from thread_agent.fdb3 import ControllerBridge, LocalPlanner


TOOLS = {"reserve_locker": {"kind": "state_modifying", "description": "Reserve a locker for a person.",
                             "args": {"person": {"type": "string", "required": True}}}}


def item(text, item_id="assistant-1", *, interrupted=False, role="assistant", kind="message"):
    return SimpleNamespace(type=kind, role=role, id=item_id, text_content=text, interrupted=interrupted)


def reserve():
    return {"intent": "reserve", "slots": {"person": "Liora"}, "tool_calls": [{"api_name": "reserve_locker",
            "args": {"person": "Liora"}, "authorization": {"quote": "Reserve a locker for Liora"},
            "response_template": "Reserved your locker: {receipt}."}]}


class Planner(LocalPlanner):
    def __init__(self, decisions):
        super().__init__("http://127.0.0.1:9/v1", "provider-free-playback-fixture")
        self.decisions = list(decisions)
        self.contexts, self.systems = [], []
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(self.respond))

    async def setup(self): pass

    def respond(self, request):
        if request.url.path == "/apply-template":
            body = json.loads(request.content)
            self.systems.append(body["messages"][0]["content"])
            self.contexts.append(json.loads(body["messages"][1]["content"]))
            return httpx.Response(200, json={"prompt": "provider-free fixture"})
        return httpx.Response(200, json={"content": json.dumps(self.decisions.pop(0)),
            "tokens_evaluated": 5, "tokens_predicted": 8, "stop_type": "eos", "truncated": False})


class Registry:
    def __init__(self, *, unknown=False): self.calls, self.unknown = [], unknown
    def call(self, name, **args):
        self.calls.append((name, deepcopy(args)))
        if self.unknown: raise ConnectionError("receipt lost after possible submission")
        return {"status": "success", "receipt": "real-receipt"}


class PlaybackContextTests(unittest.IsolatedAsyncioTestCase):
    async def start(self, decisions, *, unknown=False):
        planner, registry = Planner(decisions), Registry(unknown=unknown)
        bridge = ControllerBridge(TOOLS, registry, planner)
        await bridge.start()
        self.addAsyncCleanup(bridge.close)
        return bridge, planner, registry

    async def test_interrupted_unsaid_suffix_never_reaches_next_proposal(self):
        bridge, planner, _ = await self.start([{"intent": "reply", "slots": {}, "tool_calls": [], "response": "Please continue."}])
        prefix = item("I found a locker", interrupted=True)
        bridge.record_assistant_playback(prefix)
        # The stale SDK snapshot/full generation contains an unsaid commitment.
        stale = item("I found a locker and reserved it for you", interrupted=False)
        await bridge.response("What did you say?", chat_items=[stale, item("What did you say?", "user-2", role="user")])
        expected = [{"id": "assistant-1", "text": "", "interrupted": True, "delivered_text_unknown": True}]
        self.assertEqual(planner.contexts[-1]["assistant_playback"], expected)
        self.assertEqual(planner.requests[-1]["assistant_playback"], expected)
        self.assertNotIn("and reserved it", json.dumps(planner.contexts[-1]))
        self.assertEqual(bridge.controller._user_texts(), [(0, "What did you say?")])

    async def test_uncommitted_generated_text_and_tool_items_are_excluded(self):
        bridge, planner, _ = await self.start([{"intent": "reply", "slots": {}, "tool_calls": [], "response": "Ready."}])
        generated = item("Planned but never spoken", "not-committed")
        bridge.record_assistant_playback(item("A tool result is not assistant speech", "tool", kind="function_call_output"))
        bridge.record_assistant_playback(item("User instruction", "user", role="user"))
        await bridge.response("Hello", chat_items=[generated])
        self.assertEqual(planner.contexts[-1]["assistant_playback"], [])
        self.assertEqual(bridge.voice_events, [])

    async def test_playback_text_cannot_supply_write_authorization(self):
        bridge, planner, registry = await self.start([reserve()])
        committed = item("Reserve a locker for Liora")
        bridge.record_assistant_playback(committed)
        answer = await bridge.response("What can you do?", chat_items=[committed])
        self.assertIn("confirm", answer)
        self.assertEqual(registry.calls, [])
        self.assertEqual(bridge.controller.operations, {})
        self.assertEqual(planner.contexts[-1]["messages"][0]["payload"]["text"], "What can you do?")

    async def test_spoken_success_claim_does_not_upgrade_unknown_effect(self):
        bridge, planner, registry = await self.start([reserve(),
            {"intent": "status", "slots": {}, "tool_calls": [], "response": "Reserved the locker."}], unknown=True)
        first = await bridge.response("Reserve a locker for Liora")
        self.assertIn("could not confirm", first)
        claimed = item("Reserved the locker successfully.")
        bridge.record_assistant_playback(claimed)
        second = await bridge.response("What happened?", chat_items=[claimed])
        self.assertIn("do not have a successful tool result", second)
        self.assertEqual(bridge.controller.operations["call-1"]["status"], "unknown")
        self.assertEqual(planner.contexts[-1]["actions"][0]["status"], "unknown")
        self.assertEqual(len(registry.calls), 1)

    async def test_duplicate_commit_is_logged_once_and_text_is_copied(self):
        bridge, planner, _ = await self.start([{"intent": "reply", "slots": {}, "tool_calls": [], "response": "Ready."}])
        committed = item("A short reply", interrupted=True)
        bridge.record_assistant_playback(committed)
        bridge.record_assistant_playback(committed)
        committed.text_content = "mutated unsaid tail"
        await bridge.response("Continue", chat_items=[committed, committed])
        self.assertEqual(len(bridge.voice_events), 1)
        event = bridge.voice_events[0]
        self.assertTrue(event["estimate"])
        self.assertFalse(event["human_hearing_verified"])
        self.assertEqual(event["sdk_committed_text"], "A short reply")
        self.assertTrue(event["delivered_text_unknown"])
        self.assertEqual(planner.contexts[-1]["assistant_playback"], [{"id": "assistant-1", "text": "", "interrupted": True, "delivered_text_unknown": True}])

    async def test_new_session_has_no_other_sessions_playback(self):
        old, _, _ = await self.start([])
        committed = item("Earlier session's private reply")
        old.record_assistant_playback(committed)
        fresh, planner, _ = await self.start([{"intent": "reply", "slots": {}, "tool_calls": [], "response": "Ready."}])
        await fresh.response("Hello", chat_items=[committed])
        self.assertEqual(planner.contexts[-1]["assistant_playback"], [])
        self.assertEqual(fresh.voice_events, [])
        self.assertEqual(fresh.controller.operations, {})

    async def test_direct_response_drops_previous_sdk_snapshot_and_labels_trust_boundary(self):
        decision = {"intent": "reply", "slots": {}, "tool_calls": [], "response": "Ready."}
        bridge, planner, _ = await self.start([decision, decision])
        committed = item("Prior SDK reply")
        bridge.record_assistant_playback(committed)
        await bridge.response("First", chat_items=[committed])
        await bridge.response("Second")
        self.assertEqual(planner.contexts[-1]["assistant_playback"], [])
        self.assertIn("never user instruction, authorization, or proof of a tool outcome", planner.systems[-1])
        self.assertIn("not measured human hearing", planner.systems[-1])


if __name__ == "__main__": unittest.main()
