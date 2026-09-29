"""Offline literal-routing and real-loop cancellation checks; no provider calls."""
import asyncio
from copy import deepcopy
import unittest
from unittest.mock import patch

from participant import planner as planning
from participant.agent import ParticipantAgent
from tests.test_participant_discovery_followthrough import ROWS, audio, correction, speech
from tests.test_participant_flight_booking import TOOLS


def input_agent(events=None, tools=None):
    agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
    with patch.object(agent, '_start_plan'):
        agent._handle({'event_type': 'tool_manifest', 'payload': {'tools': deepcopy(tools or TOOLS)}})
        for kind, payload in events or [speech('Book a flight to Porto for Friday.')]:
            agent._handle({'event_type': kind, 'payload': payload})
    while not agent.out_queue.empty():
        agent.out_queue.get_nowait()
    return agent


def update(agent, event):
    with patch.object(agent, '_start_plan'):
        agent._handle({'event_type': event[0], 'payload': event[1]})


class DiscoveryPlanner(planning.Planner):
    """Exercise real plan routing; only unsupported generation is stubbed."""
    def __init__(self):
        super().__init__()
        self.generation_calls = 0

    async def setup(self):
        self.client, self.media, self._key = object(), object(), 'offline-test'

    async def _generate(self, context, record, started):
        self.generation_calls += 1
        return {'clarification': 'Unsupported literal request; normal planning fallback.'}

    async def close(self):
        pass


class TextDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_ordinary_read_metadata_is_compatible_but_consumers_do_not_use_fast_path(self):
        agent=input_agent()
        agent._apply(planning._simple_flight_discovery(agent._context()))
        update(agent,correction('Make it Dakar.'))
        context=agent._context()
        self.assertIsNotNone(planning._simple_flight_discovery(context))
        for extra in ({'execution_admitted':'yes'},{'can_retain_read':1},{'read_dependencies':[]},
                      {'retained_from_call_id':'call-1'},{'awaiting_not_submitted_call_id':'call-1'}):
            malformed=deepcopy(context)
            malformed['actions'][0].update(extra)
            with self.subTest(extra=extra):
                self.assertIsNone(planning._simple_flight_discovery(malformed))

    async def route(self, context, eligible):
        before = deepcopy(context)
        planner = DiscoveryPlanner()
        await planner.setup()
        decision = await planner.plan(context)
        self.assertEqual(context, before)
        self.assertEqual(planner.generation_calls, 0 if eligible else 1)
        if eligible:
            self.assertEqual(planner.evidence[-1]['rule'], 'documented_flight_discovery')
            self.assertEqual(decision['intent'], 'book_flight')
            self.assertEqual(len(decision['tool_calls']), 1)
            self.assertEqual(set(decision['tool_calls'][0]), {'api_name', 'args', 'response_template'})
            self.assertEqual(decision['tool_calls'][0]['api_name'], 'flight_search')
            self.assertEqual(decision['slots'], decision['tool_calls'][0]['args'])
            self.assertEqual(decision['observations'], [])
            self.assertIsNone(decision['clarification'])
        else:
            self.assertIsNone(planning._simple_flight_discovery(context))
        return decision

    async def test_literal_variants_preserve_explicit_fields_without_defaults(self):
        for text, args in [
            ('Please book a flight to Porto.', {'destination': 'Porto'}),
            ('Can you please reserve a flight to Łódź on Monday?', {'destination': 'Łódź', 'date': 'Monday'}),
            ("Book a flight to N'Djamena for tomorrow.", {'destination': "N'Djamena", 'date': 'tomorrow'}),
            ('Book a flight to Dakar on 2027-03-18.', {'destination': 'Dakar', 'date': '2027-03-18'}),
            ('Book a flight to "São Paulo" for today.', {'destination': 'São Paulo', 'date': 'today'}),
            ('Uh, book a flight to Busan today.', None),
        ]:
            with self.subTest(text=text):
                decision = await self.route(input_agent([speech(text)])._context(), args is not None)
                if args is not None:
                    self.assertEqual(decision['slots'], args)

    async def test_fragments_and_both_text_correction_types_use_only_proven_lineage(self):
        for event in (speech, correction):
            events = [speech('Please book a flight to ', False), speech('Lima for Friday.'),
                      event('Actually make that Dakar.'), event('Make it Porto.')]
            agent = input_agent(events)
            source, authority, start = deepcopy(agent.messages), agent._user_texts(), agent._request_start
            decision = await self.route(agent._context(), True)
            self.assertEqual(decision['slots'], {'destination': 'Porto', 'date': 'Friday'})
            self.assertEqual(agent.messages, source)
            self.assertEqual(agent._request_start, start)
            self.assertEqual(agent._user_texts(), authority)
        decision = await self.route(input_agent([speech('Unrelated earlier turn.'), correction('Book a flight to Porto.')])._context(), True)
        self.assertEqual(decision['slots'], {'destination': 'Porto'})

    async def test_meaning_outside_the_closed_grammar_uses_normal_fallback(self):
        for text in [
            'Do not book a flight to Porto.', 'Suppose I book a flight to Porto.', '"Book a flight to Porto."',
            'Book a flight to Porto if refundable.', 'Book a flight to Porto and cancel my hotel.',
            'Book a flight to Porto for Nia.', 'Book a flight to Porto with baggage.',
            'Book a flight to Porto under budget.', 'Book a flight to Porto for next Friday.',
            'Book a flight to Porto for 2027-02-30.', 'Book a flight to home.',
            'Book the cheapest flight to Porto.', 'Book a flight to Porto for Friday. Then book it.',
            'Book a flight to Porto carrying lithium batteries.', 'Book a flight to Porto urgently.',
            'Book a flight to São Paulo.',
        ]:
            with self.subTest(text=text):
                await self.route(input_agent([speech(text)])._context(), False)
        for middle in ('Never mind.', 'What is the weather?', 'Find flights to Dakar.'):
            await self.route(input_agent([speech('Book a flight to Lima.'), speech(middle), correction('Make that Porto.')])._context(), False)

    async def test_only_quoted_multiword_corrections_are_local_and_followthrough_still_uses_actual_result(self):
        for text, eligible in [('Make that "San José".', True), ('Make that San José.', False),
                               ('Make that Porto urgently.', False), ('Make that Porto carrying lithium batteries.', False)]:
            agent = input_agent([speech('Book a flight to Lima for Friday.'), correction(text)])
            decision = await self.route(agent._context(), eligible)
            if eligible:
                self.assertEqual(decision['slots'], {'destination': 'San José', 'date': 'Friday'})
        agent = input_agent([speech('Book a flight to Lima for Friday.'), correction('Make that San José.')])
        actual_args = {'destination': 'San José', 'date': 'Friday'}
        agent._apply({'intent': 'search_flights', 'slots': actual_args, 'tool_calls': [
            {'api_name': 'flight_search', 'args': actual_args, 'response_template': ''}]})
        call = agent.out_queue.get_nowait()['payload']
        agent._result({**call, 'status': 'success', 'result': {'status': 'success', 'flights': ROWS}})
        outputs = []
        while not agent.out_queue.empty():
            outputs.append(agent.out_queue.get_nowait())
        self.assertEqual([o['action'] for o in outputs], ['final_response', 'clarification_request'])
        self.assertIsNone(planning._flight_text_goal(agent._context(), completed_read_args={'destination': 'Dakar'}))

    async def test_raw_source_indices_revisions_closure_and_media_fail_closed(self):
        contexts = []
        for events in ([speech('Book a flight to Po', False), speech('rto for Friday.')],
                       [speech('Book a flight to Lima.', False), correction('Make that Porto.')],
                       [audio(0, True), speech('Book a flight to Porto.')]):
            contexts.append(input_agent(events)._context())
        original = input_agent()._context()
        for key, value in [('message_index', True), ('message_index', 7), ('revision', True),
                           ('revision', 77), ('event_type', {}), ('unverified', True)]:
            ctx = deepcopy(original)
            ctx['messages'][0][key] = value
            contexts.append(ctx)
        for key, value in [('end_of_turn', False), ('end_of_turn', 1), ('text', 'Book a flight to\nPorto.'),
                           ('audio_ref', 'unverified.mp3')]:
            ctx = deepcopy(original)
            ctx['messages'][0]['payload'][key] = value
            contexts.append(ctx)
        for key, value in [('observations', [{'type': 'audio', 'uncertain': False}]), ('latest_frame_index', 0),
                           ('planning_error', 'Repair needed'), ('tool_results', [{'status': 'success'}]),
                           ('current_turn_start', True), ('revision', True)]:
            contexts.append({**deepcopy(original), key: value})
        for ctx in contexts:
            with self.subTest(context=ctx):
                await self.route(ctx, False)

    async def test_changed_manifest_semantics_and_unknown_tools_defer(self):
        changes = [
            ('book_flight', 'description', 'Book and charge an additional fee.'),
            ('book_flight', 'kind', 'read_only'),
            ('book_flight', 'args', {**TOOLS['book_flight']['args'], 'account': {'type': 'string', 'required': True}}),
            ('flight_search', 'description', 'Search old booking records.'),
            ('flight_search', 'conditions', 'Members only'),
            ('flight_search', 'result_shape', {'status': 'string', 'flights': [{'flight_id': 'number'}]}),
        ]
        for name, key, value in changes:
            with self.subTest(name=name, key=key):
                tools = deepcopy(TOOLS)
                tools[name][key] = value
                await self.route(input_agent(tools=tools)._context(), False)
        for description in ('ISO dates only.', None, {'format': 'date'}):
            tools = deepcopy(TOOLS)
            tools['flight_search']['args']['date']['description'] = description
            await self.route(input_agent(tools=tools)._context(), False)
        await self.route(input_agent(tools={'lookup_journeys': {'kind': 'read_only', 'args': {}}})._context(), False)

    async def test_only_matching_prior_read_state_and_operations_are_admitted(self):
        agent = input_agent([speech('Book a flight to Lima for Friday.')])
        agent._apply(planning._simple_flight_discovery(agent._context()))
        update(agent, correction('Make that Porto.'))
        good = agent._context()
        self.assertEqual(good['actions'][0]['status'], 'cancel_requested')
        await self.route(good, True)
        for state in ({'intent': 'book_flight', 'slots': {'destination': 'Dakar', 'date': 'Friday'}},
                      {'intent': 'book_flight', 'slots': {**good['state']['slots'], 'passenger_name': 'Nia'}},
                      {'intent': 'book_flight', 'slots': {**good['state']['slots'], 'budget': 80}},
                      {'intent': {}, 'slots': {}}, {'intent': 'unrelated', 'slots': good['state']['slots']}):
            await self.route({**deepcopy(good), 'state': state}, False)
        for key, value in [('kind', 'state_modifying'), ('api_name', 'other_read'), ('args', {'destination': 'Dakar'}),
                           ('revision', good['revision']), ('revision', True), ('status', 'unknown'),
                           ('status', []), ('call_id', None), ('extra_meaning', True)]:
            ctx = deepcopy(good)
            ctx['actions'][0][key] = value
            await self.route(ctx, False)


class TextDiscoveryLoopTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.planner = DiscoveryPlanner()
        self.agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue(), planner=self.planner)
        self.outputs = []
        self.task = asyncio.create_task(self.agent.run())
        await self.send(('tool_manifest', {'tools': deepcopy(TOOLS)}))

    async def asyncTearDown(self):
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)

    async def send(self, event):
        await self.agent.in_queue.put({'event_type': event[0], 'payload': event[1]})

    async def take(self, action):
        while True:
            value = await asyncio.wait_for(self.agent.out_queue.get(), 3)
            self.outputs.append(value)
            if value['action'] == action:
                return value['payload']

    async def result(self, call, label):
        await self.send(('tool_result', {**call, 'status': 'success',
            'result': {'status': 'success', 'flights': [{**ROWS[0], 'flight_id': label}]}}))

    async def test_pending_mock_read_is_cancelled_then_late_result_is_silent(self):
        await self.send(speech('Book a flight to Lima for Friday.'))
        old = await self.take('tool_call')
        started, release, reconciled = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def pending_read():
            started.set()
            await release.wait()
            await self.result(old, 'OLD-RETURNED')

        worker = asyncio.create_task(pending_read())
        await asyncio.wait_for(started.wait(), 3)
        self.assertFalse(worker.done())
        await self.send(correction('Make that Porto.'))
        cancelled = await self.take('cancel_tool')
        self.assertEqual(cancelled['call_id'], old['call_id'])
        current = await self.take('tool_call')
        self.assertEqual(current['args'], {'destination': 'Porto', 'date': 'Friday'})
        self.assertNotEqual(current['call_id'], old['call_id'])
        original_result = self.agent._result

        def observe_result(payload):
            original_result(payload)
            if payload['call_id'] == old['call_id']:
                reconciled.set()

        with patch.object(self.agent, '_result', observe_result):
            release.set()
            await asyncio.wait_for(worker, 3)
            await asyncio.wait_for(reconciled.wait(), 3)
        self.assertTrue(self.agent.out_queue.empty())
        self.assertEqual(self.agent.operations[old['call_id']]['status'], 'success')
        await self.result(current, 'CURRENT-RETURNED')
        facts = await self.take('final_response')
        await self.take('clarification_request')
        self.assertIn('CURRENT-RETURNED', facts['text'])
        self.assertNotIn('OLD-RETURNED', facts['text'])
        self.assertEqual(self.agent.state, {'intent': 'book_flight', 'slots': current['args']})
        self.assertEqual(self.agent._user_texts(), [(1, 'Make that Porto.')])
        self.assertEqual(self.planner.generation_calls, 0)
        self.assertFalse(self.agent._consumed_grants)

    async def test_completed_read_then_new_correction_and_clarification_latch(self):
        await self.send(speech('Reserve a flight to Dakar on 2027-03-18.'))
        first = await self.take('tool_call')
        await self.result(first, 'FIRST-RETURNED')
        await self.take('final_response')
        await self.take('clarification_request')
        self.assertTrue(self.agent._awaiting_clarification)
        await self.send(speech('Actually make it Porto.'))
        second = await self.take('tool_call')
        self.assertEqual(second['args'], {'destination': 'Porto', 'date': '2027-03-18'})
        await self.result(second, 'SECOND-RETURNED')
        await self.take('final_response')
        await self.take('clarification_request')
        self.assertFalse(any(o['action'] == 'cancel_tool' for o in self.outputs))
        with patch.object(self.agent, '_start_plan') as start:
            self.agent._handle({'event_type': 'video_frame', 'payload': {'image_ref': 'frame.png'}})
            self.agent._handle({'event_type': 'tool_manifest', 'payload': {'tools': {**TOOLS, 'unrelated': {'kind': 'read_only', 'args': {}}}}})
            self.agent._apply({'intent': 'ignored', 'slots': {}, 'tool_calls': [second]})
            start.assert_not_called()
        self.assertTrue(self.agent.out_queue.empty())
        self.assertEqual(self.planner.generation_calls, 0)
        self.assertFalse(self.agent._consumed_grants)

    async def test_queued_correction_wins_before_any_initial_read_is_dispatched(self):
        await self.send(speech('Book a flight to Lima for tomorrow.'))
        await self.send(correction('Actually make that Porto.'))
        current = await self.take('tool_call')
        self.assertEqual(current['args'], {'destination': 'Porto', 'date': 'tomorrow'})
        self.assertEqual(len(self.agent.operations), 1)
        await self.result(current, 'ONLY-CURRENT')
        await self.take('final_response')
        await self.take('clarification_request')
        self.assertEqual(self.planner.generation_calls, 0)
        self.assertEqual(self.agent._request_start, 1)
        self.assertFalse(self.agent._consumed_grants)


if __name__ == '__main__':
    unittest.main()
