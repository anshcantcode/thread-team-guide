"""Regression checks for the provisional evaluation boundary and authority races."""
import asyncio
from copy import deepcopy
import json
import subprocess
import sys
import unittest
from unittest.mock import patch

from thread_agent.adapter import QueueAdapter, parse_event
from thread_agent.clock import VirtualClock
from thread_agent.engine import Session
from thread_agent.fixtures import TRAVEL, DEVICE, lookup
from thread_agent.protocol import InputEvent, Interpretation, Manifest
from thread_agent.live import LiveConversation
from thread_agent.planner import ModelPlanner, ProviderError


def interpretation(intent='revise', domain='', **slots):
    return Interpretation(intent=intent, domain=domain, changes=[
        {'slot': k, 'value': v if isinstance(v, str) else json.dumps(v)} for k, v in slots.items()])


class Planner:
    def __init__(self):
        self.plan = interpretation()

    async def interpret(self, context, event):
        return deepcopy(self.plan)


class Theme5Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.planner = Planner()
        self.session = Session(self.planner, external=True, date='2026-09-14')
        self.session.sandbox.config.update(prepare_delay=.025, timeout=.1)

    async def asyncTearDown(self):
        await self.session.close()

    async def apply(self, plan):
        self.planner.plan = plan
        text = 'Create the selected action.' if plan.intent == 'commit' else 'current input'
        await self.session.accept(InputEvent(id=self.session.new_id('input'), type='text', text=text))
        await asyncio.wait_for(self.session.inputs.join(), 1)

    async def ready(self):
        await self.apply(interpretation(domain='travel', origin='Chennai', destination='Delhi', date='2026-09-15'))
        read = next(iter(self.session.operations.values()))
        self.session.handle_result(read['id'], {'status': 'completed', **lookup('travel', read['arguments'])}, 'read')
        await self.apply(Interpretation(intent='select', selection=self.session.results['items'][0]['id']))

    async def test_changed_selection_revokes_prepared_authority(self):
        await self.ready()
        await self.apply(interpretation('commit'))
        await self.apply(Interpretation(intent='select', selection=self.session.results['items'][1]['id']))
        await asyncio.sleep(.06)
        self.assertFalse(any(e['type'] == 'tool_call' and e['effect'] == 'write' for e in self.session.trace))
        self.assertEqual(next(o['status'] for o in self.session.operations.values() if o['purpose'] == 'create'), 'not_submitted')

    async def test_negative_status_cannot_erase_positive_creation(self):
        await self.ready()
        await self.apply(interpretation('commit'))
        await asyncio.sleep(.04)
        created = next(o for o in self.session.operations.values() if o['purpose'] == 'create')
        self.session.request_reconcile(created, 'status')
        status = next(o for o in self.session.operations.values() if o['purpose'] == 'status')
        self.session.handle_result(created['id'], {'status': 'completed', 'reference': 'REF-1'}, 'success')
        self.session.handle_result(status['id'], {'status': 'not_performed'}, 'old-negative')
        await self.apply(interpretation('commit'))
        await asyncio.sleep(.04)
        self.assertEqual(created['status'], 'completed')
        self.assertEqual(len([e for e in self.session.trace if e['type'] == 'tool_call' and e['effect'] == 'write']), 1)

    async def test_malformed_result_cannot_kill_worker(self):
        await self.ready()
        read = next(iter(self.session.operations))
        self.session.floor_held = True
        for malformed in (None, [], 'completed', 7):
            self.session.handle_result(read, malformed, str(malformed))
        self.session.floor_held = False
        await self.apply(interpretation(destination='Mumbai'))
        self.assertFalse(self.session.worker.done())
        self.assertEqual(self.session.slots['destination'], 'Mumbai')

    async def test_interrupt_holds_floor_after_cancelled_reasoning(self):
        started = asyncio.Event()
        async def slow(context, event):
            started.set()
            await asyncio.sleep(5)
            return interpretation('commit')
        await self.ready()
        self.planner.interpret = slow
        await self.session.accept(InputEvent(id='slow', type='text', text='book this'))
        await started.wait()
        await self.session.accept(InputEvent(id='barge', type='interrupt'))
        await asyncio.wait_for(self.session.inputs.join(), .2)
        self.assertTrue(self.session.floor_held)
        self.assertFalse(any(o['purpose'] == 'create' for o in self.session.operations.values()))

    async def test_fast_correction_preserves_unprocessed_input(self):
        started = asyncio.Event()
        contexts = []
        async def slow(context, event):
            if event.id == 'original':
                started.set()
                await asyncio.sleep(5)
            contexts.append(context)
            return interpretation(domain='travel', origin='Chennai', destination='Mumbai', date='2026-09-15')
        self.planner.interpret = slow
        await self.session.accept(InputEvent(id='original', type='text', text='Chennai to Delhi on September 15'))
        await started.wait()
        await self.session.accept(InputEvent(id='repair', type='text', text='Actually Mumbai'))
        await asyncio.wait_for(self.session.inputs.join(), .2)
        self.assertEqual(contexts[0]['unprocessed_inputs'][0]['text'], 'Chennai to Delhi on September 15')
        self.assertEqual(self.session.slots['destination'], 'Mumbai')

    async def test_transcript_end_marker_and_duplicate_chunk(self):
        self.planner.plan = interpretation('clarify')
        chunk = InputEvent(id='chunk1', type='transcript', utterance_id='u1', end_of_turn=False, text='Find a flight ')
        await self.session.accept(chunk)
        await self.session.accept(chunk)
        await self.session.accept(InputEvent(id='chunk2', type='transcript', utterance_id='u1', end_of_turn=True, text='to Mumbai'))
        await self.session.inputs.join()
        user = [m for m in self.session.transcript if m['role'] == 'user']
        self.assertEqual(user[-1]['text'], 'Find a flight to Mumbai')
        self.assertFalse(self.session.transcript_chunks)

    async def test_unfamiliar_reference_binding_and_output_validation(self):
        raw = TRAVEL.model_dump()
        raw['id'] = 'expedition'
        for t in raw['tools']:
            t['name'] = 'expedition.' + t['purpose']
            if t['purpose'] in ('cancel', 'status'):
                t['parameters'] = {'type': 'object', 'properties': {'ticket_ref': {'type': 'string'}}, 'required': ['ticket_ref'], 'additionalProperties': False}
                t['bindings'] = {'ticket_ref': 'reference'}
        manifest = Manifest.model_validate(raw).check()
        self.session.manifests[manifest.id] = manifest
        await self.apply(interpretation(domain='expedition', origin='Chennai', destination='Delhi', date='2026-09-15'))
        read = next(iter(self.session.operations.values()))
        self.session.handle_result(read['id'], {'status': 'completed', **lookup('travel', read['arguments'])}, 'options')
        await self.apply(Interpretation(intent='commit', selection=self.session.results['items'][0]['id']))
        await asyncio.sleep(.04)
        write = next(o for o in self.session.operations.values() if o['purpose'] == 'create')
        self.session.handle_result(write['id'], {'status': 'completed', 'reference': 'TICKET-42'}, 'booked')
        self.session.request_reconcile(write, 'cancel')
        cancel = next(o for o in self.session.operations.values() if o['purpose'] == 'cancel')
        self.assertEqual(cancel['arguments'], {'ticket_ref': 'TICKET-42'})

    async def test_external_final_includes_manual_guidance_and_locator(self):
        await self.apply(interpretation(domain='device', model='THREAD R1', indicator='network'))
        op = next(iter(self.session.operations.values()))
        self.session.handle_result(op['id'], {'status': 'completed', **lookup('device', op['arguments'])}, 'manual')
        final = next(e for e in reversed(self.session.trace) if e['type'] == 'final')
        self.assertIn('connection', final['text'])
        self.assertEqual(final['state_snapshot']['evidence']['evidence']['page'], 3)

    async def test_evaluation_stores_and_manifests_are_isolated(self):
        a, b = [QueueAdapter(Planner()) for _ in range(2)]
        try:
            self.assertFalse(a.session.manifests)
            a.session.sandbox.notebook.save('same-call', {'title': 'Private', 'body': 'session A'})
            self.assertEqual(b.session.sandbox.notebook.status('same-call')['status'], 'not_performed')
            self.assertNotEqual(a.session.sandbox.notebook.path, b.session.sandbox.notebook.path)
            path = a.session.sandbox.notebook.path
            await a.session.close()
            self.assertFalse(path.exists())
        finally:
            await a.session.close()
            await b.session.close()

    async def test_adapter_timeout_and_error_recovery(self):
        a = QueueAdapter(Planner())
        await a.events.put('{"id":"bad","type":"tool_result","data":{"call_id":"x","result":null}}')
        await a.run(wall_timeout=.04)
        kinds = [e['type'] for e in a.session.trace]
        self.assertIn('protocol_error', kinds)
        self.assertIn('scenario_timeout', kinds)
        self.assertTrue(a.session.worker.done())

    async def test_virtual_clock_wakes_in_deadline_order(self):
        clock = VirtualClock()
        observed = []
        async def sleep(delay):
            await clock.sleep(delay)
            observed.append(clock.now())
        tasks = [asyncio.create_task(sleep(n)) for n in (2, 1)]
        await asyncio.sleep(0)
        clock.advance_to(1)
        await asyncio.sleep(0)
        self.assertEqual(observed, [1])
        clock.advance_to(2)
        await asyncio.gather(*tasks)
        self.assertEqual(observed, [1, 2])

    async def test_provider_reception_does_not_wait_for_a_tool(self):
        class Browser:
            def __init__(self): self.events = []
            async def send_json(self, event): self.events.append(event)
        class Upstream:
            def __init__(self): self.messages = asyncio.Queue(); self.sent = []
            def __aiter__(self): return self
            async def __anext__(self):
                value = await self.messages.get()
                if value is None: raise StopAsyncIteration
                return json.dumps(value)
            async def send(self, raw): self.sent.append(json.loads(raw))
        browser, upstream = Browser(), Upstream()
        live = LiveConversation(self.session, browser)
        live.upstream = upstream
        live.input_epoch = 1
        started, release = asyncio.Event(), asyncio.Event()
        async def slow(call):
            started.set(); await release.wait()
            return {'ok': True}
        live.handle_tool = slow
        receiver = asyncio.create_task(live.receive_provider())
        try:
            await upstream.messages.put({'toolCall': {'functionCalls': [{'id': 'slow-phone', 'name': 'phone_flashlight', 'args': {}}]}})
            await asyncio.wait_for(started.wait(), .2)
            await upstream.messages.put({'serverContent': {'interrupted': True}})
            for _ in range(12): await asyncio.sleep(0)
            self.assertTrue(any(e['type'] == 'interrupted' for e in browser.events))
            self.assertFalse(release.is_set())
            await upstream.messages.put({'toolCallCancellation': {'ids': ['slow-phone']}})
            for _ in range(12): await asyncio.sleep(0)
            release.set()
            await asyncio.gather(*list(live.tool_tasks.values()))
            self.assertFalse(upstream.sent, 'A withdrawn provider call must not receive an obsolete response')
        finally:
            release.set()
            receiver.cancel()
            await asyncio.gather(receiver, *list(live.tool_tasks.values()), return_exceptions=True)

    async def test_malformed_text_in_tool_evidence_is_rejected(self):
        await self.ready()
        read = next(iter(self.session.operations))
        self.session.handle_result(read, {'status': 'completed', 'source': 'fixture', 'items': [], 'summary': {}}, 'bad-text')
        await self.apply(interpretation(destination='Mumbai'))
        self.assertFalse(self.session.worker.done())
        self.assertTrue(any(e['type'] == 'protocol_error' for e in self.session.trace))

    async def test_confirmed_effect_survives_cancellation_and_malformed_completion(self):
        await self.ready()
        await self.apply(interpretation('commit'))
        await asyncio.sleep(.04)
        op = next(o for o in self.session.operations.values() if o['purpose'] == 'create')
        self.session.handle_result(op['id'], {'status': 'completed', 'reference': 'REAL-1'}, 'confirmed')
        self.session.request_reconcile(op, 'cancel')
        self.session.handle_result(op['id'], {'status': 'completed', 'reference': ''}, 'malformed')
        self.session.request_reconcile(op, 'status')
        check = next(o for o in self.session.operations.values() if o['purpose'] == 'status')
        self.session.handle_result(check['id'], {'status': 'not_performed'}, 'stale-status')
        await self.apply(interpretation('commit'))
        self.assertEqual(op['confirmed_reference'], 'REAL-1')
        self.assertEqual(op['status'], 'cancel_requested')
        self.assertEqual(sum(o['purpose'] == 'create' for o in self.session.operations.values()), 1)

    async def test_other_complete_utterance_cannot_release_unfinished_chunk(self):
        await self.ready()
        await self.apply(interpretation('commit'))
        await self.session.accept(InputEvent(id='u1a', type='transcript', utterance_id='u1', end_of_turn=False, text='Wait, change '))
        await self.session.accept(InputEvent(id='u2', type='transcript', utterance_id='u2', end_of_turn=True, text='What is the status?'))
        await self.session.inputs.join()
        await asyncio.sleep(.06)
        self.assertTrue(self.session.floor_held)
        self.assertFalse(any(e['type'] == 'tool_call' and e['effect'] == 'write' for e in self.session.trace))

    async def test_reported_symptom_survives_image_replacement(self):
        self.planner.plan = interpretation(domain='device', model='THREAD R1', indicator='power', symptom='blinking for ten minutes')
        await self.session.accept(InputEvent(id='old-image', type='frame', text='I report blinking for ten minutes', data={'mime': 'image/png', 'base64': 'fixture'}))
        await self.session.inputs.join()
        self.planner.plan = interpretation('clarify', domain='device', model='THREAD R1')
        await self.session.accept(InputEvent(id='new-image', type='frame', data={'mime': 'image/png', 'base64': 'fixture'}))
        await self.session.inputs.join()
        self.assertEqual(self.session.slots['symptom'], 'blinking for ten minutes')
        self.assertNotIn('indicator', self.session.slots)

    async def test_provider_failure_is_audible_after_complete_input(self):
        async def unavailable(context, event): raise ProviderError('Provider unavailable')
        self.planner.interpret = unavailable
        await self.session.accept(InputEvent(id='request', type='text', text='Find a flight'))
        await self.session.inputs.join()
        clarification = next(e for e in self.session.trace if e['type'] == 'clarify')
        self.assertTrue(clarification['speak'])

    async def test_local_asr_subprocess_is_killed_on_cancellation(self):
        real_spawn = asyncio.create_subprocess_exec
        processes = []
        async def slow_worker(*args, **kwargs):
            proc = await real_spawn(sys.executable, '-c', 'import time; time.sleep(20)', **kwargs)
            processes.append(proc)
            return proc
        planner = ModelPlanner()
        try:
            with patch('thread_agent.planner.asyncio.create_subprocess_exec', slow_worker):
                task = asyncio.create_task(planner.transcribe('fixture'))
                while not processes: await asyncio.sleep(.01)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 1)
            self.assertIsNotNone(processes[0].returncode)
        finally:
            await planner.close()


class ProtocolChecks(unittest.TestCase):
    def test_unsupported_boolean_slot_schema_fails_at_manifest_boundary(self):
        manifest = TRAVEL.model_dump()
        manifest['slots']['properties']['origin'] = True
        with self.assertRaises(ValueError):
            parse_event({'id': 'boolean-schema', 'type': 'manifest', 'data': {'manifest': manifest}})

    def test_nonfinite_result_rejected_before_state_mutation(self):
        with self.assertRaises(ValueError):
            parse_event('{"id":"x","type":"tool_result","data":{"call_id":"y","result":{"price":NaN}}}')

    def test_stdio_wall_cap_works_when_peer_keeps_stdin_open(self):
        proc = subprocess.Popen([sys.executable, '-m', 'thread_agent.stdio', '--wall-timeout', '.1'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            proc.wait(timeout=5)
            actions = [json.loads(line) for line in proc.stdout.read().splitlines()]
            self.assertIn('scenario_timeout', [a['type'] for a in actions])
            self.assertEqual(proc.returncode, 0)
        finally:
            if proc.poll() is None: proc.kill(); proc.wait()
            proc.stdin.close(); proc.stdout.close(); proc.stderr.close()


if __name__ == '__main__':
    unittest.main()
