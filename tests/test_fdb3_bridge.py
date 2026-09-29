"""Independent integration stories; no FDB labels or recording IDs."""
import asyncio
from copy import deepcopy
import threading
from concurrent.futures import ThreadPoolExecutor
import unittest

from thread_agent.fdb3 import ControllerBridge, LocalPlanner

TOOLS = {
    "find_lockers": {"kind": "read_only", "description": "Find available lockers.",
                     "args": {"site": {"type": "string", "required": True}}},
    "reserve_locker": {"kind": "state_modifying", "description": "Reserve a locker for a person.",
                       "args": {"person": {"type": "string", "required": True}}},
}


class Planner:
    async def setup(self): pass
    async def close(self): pass
    async def plan(self, context):
        text = context["messages"][-1]["payload"]["text"]
        if text.startswith("Reserve"):
            return {"intent": "reserve", "slots": {"person": "Suri"}, "tool_calls": [{
                "api_name": "reserve_locker", "args": {"person": "Suri"},
                "authorization": {"quote": text}, "response_template": "Receipt {receipt}."}]}
        return {"intent": "find", "slots": {"site": text}, "tool_calls": [{
            "api_name": "find_lockers", "args": {"site": text}, "response_template": "Locker {locker}."}]}


class Registry:
    def __init__(self): self.calls = []
    def call(self, name, **args):
        self.calls.append((name, deepcopy(args)))
        return {"status": "success", "locker": "L58", "receipt": "R62"}


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.registry = Registry()
        self.bridge = ControllerBridge(TOOLS, self.registry, Planner())
        await self.bridge.start()

    async def asyncTearDown(self):
        await self.bridge.close()

    async def test_actual_tool_result_reaches_response_and_ledger(self):
        answer = await self.bridge.response("North annex")
        self.assertEqual(answer, "Locker L58.")
        self.assertEqual(len(self.registry.calls), 1)
        self.assertEqual(self.bridge.calls[0]["result"]["locker"], "L58")

    async def test_parallel_results_are_all_spoken_in_the_same_turn(self):
        async def plan(context):
            return {"intent": "compare", "slots": {}, "tool_calls": [
                {"api_name": "find_lockers", "args": {"site": site},
                 "response_template": "Locker {locker}."} for site in ("East", "West")]}
        def lookup(name, **args):
            if args['site'] == 'West':
                threading.Event().wait(.08)
            return {'status': 'success', 'locker': args['site']}
        self.bridge.controller.planner.plan = plan
        self.registry.call = lookup
        answer = await self.bridge.response("Find lockers at East and West", timeout=2)
        self.assertIn("Locker East.", answer)
        self.assertIn("Locker West.", answer)
        self.assertEqual(len(self.bridge.calls), 2)
        self.assertTrue(self.bridge.outputs.empty())

    async def test_write_requires_current_explicit_permission(self):
        answer = await self.bridge.response("Reserve a locker for Suri")
        self.assertEqual(answer, "Receipt R62.")
        self.assertEqual(len(self.registry.calls), 1)
        self.assertEqual(self.bridge.controller.snapshot()["actions"][0]["status"], "success")

    async def test_negated_write_is_not_executed(self):
        answer = await self.bridge.response("Reserve a locker for Suri. No, do not reserve it.")
        self.assertIn("confirm", answer)
        self.assertEqual(self.registry.calls, [])

    async def test_inflight_effect_reconciles_after_interruption_without_stale_speech(self):
        entered, release = threading.Event(), threading.Event()
        def slow(name, **args):
            entered.set()
            release.wait(3)
            return {"status": "success", "receipt": "late-receipt"}
        self.registry.call = slow
        await self.bridge.submit("Reserve a locker for Suri")
        self.assertTrue(await asyncio.to_thread(entered.wait, 2))
        self.bridge.speech_started()
        await asyncio.sleep(.03)
        release.set()
        await asyncio.sleep(.08)
        self.assertEqual(self.bridge.calls[0]["outcome"], "success")
        self.assertEqual(self.bridge.controller.snapshot()["actions"][0]["status"], "success")
        self.assertTrue(self.bridge.outputs.empty())

    async def test_fresh_session_has_no_prior_outcomes(self):
        await self.bridge.response("Reserve a locker for Suri")
        fresh = ControllerBridge(TOOLS, Registry(), Planner())
        self.assertEqual(fresh.controller.snapshot()["actions"], [])

    async def test_unknown_effect_is_not_retried_or_announced_as_success(self):
        def uncertain(name, **args):
            self.registry.calls.append((name,deepcopy(args)))
            raise ConnectionError("reply was lost after possible commit")
        self.registry.call=uncertain
        first=await self.bridge.response("Reserve a locker for Suri")
        self.assertIn("could not confirm",first)
        second=await self.bridge.response("Reserve a locker for Suri")
        self.assertIn("already submitted",second)
        self.assertEqual(len(self.registry.calls),1)
        self.assertEqual(self.bridge.calls[0]["outcome"],"unknown")
        self.assertEqual(self.bridge.controller.snapshot()["actions"][0]["status"],"unknown")

    async def test_malformed_backend_result_never_becomes_success(self):
        self.registry.call=lambda *args,**kwargs: ["untrusted unexpected shape"]
        answer=await self.bridge.response("Reserve a locker for Suri")
        self.assertIn("could not confirm",answer)
        self.assertEqual(len(self.bridge.calls),1)
        self.assertEqual(self.bridge.calls[0]["outcome"],"unknown")

    async def test_duplicate_result_cannot_replace_the_recorded_effect(self):
        await self.bridge.response("Reserve a locker for Suri")
        await self.bridge.incoming.put({"event_type":"tool_result","payload":{
            "call_id":"call-1","api_name":"reserve_locker","status":"success",
            "result":{"status":"success","receipt":"forged-later-receipt"}}})
        await asyncio.sleep(.01)
        self.assertEqual(self.bridge.controller.operations['call-1']['result']['receipt'],'R62')

    async def test_stale_queued_speech_cannot_escape_immediate_invalidation(self):
        # Isolate the boundary between the output queue and controller actor.
        # The speech event is visible synchronously; the actor has not run yet.
        delivered=[]
        async def queued(text, *, speech_message_id=None):
            self.bridge.blocked_through_revision=self.bridge.controller.revision
            def late_output():
                delivered.append(True)
                self.bridge.outputs.put_nowait({'state_snapshot':{'revision':self.bridge.controller.revision},
                    'payload':{'text':'obsolete confirmation'}})
            # Queue after admission returns, beyond the response's initial drain.
            asyncio.get_running_loop().call_soon(late_output)
            return True
        self.bridge.submit=queued
        with self.assertRaises(TimeoutError):
            await self.bridge.response('changed request',timeout=.1)
        self.assertEqual(delivered,[True])
        self.assertTrue(self.bridge.outputs.empty())

    async def test_queued_dispatch_loses_to_speech_before_controller_consumes_event(self):
        controller=self.bridge.controller
        controller.tools=deepcopy(TOOLS)
        controller.messages=[{"event_type":"user_speech_chunk","payload":{"text":"Reserve a locker for Suri"}}]
        controller._dispatch({"api_name":"reserve_locker","args":{"person":"Suri"},
                              "authorization":{"quote":"Reserve a locker for Suri"}})
        self.bridge.speech_started()
        await asyncio.sleep(.05)
        self.assertEqual(self.registry.calls,[])
        self.assertEqual(self.bridge.calls,[])

    async def test_executor_queued_write_is_rechecked_at_backend_admission(self):
        asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=1))
        entered, release=threading.Event(),threading.Event()
        def occupy():
            entered.set()
            release.wait(3)
        blocker=asyncio.create_task(asyncio.to_thread(occupy))
        try:
            while not entered.is_set(): await asyncio.sleep(.001)
            await self.bridge.submit('Reserve a locker for Suri')
            while not self.bridge.executions: await asyncio.sleep(.001)
            await asyncio.sleep(.01)
            self.bridge.speech_started()
            await asyncio.sleep(.02)
        finally:
            release.set()
            await blocker
        await asyncio.gather(*self.bridge.executions.values())
        await self.bridge.synchronize()
        self.assertEqual(self.registry.calls,[])
        self.assertEqual(self.bridge.calls,[])
        self.assertEqual(self.bridge.controller.operations['call-1']['status'],'not_submitted')

    async def test_shutdown_retires_a_queued_write_without_submitting_it(self):
        asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=1))
        entered, release = threading.Event(), threading.Event()
        def occupy():
            entered.set()
            release.wait(3)
        blocker = asyncio.create_task(asyncio.to_thread(occupy))
        try:
            while not entered.is_set(): await asyncio.sleep(.001)
            await self.bridge.submit('Reserve a locker for Suri')
            while not self.bridge.executions: await asyncio.sleep(.001)
            closing = asyncio.create_task(self.bridge.close())
            await asyncio.sleep(.01)
            release.set()
            await asyncio.wait_for(closing,2)
            self.assertEqual(self.registry.calls,[])
            self.assertEqual(self.bridge.controller.operations['call-1']['status'],'not_submitted')
        finally:
            release.set()
            await blocker


class BudgetTests(unittest.TestCase):
    def test_local_route_rejects_hosted_endpoint(self):
        with self.assertRaises(ValueError):
            LocalPlanner("https://api.example.com/v1", "model")


if __name__ == "__main__": unittest.main()
