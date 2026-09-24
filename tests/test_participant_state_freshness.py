"""Offline checks for current public state versus retained planning memory."""
import asyncio
from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from participant.agent import ParticipantAgent
from participant.planner import Planner, PlannerError, _simple_flight_discovery
from tests.test_participant_controller import ScriptedPlanner, TOOLS, lookup
from tests.test_participant_flight_booking import TOOLS as FLIGHT_TOOLS


OLD = {'intent': 'find_journey', 'slots': {'city': 'Oslo', 'day': 'Friday'}}
EMPTY = {'intent': '', 'slots': {}}


def drain(agent):
    events = []
    while not agent.out_queue.empty():
        events.append(agent.out_queue.get_nowait())
    return events


def handle(agent, kind='user_speech_chunk', **payload):
    with patch.object(agent, '_start_plan'):
        agent._handle({'event_type': kind, 'payload': payload})


def old_agent(planner=None, *, pending=False):
    agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue(), planner=planner)
    handle(agent, 'tool_manifest', tools=deepcopy(TOOLS))
    handle(agent, text='Find journeys to Oslo on Friday.', end_of_turn=True)
    agent._apply(lookup() if pending else {**deepcopy(OLD), 'response': 'Current details.'})
    drain(agent)
    return agent


def active(snapshot):
    return {key: snapshot[key] for key in ('intent', 'slots')}


