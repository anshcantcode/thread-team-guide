"""Independent client-boundary probes; no microphone, model or network services."""
import asyncio
from copy import deepcopy
import unittest
from unittest.mock import patch

from thread_agent import fdb3_client
from thread_agent.fdb3 import ControllerBridge
from thread_agent.fdb3_client import ClientRegistry


SESSION = "a" * 32


class ClientAuthorityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.messages = []

        async def send(message):
            self.messages.append(deepcopy(message))

        self.send = send
        self.registry = ClientRegistry(asyncio.get_running_loop(), send, SESSION, "input-a", timeout=.025)

    async def asyncTearDown(self):
        self.registry.close()

    async def test_returning_to_an_old_input_token_cannot_revive_its_permission(self):
        self.registry.new_input("input-b")
        with self.assertRaises(ValueError):
            self.registry.new_input("input-a")
        self.assertEqual(self.registry.input_token, "input-b")

    async def test_a_delayed_exchange_cannot_borrow_a_new_input_token(self):
        request = {"type": "tool_request", "request_id": "b" * 32, "session_id": SESSION,
                   "input_token": "input-a", "command": "add_checklist_item", "args": {"text": "rinse lentils"}}
        self.registry.new_input("input-b")
        self.registry.input_started(1)
        result = await self.registry.exchange(request, 0, 3, "call-1")
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.messages, [])
        self.assertEqual(self.registry.records, [])

    async def test_late_matching_receipt_reconciles_once_without_repeating_the_request(self):
        reconciled = []

        async def on_late_receipt(record, result):
            reconciled.append((deepcopy(record), deepcopy(result)))

        self.registry.on_late_receipt = on_late_receipt
        request = {"type": "tool_request", "request_id": "c" * 32, "session_id": SESSION,
                   "input_token": "input-a", "command": "add_checklist_item", "args": {"text": "rinse lentils"}}
        timeout = await self.registry.exchange(request, 0, 7, "call-3")
        self.assertEqual(timeout["error"], "outcome_unknown")
        self.registry.new_input("input-b")
        self.registry.input_started(1)
        result = {"status": "success", "detail": "Added rinse lentils", "request_id": request["request_id"],
                  "session_id": SESSION, "item_id": "d" * 32, "text": "rinse lentils", "checked": False}
        message = {"type": "tool_result", "request_id": request["request_id"], "session_id": SESSION,
                   "input_token": "input-a", "result": result}
        self.assertTrue(await self.registry.receive(message))
        self.assertEqual(len(reconciled), 1)
        record, actual = reconciled[0]
        self.assertEqual(record["call_id"], "call-3")
        self.assertEqual(record["revision"], 7)
        self.assertEqual(actual, result)
        self.assertTrue(await self.registry.receive(message))
        conflicting = deepcopy(message)
        conflicting["result"]["status"] = "error"
        self.assertFalse(await self.registry.receive(conflicting))
        self.assertEqual(len(reconciled), 1)
        self.assertEqual(len([row for row in self.messages if row["type"] == "tool_request"]), 1)

    async def test_wrong_input_receipt_cannot_settle_an_operation(self):
        request = {"type": "tool_request", "request_id": "e" * 32, "session_id": SESSION,
                   "input_token": "input-a", "command": "read_checklist", "args": {}}
        await self.registry.exchange(request, 0, 1, "call-1")
        message = {"type": "tool_result", "request_id": request["request_id"], "session_id": SESSION,
                   "input_token": "unrelated-input", "result": {"status": "success", "detail": "Empty",
                   "request_id": request["request_id"], "session_id": SESSION, "items": []}}
        self.assertFalse(await self.registry.receive(message))
        self.assertEqual(self.registry.records[0]["outcome"], "unknown")

    async def test_outer_thread_wait_timeout_cannot_drop_a_later_device_receipt(self):
        reconciled, owned = [], []
        ready = asyncio.Event()
        original_schedule = asyncio.run_coroutine_threadsafe

        async def send(message):
            await self.send(message)
            if message["type"] == "tool_request":
                ready.set()

        async def reconcile(record, result):
            reconciled.append((deepcopy(record), deepcopy(result)))

        def exhausted_outer_wait(coro, loop):
            owned.append(original_schedule(coro, loop))

            class ExpiredWait:
                def result(self, timeout):
                    raise TimeoutError("Injected expiry of the calling thread's wait")

            return ExpiredWait()

        self.registry.send = send
        self.registry.timeout = 60
        self.registry.on_late_receipt = reconcile
        try:
            with patch("asyncio.run_coroutine_threadsafe", exhausted_outer_wait):
                outcome = await asyncio.to_thread(self.registry.call_with_context, "add_checklist_item",
                    {"text": "rinse lentils"}, call_id="call-1", revision=1, input_sequence=0)
            self.assertEqual(outcome["error"], "outcome_unknown")
            await asyncio.wait_for(ready.wait(), 2)
            request = next(row for row in self.messages if row["type"] == "tool_request")
            result = {"status": "success", "detail": "Added rinse lentils", "request_id": request["request_id"],
                      "session_id": SESSION, "item_id": "b" * 32, "text": "rinse lentils"}
            self.assertTrue(await self.registry.receive({"request_id": request["request_id"], "session_id": SESSION,
                "input_token": "input-a", "result": result}))
            self.assertEqual(len(reconciled), 1)
            self.assertEqual(reconciled[0][1], result)
            self.assertEqual(len([row for row in self.messages if row["type"] == "tool_request"]), 1)
        finally:
            self.registry.close()
            await asyncio.wait_for(asyncio.gather(*(asyncio.wrap_future(future) for future in owned)), 2)

    async def test_delayed_typed_task_cannot_submit_after_a_newer_input(self):
        submitted, spoken = [], []

        class Bridge:
            async def response(self, text, **kwargs):
                submitted.append(text)
                return "Added rinse lentils"

        class Session:
            def say(self, text, **kwargs):
                spoken.append(text)

        self.registry.new_input("input-b")
        self.registry.input_started(1)
        helper = getattr(fdb3_client, "typed_response", None)
        self.assertTrue(callable(helper), "Typed work needs an independently testable token-bound admission helper")
        await helper(Bridge(), self.registry, Session(), self.send, "Add rinse lentils", "input-a")
        self.assertEqual(submitted, [])
        self.assertEqual(spoken, [])
        self.assertEqual(self.messages, [])

    async def test_late_device_outcome_updates_real_controller_without_resuming_work(self):
        text = "Add rinse lentils to the checklist."
        calls = []

        class Planner:
            async def setup(self):
                pass

            async def close(self):
                pass

            async def plan(self, context):
                return {"tool_calls": [{"api_name": "add_checklist_item", "args": {"text": "rinse lentils"},
                                        "authorization": {"quote": text}}]}

        class UnknownRegistry:
            def call(self, name, **args):
                calls.append((name, deepcopy(args)))
                return {"status": "error", "error": "outcome_unknown", "detail": "No device receipt arrived"}

        bridge = ControllerBridge(deepcopy(fdb3_client.TOOLS), UnknownRegistry(), Planner())
        await bridge.start()
        try:
            await bridge.response(text, timeout=2)
            self.assertEqual(len(calls), 1)
            operation = bridge.controller.operations["call-1"]
            self.assertEqual(operation["status"], "unknown")
            record = {"call_id": "call-1", "revision": operation["revision"], "command": "add_checklist_item",
                      "args": {"text": "rinse lentils"}, "request_id": "f" * 32, "session_id": SESSION}
            result = {"status": "success", "detail": "Added rinse lentils", "item_id": "b" * 32,
                      "text": "rinse lentils", "checked": False, "request_id": record["request_id"],
                      "session_id": SESSION}
            helper = getattr(fdb3_client, "reconcile_receipt", None)
            self.assertTrue(callable(helper), "Late device receipts must reconcile into the actual controller ledger")
            await helper(bridge, record, result)
            self.assertEqual(bridge.controller.operations["call-1"]["status"], "success")
            self.assertTrue(bridge.controller.operations["call-1"]["continuation_retired"])
            self.assertEqual(bridge.calls[0]["outcome"], "success")
            self.assertEqual(bridge.calls[0]["result"], result)
            self.assertEqual(len(calls), 1)
            self.assertTrue(bridge.outputs.empty())
            await helper(bridge, record, result)
            self.assertEqual(len(calls), 1)
            self.assertTrue(bridge.outputs.empty())
        finally:
            await bridge.close()


if __name__ == "__main__":
    unittest.main()
