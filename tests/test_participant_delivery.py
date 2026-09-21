"""Offline regression checks for explicit Gemini setup and literal text delivery."""
import asyncio
import json
import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import httpx

from participant.agent import ParticipantAgent
from participant.planner import DEFAULT_MODEL, Planner, PlannerError, _simple_capabilities, _simple_flight_search
from participant.schema import validate_args


def flight_context(*fragments):
    return {
        'revision': 1, 'current_turn_start': 0,
        'messages': [{'message_index': i, 'revision': 1, 'event_type': 'user_speech_chunk',
                      'payload': {'text': text, 'end_of_turn': i == len(fragments) - 1}}
                     for i, text in enumerate(fragments)],
        'state': {'intent': '', 'slots': {}}, 'actions': [], 'tool_results': [], 'observations': [],
        'latest_frame_index': None,
        'tools': {'flight_search': {'kind': 'read_only', 'args': {
            'destination': {'type': 'string', 'required': True},
            'date': {'type': 'string', 'required': False,
                     'description': "Departure date, free-form (e.g. 'tomorrow', '2026-09-12')."}}}},
    }


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        env = patch.dict(os.environ, {'SECRET_GEMINI_API_KEY': 'process-test-key',
                                     'PARTICIPANT_MEDIA_ROOT': str(self.root),
                                     'PARTICIPANT_PREWARM': '0'}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    async def make_planner(self, handler=None):
        if handler is None:
            handler = lambda _: self.fail('This offline path must not contact Gemini.')
        planner = Planner(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(planner.close)
        await planner.setup()
        return planner

    def env_file(self, content):
        path = self.root / 'explicit.env'
        path.write_text(content, encoding='utf-8')
        os.environ['PARTICIPANT_ENV_FILE'] = str(path)
        return path

    async def test_literal_weekdays_and_exact_fragments_use_validator_without_provider(self):
        planner = await self.make_planner()
        cases = [
            (('Can you find flights to ', 'Chicago for Friday?'), 'Chicago', 'Friday'),
            (('can you please search for a flight to Reykjavík on mOnDaY?',), 'Reykjavík', 'mOnDaY'),
            (('Find flights to "San ', 'José"', ' on Tuesday.'), 'San José', 'Tuesday'),
            (('Please find me flights to ', "N'Djamena for Wednesday please?"), "N'Djamena", 'Wednesday'),
            (('Search flights to Łódź for Thursday',), 'Łódź', 'Thursday'),
            (('Can you find a flight to Porto-Alegre on Saturday?',), 'Porto-Alegre', 'Saturday'),
            (('Find flights to Nairobi on Sunday.',), 'Nairobi', 'Sunday'),
            (('Can you find flights to', ' Quito?'), 'Quito', None),
        ]
        for fragments, destination, weekday in cases:
            with self.subTest(fragments=fragments):
                context = flight_context(*fragments)
                original = deepcopy(context)
                expected = {'destination': destination}
                if weekday is not None:
                    expected['date'] = weekday
                with patch('participant.schema.validate_args', wraps=validate_args) as checked:
                    result = await planner.plan(context)
                checked.assert_called_once_with(context['tools']['flight_search'], expected)
                self.assertEqual(result['slots'], expected)
                self.assertEqual(result['tool_calls'][0]['args'], expected)
                self.assertEqual(len(result['tool_calls']), 1)
                self.assertNotIn('authorization', result['tool_calls'][0])
                self.assertNotIn('after_result', result['tool_calls'][0])
                self.assertIn('{flights.0.flight_id}', result['tool_calls'][0]['response_template'])
                self.assertEqual(planner.evidence[-1]['phase'], 'local_planning')
                self.assertEqual(context, original)

    def test_fragment_integrity_and_retained_context_defer(self):
        base = flight_context('Can you find flights to ', 'Chicago for Friday?')
        mutations = [
            (('revision',), 2), (('revision',), True),
            (('messages', 0, 'revision'), 0), (('messages', 1, 'revision'), None),
            (('messages', 1, 'revision'), True), (('messages', 1, 'message_index'), 2),
            (('messages', 0, 'message_index'), False),
            (('messages', 0, 'payload', 'end_of_turn'), True),
            (('messages', 0, 'payload', 'end_of_turn'), 0),
            (('messages', 1, 'payload', 'end_of_turn'), False),
            (('messages', 1, 'payload', 'end_of_turn'), 1),
            (('messages', 0, 'event_type'), 'user_audio_chunk'),
            (('messages', 0, 'payload', 'text'), ''),
            (('messages', 0, 'payload', 'text'), 'Can you find flights to\n'),
            (('current_turn_start',), 1), (('state', 'slots'), {'budget': 400}),
            (('actions',), [{'status': 'success'}]), (('tool_results',), [{'status': 'error'}]),
            (('observations',), [{'type': 'audio'}]), (('latest_frame_index',), 0),
            (('planning_error',), 'Repair a prior proposal'),
        ]
        for path, value in mutations:
            with self.subTest(path=path, value=value):
                context = deepcopy(base)
                target = context
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                self.assertIsNone(_simple_flight_search(context))
        for fragments in [('Find flights to Chi', 'cago for Friday?'),
                          ('Find flights to ', 'Chicago for Fri', 'day?'),
                          ('Find flights to', 'Chicago for Friday?')]:
            with self.subTest(fragments=fragments):
                self.assertIsNone(_simple_flight_search(flight_context(*fragments)))

    async def test_extra_meaning_across_fragments_reaches_model_whole(self):
        cases = [
            ('Keep the fare under $400. ', 'Can you find flights to Chicago for Friday?'),
            ('Can you find flights to ', 'Chicago for Friday and book one?'),
            ('Do not ', 'find flights to Chicago for Friday.'),
            ('If refundable, ', 'find flights to Chicago for Friday.'),
            ('"Can you find flights to ', 'Chicago for Friday?"'),
            ('Find flights to ', 'Chicago for Friday, not London.'),
            ('Find flights to ', 'Chicago tomorrow?'),
            ('Find flights to ', 'Chicago for 2026-10-02?'),
            ('Find flights to ', 'New York for Friday?'),
            ('Find flights to ', 'home for Friday?'),
        ]
        for fragments in cases:
            with self.subTest(fragments=fragments):
                self.assertIsNone(_simple_flight_search(flight_context(*fragments)))
        captured = []

        def handler(request):
            captured.append(json.loads(request.content))
            decision = {'observations': [], 'intent': 'travel', 'slots': {}, 'tool_calls': [],
                        'clarification': 'Which budget should I use?', 'response': None}
            return httpx.Response(200, json={'candidates': [{'finishReason': 'STOP',
                                  'content': {'parts': [{'text': json.dumps(decision)}]}}]})

        planner = await self.make_planner(handler)
        await planner.plan(flight_context(*cases[0]))
        self.assertEqual(len(captured), 1)
        prepared = json.loads(captured[0]['contents'][0]['parts'][0]['text'])
        self.assertEqual([m['payload']['text'] for m in prepared['messages']], list(cases[0]))
        self.assertIsNone(_simple_capabilities(flight_context('What can ', 'you do?')))

    def test_weekday_requires_compatible_optional_string_contract(self):
        context = flight_context('Can you find flights to Chicago for Friday?')
        for date in [None, {'type': 'string', 'required': True}, {'type': 'integer'},
                     {'type': 'string', 'enum': ['Friday']}, {'type': 'string', 'format': 'date'},
                     {'type': 'string', 'description': 'YYYY-MM-DD only'},
                     {'type': 'string', 'description': 'ISO 8601 date'},
                     {'type': 'string', 'description': 'Free-form date, but YYYY-MM-DD is required.'},
                     {'type': 'string', 'description': 'Free-form date; weekday names are not accepted.'},
                     {'type': 'string', 'description': 'Free-form date; use YYYY-MM-DD.'},
                     {'type': 'string', 'description': "Free-form date (e.g. 'tomorrow'; weekday names are not accepted)."},
                     {'type': 'string', 'description': "Free-form date (e.g. 'tomorrow', but not weekdays)."},
                     {'type': 'string', 'description': "Free-form date (e.g. 'tomorrow'). ISO8601 required."}]:
            with self.subTest(date=date):
                candidate = deepcopy(context)
                if date is None:
                    del candidate['tools']['flight_search']['args']['date']
                else:
                    candidate['tools']['flight_search']['args']['date'] = date
                self.assertIsNone(_simple_flight_search(candidate))
        for description in ['', 'Free-form date', 'Date, free form.',
                            "Departure date, free-form (e.g. 'Thursday', '2031-07-14')."]:
            with self.subTest(description=description):
                context['tools']['flight_search']['args']['date'] = {'type': 'string', 'description': description}
                self.assertEqual(_simple_flight_search(context)['slots']['date'], 'Friday')
        context['tools']['flight_search']['args']['destination']['enum'] = ['Nairobi']
        self.assertIsNone(_simple_flight_search(context))

    async def test_real_agent_dispatches_fragmented_read_and_uses_only_delivered_result(self):
        planner = await self.make_planner()
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue(), planner=planner)
        task = asyncio.create_task(agent.run())

        async def output(kind):
            while True:
                action = await agent.out_queue.get()
                if action['action'] == kind:
                    return action

        try:
            context = flight_context('Can you find flights to ', 'Chicago for Friday?')
            agent.in_queue.put_nowait({'event_type': 'tool_manifest', 'payload': {'tools': context['tools']}})
            for message in context['messages']:
                agent.in_queue.put_nowait({'event_type': message['event_type'], 'payload': message['payload']})
            call = await asyncio.wait_for(output('tool_call'), 1)
            self.assertEqual(call['payload']['args'], {'destination': 'Chicago', 'date': 'Friday'})
            self.assertEqual(call['state_snapshot']['slots'], call['payload']['args'])
            agent.in_queue.put_nowait({'event_type': 'tool_result', 'payload': {
                **call['payload'], 'status': 'success', 'result': {'status': 'success',
                'flights': [{'flight_id': 'DELIVERED-42', 'depart': '09:10', 'price_usd': 237}]}}})
            final = await asyncio.wait_for(output('final_response'), 1)
            for actual in ('DELIVERED-42', '09:10', '237'):
                self.assertIn(actual, final['payload']['text'])
            self.assertEqual(final['state_snapshot']['slots']['date'], 'Friday')
            self.assertEqual(len(agent.operations), 1)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(agent._closed)
        self.assertIsNone(planner.client)

    async def test_process_alias_tier_overrides_entire_file_group(self):
        self.env_file('THREAD_API_KEY=file-old-key\nSECRET_GEMINI_API_KEY=file-other-key\n'
                      'THREAD_MODEL=gemini-3.5-flash-lite\nPARTICIPANT_MODEL=gemini-2.5-flash-lite\n')
        os.environ['PARTICIPANT_MODEL'] = 'gemini-2.5-flash'
        os.environ['PARTICIPANT_THINKING_BUDGET'] = '0'
        planner = await self.make_planner()
        self.assertEqual(planner._key, 'process-test-key')
        self.assertEqual(planner.model, 'gemini-2.5-flash')
        self.assertEqual(planner.thinking_budget, 0)

    async def test_file_only_aliases_are_explicitly_loaded(self):
        del os.environ['SECRET_GEMINI_API_KEY']
        for alias in ('THREAD_API_KEY', 'SECRET_GEMINI_API_KEY'):
            with self.subTest(alias=alias):
                self.env_file(f'{alias}=file-test-key\nTHREAD_MODEL=gemini-2.5-flash\n'
                              'PARTICIPANT_THINKING_BUDGET=0\nPARTICIPANT_IMAGE_EMBEDDING=0\n')
                planner = await self.make_planner()
                self.assertEqual(planner._key, 'file-test-key')
                self.assertEqual(planner.model, 'gemini-2.5-flash')
                self.assertEqual(planner.thinking_budget, 0)
                self.assertFalse(planner.image_embedding)

    async def test_same_tier_conflicts_fail_without_disclosing_values(self):
        for source in ('process', 'file'):
            for names in [('THREAD_API_KEY', 'SECRET_GEMINI_API_KEY'), ('THREAD_MODEL', 'PARTICIPANT_MODEL')]:
                with self.subTest(source=source, names=names), patch.dict(os.environ):
                    os.environ.pop('SECRET_GEMINI_API_KEY', None)
                    values = {names[0]: 'first-private-value', names[1]: 'second-private-value'}
                    if source == 'file':
                        self.env_file(''.join(f'{key}={value}\n' for key, value in values.items()))
                    else:
                        os.environ.update(values)
                    with self.assertRaisesRegex(PlannerError, 'Conflicting configuration') as error:
                        await self.make_planner()
                    for value in values.values():
                        self.assertNotIn(value, str(error.exception))

    async def test_explicit_blank_process_alias_suppresses_file_fallback(self):
        self.env_file('THREAD_API_KEY=file-test-key\nTHREAD_MODEL=gemini-2.5-flash\n')
        os.environ['SECRET_GEMINI_API_KEY'] = ''
        os.environ['PARTICIPANT_MODEL'] = ''
        planner = await self.make_planner()
        self.assertEqual(planner.model, DEFAULT_MODEL)
        self.assertEqual(planner._key, '')
        with self.assertRaisesRegex(PlannerError, 'SECRET_GEMINI_API_KEY or THREAD_API_KEY'):
            await planner.plan(flight_context('Find flights to Quito'))

    async def test_implicit_dotenv_is_not_read(self):
        with patch('participant.planner.dotenv_values', side_effect=AssertionError('Implicit dotenv read')):
            planner = await self.make_planner()
        self.assertEqual(planner.model, DEFAULT_MODEL)

    async def test_bad_explicit_env_file_is_sanitized_before_network(self):
        for path in (self.root / 'missing-private-name.env', self.root):
            with self.subTest(path=path):
                os.environ['PARTICIPANT_ENV_FILE'] = str(path)
                with self.assertRaisesRegex(PlannerError, 'PARTICIPANT_ENV_FILE') as error:
                    await self.make_planner()
                self.assertNotIn(str(path), str(error.exception))
        path = self.env_file('THREAD_API_KEY=file-test-key\n')
        with patch('participant.planner.dotenv_values', side_effect=PermissionError('private file detail')):
            with self.assertRaisesRegex(PlannerError, 'path and encoding') as error:
                await self.make_planner()
            self.assertNotIn('private file detail', str(error.exception))
        path.write_bytes(b'\xff\xfe\x80')
        with self.assertRaisesRegex(PlannerError, 'path and encoding'):
            await self.make_planner()

    async def test_provider_status_has_fixed_advice_without_retry_or_body_disclosure(self):
        for status, advice in [(400, 'model and thinking'), (401, 'API key'),
                               (403, 'permissions'), (404, 'model identifier'),
                               (429, 'quota'), (503, 'provider request failed')]:
            with self.subTest(status=status):
                calls = []

                def handler(request):
                    calls.append(request)
                    return httpx.Response(status, text='private provider detail process-test-key')

                planner = await self.make_planner(handler)
                with self.assertRaisesRegex(PlannerError, f'HTTP {status}') as error:
                    await planner.plan(flight_context('Find flights to Chicago tomorrow.'))
                self.assertIn(advice, str(error.exception))
                self.assertNotIn('private provider detail', str(error.exception))
                self.assertNotIn('process-test-key', str(error.exception))
                self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