class SnapshotFreshnessTests(unittest.TestCase):
    def assert_unresolved(self, agent, events=()):
        self.assertEqual(active(agent.snapshot()), EMPTY)
        for event in events:
            self.assertEqual(active(event['state_snapshot']), EMPTY)
            self.assertEqual(event['state_snapshot']['revision'], agent.revision)

    def test_new_input_hides_old_fields_before_cancel_and_filler(self):
        for kind, payload in [
            ('user_speech_chunk', {'text': 'Use another city.', 'end_of_turn': True}),
            ('user_audio_chunk', {'audio_ref': 'new.mp3', 'end_of_turn': True}),
            ('interruption', {'text': 'Cancel that request.'}),
            ('interruption', {}),
        ]:
            with self.subTest(kind=kind, payload=payload):
                agent = old_agent(pending=True)
                handle(agent, kind, **payload)
                events = drain(agent)
                self.assertEqual([event['action'] for event in events], ['cancel_tool', 'filler_speech'])
                self.assert_unresolved(agent, events)
                self.assertEqual(agent._context()['state'], OLD)
                self.assertEqual(agent.snapshot()['actions'], [])
                self.assertEqual(next(iter(agent.operations.values()))['status'], 'cancel_requested')

    def test_fragmented_speech_and_audio_stay_unresolved_until_complete_acceptance(self):
        for kind, part in [('user_speech_chunk', {'text': 'Find another '}),
                           ('user_audio_chunk', {'audio_ref': 'part.mp3'})]:
            with self.subTest(kind=kind):
                agent = old_agent()
                handle(agent, kind, **part, end_of_turn=False)
                revision, start = agent.revision, agent._request_start
                self.assertTrue(agent._turn_open)
                self.assert_unresolved(agent, drain(agent))
                handle(agent, kind, **part, end_of_turn=True)
                self.assertEqual((agent.revision, agent._request_start), (revision, start))
                self.assertFalse(agent._turn_open)
                self.assert_unresolved(agent, drain(agent))
                agent._apply({'intent': 'find_journey', 'slots': {'city': 'Rome'}, 'response': 'New details.'})
                self.assertEqual(active(agent.snapshot()), {'intent': 'find_journey', 'slots': {'city': 'Rome'}})

    def test_interruption_during_fragment_opens_a_distinct_unresolved_request(self):
        agent = old_agent()
        handle(agent, text='Part of a request ', end_of_turn=False)
        revision, start = agent.revision, agent._request_start
        handle(agent, 'interruption', text='Forget that.')
        self.assertEqual(agent.revision, revision + 1)
        self.assertGreater(agent._request_start, start)
        self.assert_unresolved(agent, drain(agent))
        self.assertEqual(agent._context()['state'], OLD)

    def test_clarification_and_partial_or_invalid_pairs_do_not_revalidate_retained_fields(self):
        for partial in [{}, {'intent': 'new'}, {'slots': {'city': 'Rome'}},
                        {'intent': None, 'slots': {}}, {'intent': 7, 'slots': {}},
                        {'intent': 'new', 'slots': []}, {'intent': 'new', 'slots': None}]:
            with self.subTest(partial=partial):
                agent = old_agent()
                handle(agent, text='Use another city.', end_of_turn=True)
                drain(agent)
                agent._apply({**partial, 'clarification': 'Which city?'})
                events = drain(agent)
                self.assertEqual([event['action'] for event in events], ['clarification_request'])
                self.assert_unresolved(agent, events)
                self.assertTrue(agent._awaiting_clarification)
                # A late complete proposal cannot bypass the existing question latch.
                agent._apply({**deepcopy(OLD), 'response': 'Obsolete.'})
                self.assert_unresolved(agent, drain(agent))

    def test_separate_partial_decisions_do_not_collectively_accept_a_current_pair(self):
        agent = old_agent()
        handle(agent, text='Use another city.', end_of_turn=True)
        agent._apply({'intent': 'new_request', 'response': 'First update.'})
        agent._apply({'slots': {'city': 'Rome'}, 'response': 'Second update.'})
        self.assertEqual(agent._context()['state'], {'intent': 'new_request', 'slots': {'city': 'Rome'}})
        self.assert_unresolved(agent, drain(agent))

    def test_complete_acceptance_publishes_clean_current_values_on_dispatch(self):
        agent = old_agent()
        handle(agent, text='Find journeys to Rome.', end_of_turn=True)
        drain(agent)
        slots = {'city': 'Rome', 'budget': 0, 'accessible': False, 'tags': [], 'note': '', 'old': None}
        agent._apply({'intent': 'find_journey', 'slots': slots, 'tool_calls': [
            {'api_name': 'journeys', 'args': {'city': 'Rome'}}]})
        expected = {'intent': 'find_journey', 'slots': {k: v for k, v in slots.items() if v is not None}}
        events = drain(agent)
        self.assertEqual([event['action'] for event in events], ['tool_call'])
        self.assertEqual(active(events[0]['state_snapshot']), expected)
        self.assertEqual(active(agent.snapshot()), expected)
        agent._apply({'intent': '', 'slots': {}, 'response': 'No active request.'})
        self.assertEqual(agent._context()['state'], EMPTY)
        self.assertEqual(active(agent.snapshot()), EMPTY)

    def test_current_complete_clarification_can_publish_known_current_details(self):
        agent = old_agent()
        handle(agent, text='Find journeys to Rome.', end_of_turn=True)
        drain(agent)
        current = {'intent': 'find_journey', 'slots': {'city': 'Rome'}}
        agent._apply({**current, 'clarification': 'Which day?'})
        self.assertEqual(active(drain(agent)[0]['state_snapshot']), current)
        self.assertEqual(agent._context()['state'], current)

    def test_same_request_partial_updates_keep_existing_snapshot_semantics(self):
        agent = old_agent()
        agent._apply({'slots': {'city': 'Rome'}, 'response': 'Updated city.'})
        self.assertEqual(active(agent.snapshot()), {'intent': OLD['intent'], 'slots': {'city': 'Rome'}})
        agent._apply({'intent': 'inspect_routes', 'response': 'Updated goal.'})
        self.assertEqual(active(agent.snapshot()), {'intent': 'inspect_routes', 'slots': {'city': 'Rome'}})

    def test_frame_and_manifest_revisions_preserve_current_or_unresolved_status(self):
        for unresolved in (False, True):
            for kind in ('video_frame', 'tool_manifest'):
                with self.subTest(unresolved=unresolved, kind=kind):
                    agent = old_agent(pending=True)
                    if unresolved:
                        handle(agent, text='Find another city.', end_of_turn=True)
                        agent._apply({'tool_calls': [{'api_name': 'journeys', 'args': {'city': 'Rome'}}]})
                    drain(agent)
                    retained, revision, start = deepcopy(agent.state), agent.revision, agent._request_start
                    payload = ({'frame_ref': 'frame.png'} if kind == 'video_frame' else
                               {'tools': {**TOOLS, 'extra': {'kind': 'read_only', 'args': {}}}})
                    handle(agent, kind, **payload)
                    self.assertEqual(agent.revision, revision + 1)
                    self.assertEqual(agent._request_start, start)
                    self.assertEqual(agent._context()['state'], retained)
                    expected = EMPTY if unresolved else retained
                    self.assertEqual(active(agent.snapshot()), expected)
                    self.assertEqual(active(drain(agent)[0]['state_snapshot']), expected)

    def test_retained_constraints_still_block_narrow_local_discovery(self):
        agent = old_agent()
        agent.tools = deepcopy(FLIGHT_TOOLS)
        agent._apply({'intent': 'book_flight', 'slots': {'destination': 'Porto', 'budget': 200},
                      'response': 'Retained constraints.'})
        drain(agent)
        handle(agent, text='Book a flight to Porto.', end_of_turn=True)
        context = agent._context()
        self.assertEqual(context['state']['slots']['budget'], 200)
        self.assertIsNone(_simple_flight_discovery(context))
        self.assert_unresolved(agent, drain(agent))
        context['state']['slots'].clear()
        public = agent.snapshot()
        public['slots']['destination'] = 'Invented'
        self.assertEqual(agent.state['slots'], {'destination': 'Porto', 'budget': 200})
        self.assertEqual(set(agent.snapshot()), {'intent', 'slots', 'revision', 'actions'})

    def test_late_read_records_outcome_without_restoring_state_or_continuing(self):
        agent = old_agent(pending=True)
        op = next(iter(agent.operations.values()))
        handle(agent, 'interruption', text='Cancel that request.')
        drain(agent)
        agent._apply({'clarification': 'What next?'})
        drain(agent)
        agent._result({'call_id': op['call_id'], 'api_name': op['api_name'], 'status': 'success',
                       'result': {'status': 'success', 'journey_id': 'OLD-RESULT'}})
        self.assertEqual(op['status'], 'success')
        self.assertEqual(drain(agent), [])
        self.assertEqual(agent._context()['state'], OLD)
        self.assert_unresolved(agent)

    def test_late_writes_preserve_ledger_without_speech_or_reviving_old_fields(self):
        for outcome, result in [('success', {'note_id': 'LATE-RECEIPT'}),
                                ('error', {'error': 'not_found'}), ('unknown', {'error': 'timeout'})]:
            with self.subTest(outcome=outcome):
                agent = old_agent()
                tool = {'kind': 'state_modifying', 'description': 'Create a note.',
                        'args': {'text': {'type': 'string', 'required': True}}}
                handle(agent, 'tool_manifest', tools={'create_note': tool})
                handle(agent, text='Create a note saying hello.', end_of_turn=True)
                step = {'api_name': 'create_note', 'args': {'text': 'hello'},
                        'authorization': {'quote': 'Create a note'}, 'response_template': 'OBSOLETE {note_id}'}
                agent._apply({'intent': 'create_note', 'slots': {'text': 'hello'}, 'tool_calls': [step]})
                self.assertEqual(len(agent.operations), 1)
                op = next(iter(agent.operations.values()))
                retained, grants = deepcopy(agent.state), deepcopy(agent._consumed_grants)
                drain(agent)
                handle(agent, 'interruption', text='Cancel that request.')
                cancellation = drain(agent)
                self.assert_unresolved(agent, cancellation)
                self.assertEqual(agent.snapshot()['actions'][0]['status'], 'cancel_requested')
                agent._apply({'clarification': 'What next?'})
                drain(agent)
                payload = {'call_id': op['call_id'], 'api_name': op['api_name'],
                           'status': 'success' if outcome == 'success' else 'error', 'result': result}
                agent._result(payload)
                events = drain(agent)
                self.assert_unresolved(agent, events)
                self.assertEqual(agent.snapshot()['actions'][0]['status'], outcome)
                self.assertEqual(agent.snapshot()['actions'][0]['result'], result)
                self.assertEqual(agent._context()['state'], retained)
                self.assertEqual(agent._consumed_grants, grants)
                self.assertTrue(agent._awaiting_clarification)
                self.assertEqual(events, [])
                agent._result(payload)
                self.assertEqual(drain(agent), [])


