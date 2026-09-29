"""Provider-free negative controls; native persistence has separate device tests."""
import base64
import asyncio
import json
import subprocess
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from thread_agent.fdb3 import ControllerBridge
from thread_agent.fdb3_extension import EmulatorRegistry, ExtensionPlanner, TOOLS, encode_request, validate_arguments


class ExtensionTests(unittest.TestCase):
    def test_arguments_and_shell_boundary(self):
        text = 'Wash "café"; $(touch /tmp/oops) & < > |\nnext'
        encoded = encode_request({"text": text})
        self.assertRegex(encoded, r"^[A-Za-z0-9_=-]+$")
        self.assertEqual(json.loads(base64.urlsafe_b64decode(encoded)), {"text": text})
        validate_arguments("add_checklist_item", {"text": text})
        for name, args in [("request_timer_handoff", {"seconds": True, "label": "Tea"}),
                           ("request_timer_handoff", {"seconds": 86401, "label": "Tea"}),
                           ("set_checklist_item", {"item_id": "../prefs", "checked": True}),
                           ("add_checklist_item", {"text": "\0"}),
                           ("read_checklist", {"path": "../secret"})]:
            with self.subTest(name=name, args=args), self.assertRaises(ValueError):
                validate_arguments(name, args)

    def test_only_explicit_emulator_and_fixed_result_path(self):
        for serial in ["", "device-123", "emulator-5554;id", "127.0.0.1:5555"]:
            with self.assertRaises(ValueError): EmulatorRegistry(serial)
        registry = EmulatorRegistry("emulator-5554")
        with self.assertRaises(ValueError): registry.exchange("read_checklist", request_id="../../private")

    def test_argv_encoding_and_receipt_identity(self):
        calls = []
        request_id = "b" * 32
        session_id = "a" * 32
        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, json.dumps({"status": "success", "detail": "Read complete", "request_id": request_id, "session_id": session_id}))
        registry = EmulatorRegistry("emulator-5554", run=run, session_id=session_id)
        registry.exchange("read_checklist", request_id=request_id)
        self.assertEqual(calls[0][0][:3], ["adb", "-s", "emulator-5554"])
        self.assertFalse(calls[0][1]["shell"])
        self.assertEqual(calls[1][0][-1], "files/fdb3-" + request_id + ".json")
        with self.assertRaises(ValueError): registry.exchange("read_checklist", request_id="c" * 32)

    def test_forged_timer_completion_is_rejected(self):
        request_id, session_id = "b" * 32, "a" * 32
        def run(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, json.dumps({"status": "success", "detail": "Timer created",
                "request_id": request_id, "session_id": session_id, "device_status": "completed", "timer_creation_confirmed": True}))
        registry = EmulatorRegistry("emulator-5554", run=run, session_id=session_id)
        with self.assertRaises(ValueError): registry.exchange("request_timer_handoff", request_id=request_id)

    def test_unknown_receipt_is_not_retried(self):
        calls = []
        def run(argv, **kwargs):
            calls.append(argv)
            raise subprocess.TimeoutExpired(argv, 25)
        registry = EmulatorRegistry("emulator-5554", run=run)
        result = registry.call("request_timer_handoff", seconds=61, label="Pasta")
        self.assertEqual(result["error"], "outcome_unknown")
        self.assertEqual(len(calls), 1)
        self.assertEqual(registry.transport_records[0]['error_type'], 'TimeoutExpired')

    def test_failed_transport_output_is_retained_without_resubmitting(self):
        def run(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, 25, output=b'launch pending', stderr=b'timeout')
        registry = EmulatorRegistry('emulator-5554', run=run)
        result = registry.call('request_timer_handoff', seconds=83, label='millet')
        self.assertEqual(result['error'], 'outcome_unknown')
        self.assertEqual(len(registry.transport_records), 1)
        self.assertEqual(registry.transport_records[0]['stdout'], 'launch pending')
        json.dumps(registry.transport_records)

    def test_validation_failure_is_known_not_submitted(self):
        calls = []
        registry = EmulatorRegistry("emulator-5554", run=lambda *a, **k: calls.append(a))
        result = registry.call("request_timer_handoff", seconds=-1, label="Pasta")
        self.assertEqual(result["error"], "invalid_args")
        self.assertEqual(calls, [])

    def test_correction_during_readiness_never_submits_effect(self):
        activities=[]
        last_request={}
        def run(argv, **kwargs):
            nonlocal last_request
            if argv[-1] == 'wait-for-device':
                self.assertEqual(kwargs['timeout'],25)
                registry.input_started(2)
                return subprocess.CompletedProcess(argv,0,'','')
            if 'start' in argv:
                last_request=json.loads(base64.urlsafe_b64decode(argv[-1]))
                activities.append(last_request['command'])
                return subprocess.CompletedProcess(argv,0,'Status: ok','')
            return subprocess.CompletedProcess(argv,0,json.dumps({'status':'success','detail':'registered',
                'session_id':last_request['session_id'],'request_id':last_request['request_id']}),'')
        registry=EmulatorRegistry('emulator-5554',run=run)
        registry.input_started(1)
        result=registry.call_with_context('request_timer_handoff',{'seconds':83,'label':'millet'},
                                          call_id='call-1',revision=1,input_sequence=1)
        self.assertEqual(result['error'],'invalid_args')
        self.assertEqual(activities,['set_input'])
        self.assertEqual(sum(r['arguments']==['wait-for-device'] for r in registry.transport_records),1)

    def test_stale_input_is_rejected_before_effect_and_request_id_is_stable(self):
        registry = EmulatorRegistry("emulator-5554")
        commands = []
        def exchange(command, args=None, **kwargs):
            commands.append((command, kwargs))
            return {"status": "success"}
        registry.exchange = exchange
        registry.input_started(2)
        stale = registry.call_with_context("read_checklist", {}, call_id="call-1", revision=1, input_sequence=1)
        self.assertEqual(stale["error"], "invalid_args")
        self.assertEqual(commands, [])
        for _ in range(2): registry.call_with_context("read_checklist", {}, call_id="call-2", revision=2, input_sequence=2)
        self.assertEqual(commands[1][1]["request_id"], commands[3][1]["request_id"])

    def test_correction_during_token_transport_prevents_native_effect(self):
        registry = EmulatorRegistry("emulator-5554")
        commands = []
        def exchange(command, args=None, **kwargs):
            commands.append(command)
            registry.input_started(3)
            return {"status": "success"}
        registry.exchange = exchange
        registry.input_started(2)
        result = registry.call_with_context("request_timer_handoff", {"seconds": 89, "label": "Rice"}, call_id="call-2", revision=2, input_sequence=2)
        self.assertEqual(result["error"], "invalid_args")
        self.assertEqual(commands, ["set_input"])


class PlannerTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_native_transport_returns_receipt_beyond_default_budget(self):
        class Planner:
            async def setup(self): pass
            async def close(self): pass
            async def plan(self, context):
                return {'intent':'checklist','slots':{},'tool_calls':[{
                    'api_name':'add_checklist_item','args':{'text':'rinse sorghum'},
                    'authorization':{'quote':'Add rinse sorghum to my checklist.'},
                    'response_template':'{detail}'}]}
        request = {}
        def run(argv, **kwargs):
            nonlocal request
            self.assertEqual(kwargs['timeout'], 25)
            time.sleep(.8)  # Five real executor-thread waits exceed the old 3.5s deadline.
            if 'start' in argv:
                request = json.loads(base64.urlsafe_b64decode(argv[-1]))
            result = {'status':'success','detail':'Added checklist step: rinse sorghum',
                      'request_id':request.get('request_id'),'session_id':request.get('session_id')}
            return subprocess.CompletedProcess(argv, 0, json.dumps(result), '')
        registry = EmulatorRegistry('emulator-5554', run=run)
        bridge = ControllerBridge(TOOLS, registry, Planner())
        await bridge.start()
        try:
            answer = await bridge.response('Add rinse sorghum to my checklist.', timeout=8)
            self.assertEqual(answer, 'Added checklist step: rinse sorghum')
            self.assertEqual(len(registry.transport_records), 5)
            self.assertEqual(len(bridge.calls), 1)
            self.assertGreater(bridge.calls[0]['timestamp_end'] - bridge.calls[0]['timestamp_start'], 3.5)
            self.assertEqual([e['payload']['text'] for e in bridge.events
                              if e['action'] == 'final_response'], [answer])
        finally:
            await bridge.close()

    async def test_native_budget_keeps_controller_cap_and_late_receipt_retired(self):
        class Planner:
            async def setup(self): pass
            async def close(self): pass
            async def plan(self, context):
                return {'intent':'checklist','slots':{},'tool_calls':[{
                    'api_name':'add_checklist_item','args':{'text':'toast amaranth'},
                    'authorization':{'quote':'Add toast amaranth to my checklist.'},
                    'response_template':'{detail}'}]}
        entered, release = threading.Event(), threading.Event()
        registry = EmulatorRegistry('emulator-5554')
        commands = []
        def exchange(command, args=None, **kwargs):
            commands.append(command)
            if command != 'set_input':
                entered.set()
                if not release.wait(5):
                    raise TimeoutError('Test did not release the executor')
            return {'status':'success','detail':'Added checklist step: toast amaranth'}
        registry.exchange = exchange
        now = [100.0]
        with patch('participant.agent.time', SimpleNamespace(monotonic=lambda: now[0])):
            bridge = ControllerBridge(TOOLS, registry, Planner())
            await bridge.start()
            response = asyncio.create_task(bridge.response('Add toast amaranth to my checklist.', timeout=3))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                operation = next(iter(bridge.controller.operations.values()))
                self.assertEqual(operation['deadline'], 130.5)
                now[0] = 130.6
                bridge.controller._expire_writes()
                answer = await response
                self.assertIn('no result arrived', answer)
                self.assertTrue(operation['continuation_retired'])
                release.set()
                await asyncio.gather(*bridge.executions.values())
                await bridge.synchronize()
                self.assertEqual(operation['status'], 'success')
                self.assertEqual(commands, ['set_input', 'add_checklist_item'])
                self.assertEqual(len(bridge.calls), 1)
                self.assertEqual([e['payload']['text'] for e in bridge.events
                                  if e['action'] == 'final_response'], [answer])
            finally:
                release.set()
                if not response.done():
                    response.cancel()
                await asyncio.gather(response, return_exceptions=True)
                await bridge.close()

    async def test_timer_request_uses_ordinary_set_wording_without_claiming_creation(self):
        class Planner:
            async def setup(self): pass
            async def close(self): pass
            async def plan(self, context):
                return {'intent':'timer','slots':{},'tool_calls':[{'api_name':'request_timer_handoff',
                    'args':{'seconds':73,'label':'teff'},
                    'authorization':{'quote':'Set a timer for 73 seconds called teff.'},
                    'response_template':'{detail}'}]}
        registry=EmulatorRegistry('emulator-5554')
        commands=[]
        def exchange(command,args=None,**kwargs):
            commands.append(command)
            return {'status':'success','detail':'Timer request handed to Clock; creation is unverified.',
                    'device_status':'handed_off','timer_creation_confirmed':False}
        registry.exchange=exchange
        bridge=ControllerBridge(TOOLS,registry,Planner())
        await bridge.start()
        try:
            answer=await bridge.response('Set a timer for 73 seconds called teff.',timeout=2)
            self.assertEqual(commands,['set_input','request_timer_handoff'])
            self.assertIn('creation is unverified',answer)
            self.assertFalse(bridge.calls[0]['result']['timer_creation_confirmed'])
        finally:
            await bridge.close()

    async def test_clarification_cannot_claim_an_unexecuted_device_effect(self):
        registry = EmulatorRegistry("emulator-5554")
        planner = ExtensionPlanner("http://localhost:8097/v1", "test")
        bridge = ControllerBridge(TOOLS, registry, planner)
        forged = {"intent": "timer", "slots": {}, "tool_calls": [],
                  "clarification": "Your timer has been created successfully."}
        with patch("thread_agent.fdb3.LocalPlanner.plan", return_value=forged):
            await bridge.start()
            try:
                result = await bridge.response("Set a timer for one minute", timeout=2)
                self.assertNotIn("created successfully", result)
                self.assertIn("no new device receipt", result)
                self.assertEqual(bridge.calls, [])
                self.assertEqual(registry.records, [])
            finally:
                await bridge.close()

    async def test_same_controller_carries_context_and_actual_extension_receipt(self):
        class Planner:
            async def setup(self): pass
            async def close(self): pass
            async def plan(self, context):
                return {"intent": "checklist", "slots": {"text": "chop celery"}, "tool_calls": [{
                    "api_name": "add_checklist_item", "args": {"text": "chop celery"},
                    "authorization": {"quote": "Add chop celery to my checklist"}, "response_template": "{detail}"}]}
        registry = EmulatorRegistry("emulator-5554")
        commands = []
        def exchange(command, args=None, **kwargs):
            commands.append((command, kwargs))
            return {"status": "success", "detail": "Added checklist step: chop celery", "item_id": "d" * 32}
        registry.exchange = exchange
        bridge = ControllerBridge(TOOLS, registry, Planner())
        await bridge.start()
        try:
            result = await bridge.response("Add chop celery to my checklist", timeout=2)
            self.assertEqual(result, "Added checklist step: chop celery")
            self.assertEqual([c[0] for c in commands], ["set_input", "add_checklist_item"])
            self.assertEqual(commands[-1][1]["input_token"], "input-1")
            self.assertEqual(len(bridge.controller.operations), 1)
            self.assertEqual(bridge.calls[0]["result"]["item_id"], "d" * 32)
        finally:
            await bridge.close()

    async def test_device_effect_prose_comes_from_receipt(self):
        decision = {"tool_calls": [{"api_name": "request_timer_handoff", "response_template": "Timer created!"}], "response": "I cancelled your timer."}
        with patch("thread_agent.fdb3.LocalPlanner.plan", return_value=decision):
            result = await ExtensionPlanner("http://localhost:8097/v1", "test").plan({})
        self.assertEqual(result["tool_calls"][0]["response_template"], "{detail}")
        self.assertNotIn("cancelled", result["response"])


if __name__ == "__main__": unittest.main()