class AsyncFreshnessTests(unittest.IsolatedAsyncioTestCase):
    async def test_planning_failures_become_unresolved_clarification(self):
        for failure in (TimeoutError(), PlannerError('Media verification failed.'), ['invalid output']):
            with self.subTest(failure=failure):
                def interpret(_):
                    if isinstance(failure, Exception):
                        raise failure
                    return failure
                agent = old_agent(ScriptedPlanner(interpret))
                self.addAsyncCleanup(agent.close)
                handle(agent, text='Use another city.', end_of_turn=True)
                drain(agent)
                revision, decision = await agent._plan(agent._context(), agent.revision)
                self.assertEqual(revision, agent.revision)
                self.assertEqual(set(decision), {'clarification'})
                agent._apply(decision)
                self.assertEqual(active(drain(agent)[0]['state_snapshot']), EMPTY)
                self.assertEqual(agent._context()['state'], OLD)

    async def test_queued_correction_wins_over_already_ready_complete_plan(self):
        planner = ScriptedPlanner(lambda _: {'clarification': 'Please clarify the new request.'})
        agent = old_agent(planner)
        ready = asyncio.get_running_loop().create_future()
        ready.set_result((agent.revision, lookup('Obsolete')))
        agent._plan_task = ready
        agent.in_queue.put_nowait({'event_type': 'interruption', 'payload': {'text': 'Cancel that request.'}})
        task = asyncio.create_task(agent.run())
        try:
            events = []
            while not events or events[-1]['action'] != 'clarification_request':
                events.append(await asyncio.wait_for(agent.out_queue.get(), .8))
            self.assertTrue(all(active(event['state_snapshot']) == EMPTY for event in events))
            self.assertEqual(agent.operations, {})
            self.assertEqual(agent._context()['state'], OLD)
            self.assertEqual(planner.contexts[0]['state'], OLD)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_cancel_suppressing_planner_cannot_restore_old_state(self):
        started, cancelled = asyncio.Event(), asyncio.Event()
        async def interpret(context):
            if context['revision'] == 1:
                started.set()
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    cancelled.set()
                    return lookup('Obsolete')
            return {'clarification': 'Which new city?'}
        agent = old_agent(ScriptedPlanner(interpret))
        task = asyncio.create_task(agent.run())
        try:
            agent._start_plan()
            await asyncio.wait_for(started.wait(), .8)
            agent.in_queue.put_nowait({'event_type': 'interruption', 'payload': {'text': 'Cancel that request.'}})
            while True:
                event = await asyncio.wait_for(agent.out_queue.get(), .8)
                self.assertEqual(active(event['state_snapshot']), EMPTY)
                if event['action'] == 'clarification_request':
                    break
            await asyncio.wait_for(cancelled.wait(), .8)
            self.assertEqual(agent.operations, {})
            self.assertEqual(agent._context()['state'], OLD)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


class CompletedReadFreshnessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.source_call_id = None

        def plan(context):
            if context['revision'] == 1:
                return {'intent': 'find_journey', 'slots': {'city': 'Oslo', 'day': 'Friday'},
                        'tool_calls': [{'api_name': 'resolve_city', 'args': {}, 'after_result': {
                            'api_name': 'journeys', 'args': {'day': 'Friday'},
                            'bindings': {'city': 'city'},
                            'response_template': 'Journey {journeys.0.ref}.'}}]}
            return {'intent': 'find_journey',
                    'slots': {'city': 'Oslo', 'day': 'Friday', 'sort': 'price'},
                    'tool_calls': [{'api_name': 'journeys', 'args': {'city': 'Oslo', 'day': 'Friday'},
                                    'result_bindings': {'city': {'call_id': self.source_call_id, 'path': 'city'}},
                                    'response_template': 'Journey {journeys.0.ref}, sorted by price.'}]}

        self.planner = ScriptedPlanner(plan)
        self.agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue(), planner=self.planner)
        self.task = asyncio.create_task(self.agent.run())
        self.addAsyncCleanup(self.stop)
        await self.event('tool_manifest', {'tools': {
            'resolve_city': {'kind': 'read_only', 'description': 'Resolve a city.', 'args': {}},
            'journeys': deepcopy(TOOLS['journeys'])}})

    async def stop(self):
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)

    async def event(self, kind, payload=None):
        await self.agent.in_queue.put({'event_type': kind, 'payload': payload or {}})

    async def output(self, action):
        async def find():
            while True:
                event = await self.agent.out_queue.get()
                if event['action'] == action:
                    return event
        return await asyncio.wait_for(find(), 0.8)

    async def result(self, call, result):
        await self.event('tool_result', {**call['payload'], 'status': 'success',
                                          'result': {'status': 'success', **result}})

    async def test_correction_reuses_read_when_args_and_source_still_match_slots(self):
        await self.event('user_speech_chunk', {'text': 'Find journeys to Oslo on Friday.', 'end_of_turn': True})
        source = await self.output('tool_call')
        self.source_call_id = source['payload']['call_id']
        await self.result(source, {'city': 'Oslo'})
        read = await self.output('tool_call')
        self.assertEqual(read['payload']['api_name'], 'journeys')
        await self.result(read, {'journeys': [{'ref': 'R-OSLO'}]})
        await self.output('final_response')

        await self.event('user_speech_chunk', {'text': 'Keep Oslo and sort by price.', 'end_of_turn': True})
        final = await self.output('final_response')

        self.assertIn('R-OSLO', final['payload']['text'])
        self.assertIn('sorted by price', final['payload']['text'])
        self.assertEqual(len(self.agent.operations), 2)
        self.assertEqual(self.agent.state['slots'], {'city': 'Oslo', 'day': 'Friday', 'sort': 'price'})


class AudioFallbackFreshnessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        clip = Path(__file__).parent / 'fixtures/mp3/tone-cbr.mp3'
        (self.root / 'current.mp3').write_bytes(clip.read_bytes())
        environment = patch.dict(os.environ, {'SECRET_GEMINI_API_KEY': 'offline-only',
            'PARTICIPANT_MEDIA_ROOT': str(self.root), 'PARTICIPANT_PREWARM': '0',
            'PARTICIPANT_IMAGE_EMBEDDING': '0'}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    async def planner(self, mode='independent'):
        async def reject_network(request):
            self.fail('Unexpected HTTP request; this suite injects decisions.')
        planner = Planner(transport=httpx.MockTransport(reject_network))
        await planner.setup()
        planner.audio_mode = mode
        self.addAsyncCleanup(planner.close)
        return planner

    def agent(self, planner):
        agent = old_agent(planner)
        handle(agent, 'user_audio_chunk', audio_ref='current.mp3', end_of_turn=True)
        drain(agent)
        return agent

    def assert_synthetic(self, agent, decision):
        self.assertNotIn('intent', decision)
        self.assertNotIn('slots', decision)
        self.assertEqual(decision['tool_calls'], [])
        self.assertIsNone(decision['response'])
        self.assertTrue(decision['clarification'])
        agent._apply(decision)
        events = drain(agent)
        self.assertEqual([event['action'] for event in events], ['clarification_request'])
        self.assertEqual(active(events[0]['state_snapshot']), EMPTY)
        self.assertEqual(agent._context()['state'], OLD)
        self.assertEqual(agent.operations, {})

    async def test_all_generate_audio_fallbacks_preserve_memory_without_accepting_it(self):
        cases = [('stopped', 'acoustic_unverified'), ('single_uncertain', 'main_audio_uncertain'),
                 ('acoustic_uncertain', 'acoustic_uncertain'), ('main_uncertain', 'main_audio_uncertain'),
                 ('conflict', None), ('source_changed', 'audio_source_changed'),
                 ('acoustic_error', 'acoustic_unverified')]
        for case, status in cases:
            with self.subTest(case=case):
                mode = 'single_call_reads' if case in {'single_uncertain', 'source_changed'} else 'independent'
                planner = await self.planner(mode)
                agent = self.agent(planner)
                index = len(agent.messages) - 1
                row = {'message_index': index, 'type': 'audio', 'transcript': 'Find journeys to Rome.',
                       'uncertain': case in {'single_uncertain', 'main_uncertain'}}
                proposal = {**lookup('Rome'), 'observations': [row], 'response': None, 'clarification': None}
                if case == 'single_uncertain':
                    proposal['tool_calls'][0]['after_result'] = {'api_name': 'journeys', 'args': {'city': 'Rome'}}
                if case == 'stopped':
                    planner._stop_audio_jobs()
                async def decide(*_):
                    if case in {'acoustic_uncertain', 'acoustic_error'}:
                        await asyncio.Future()
                    if case == 'source_changed':
                        planner._audio_turn += 1
                    return deepcopy(proposal)
                async def hear(*_):
                    if case == 'main_uncertain':
                        await asyncio.Future()
                    if case == 'acoustic_error':
                        raise PlannerError('Injected verification failure.')
                    return [{**row, 'transcript': 'Different material words.' if case == 'conflict' else row['transcript'],
                             'uncertain': case == 'acoustic_uncertain'}]
                with patch.object(planner, '_decide', side_effect=decide), patch.object(planner, '_current_audio', side_effect=hear):
                    decision = await planner.plan(agent._context())
                if status is not None:
                    self.assertEqual(planner.evidence[-1]['status'], status)
                else:
                    self.assertEqual(planner.evidence[-1]['audio_transcript_conflicts'], [index])
                self.assert_synthetic(agent, decision)
                await planner.close()

    async def test_outer_audio_source_epoch_guard_cannot_revalidate_retained_state(self):
        planner = await self.planner('single_call_reads')
        agent = self.agent(planner)
        async def generate(*_):
            planner._audio_turn += 1
            return {**lookup('Rome'), 'observations': []}
        with patch.object(planner, '_generate', side_effect=generate):
            decision = await planner.plan(agent._context())
        self.assertEqual(planner.evidence[-1]['status'], 'audio_source_changed')
        self.assert_synthetic(agent, decision)

    async def test_media_load_failure_stays_unresolved_through_controller_fallback(self):
        planner = await self.planner()
        agent = self.agent(planner)
        (self.root / 'current.mp3').unlink()
        _, decision = await agent._plan(agent._context(), agent.revision)
        self.assertEqual(planner.evidence[-1]['status'], 'media_error')
        agent._apply(decision)
        self.assertEqual(active(drain(agent)[0]['state_snapshot']), EMPTY)
        self.assertEqual(agent._context()['state'], OLD)

    async def test_complete_audio_decision_restores_only_after_existing_source_gate(self):
        for verified in (False, True):
            with self.subTest(verified=verified):
                planner = await self.planner('single_call_reads')
                agent = self.agent(planner)
                index = len(agent.messages) - 1
                row = {'message_index': index, 'type': 'audio', 'transcript': 'Find journeys to Rome.', 'uncertain': False}
                if verified:
                    planner._audio_cache[(index, agent.revision, 'audio/mpeg', 'source-digest')] = deepcopy(row)
                agent._apply({**lookup('Rome'), 'observations': [row]})
                events = drain(agent)
                self.assertEqual([event['action'] for event in events], ['tool_call' if verified else 'clarification_request'])
                self.assertEqual(active(events[0]['state_snapshot']), active(lookup('Rome')) if verified else EMPTY)
                self.assertEqual(agent._context()['state'], active(lookup('Rome')) if verified else OLD)


if __name__ == '__main__':
    unittest.main()
