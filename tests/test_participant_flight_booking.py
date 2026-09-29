"""Offline checks for a bounded documented-API command, not model accuracy."""
import asyncio
from copy import deepcopy
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import httpx

from participant import planner as planning
from participant.agent import ParticipantAgent


TOOLS = {
    'flight_search': {
        'kind': 'read_only', 'description': 'Search flights to a destination city on a given date.',
        'args': {'destination': {'type': 'string', 'required': True, 'description': 'Destination city name or airport code.'},
                 'date': {'type': 'string', 'required': False, 'description': 'Departure date, free-form.'}}},
    'book_flight': {
        'kind': 'state_modifying', 'description': 'Book a specific flight returned by flight_search.',
        'args': {'flight_id': {'type': 'string', 'required': True, 'description': 'A flight id returned by flight_search.'},
                 'passenger_name': {'type': 'string', 'required': True, 'description': 'Full name of the passenger.'}}},
}
TEXT = 'Find flights to Oslo and book the 7:45 PM one for Nia.'


def context(text=TEXT):
    return {'revision': 1, 'current_turn_start': 0,
            'messages': [{'message_index': 0, 'revision': 1, 'event_type': 'user_speech_chunk',
                          'payload': {'text': text, 'end_of_turn': True}}],
            'state': {'intent': '', 'slots': {}}, 'actions': [], 'tool_results': [], 'observations': [],
            'latest_frame_index': None, 'tools': deepcopy(TOOLS)}


class FlightBookingTests(unittest.TestCase):
    def test_literal_substitutions_preserve_time_identity_and_original_authority(self):
        cases = [
            (TEXT, 'Oslo', '19:45', 'Nia', None),
            ('Please search for a flight to Łódź on Monday then reserve the 12 AM one for Kai.',
             'Łódź', '00:00', 'Kai', 'Monday'),
            ("Find me flights to N'Djamena and book the 12:00 PM one for Ana-María.",
             "N'Djamena", '12:00', "Ana-María", None),
            ('search flights to Dakar and then reserve the 01:09 am one for Éva.',
             'Dakar', '01:09', 'Éva', None),
            ("Find flights to Busan and book the 11:59 PM flight for O'Neill.",
             'Busan', '23:59', "O'Neill", None),
            ('Find flights to Quito and book the 9 AM one for kai.',
             'Quito', '09:00', 'kai', None),
        ]
        for text, destination, depart, person, day in cases:
            with self.subTest(text=text):
                original = context(text)
                untouched = deepcopy(original)
                plan = planning._simple_flight_booking(original)
                self.assertIsNotNone(plan)
                self.assertEqual(original, untouched)
                call = plan['tool_calls'][0]
                self.assertEqual(call['args'], {'destination': destination, **({'date': day} if day else {})})
                follow = call['after_result']
                self.assertEqual(follow['args'], {'passenger_name': person})
                self.assertEqual(follow['select'], {'path': 'flights', 'where': {'depart': depart}})
                self.assertEqual(follow['bindings'], {'flight_id': 'flight_id'})
                self.assertEqual(follow['authorization'], {'quote': text})
                self.assertEqual(call['response_template'], '')
                self.assertIn('{booking_id}', follow['response_template'])
                self.assertEqual(plan['slots']['depart'], depart)
                self.assertEqual(plan['slots']['passenger_name'], person)
                self.assertIsNone(plan['clarification'])

    def test_exact_completed_fragments_are_joined_without_minting_authority(self):
        value = context()
        value['messages'][0]['payload'] = {'text': 'Find flights to Oslo and ', 'end_of_turn': False}
        value['messages'].append({'message_index': 1, 'revision': 1, 'event_type': 'user_speech_chunk',
                                  'payload': {'text': 'book the 7:45 PM one for Nia.', 'end_of_turn': True}})
        plan = planning._simple_flight_booking(value)
        self.assertEqual(plan['tool_calls'][0]['after_result']['authorization'], {'quote': TEXT})
        value['messages'][0]['payload']['text'] = 'Find flights to Oslo and'
        self.assertIsNone(planning._simple_flight_booking(value))

    def test_extra_meaning_ambiguous_literals_and_invalid_times_defer(self):
        for text in [
            TEXT.replace('Nia', 'Nia Sato'), TEXT.replace('Nia', 'Nia Carrying Lithium Batteries'),
            TEXT.replace('Nia', 'Nia using miles'), TEXT.replace('Nia', 'Nia carrying lithium batteries'),
            TEXT.replace('Nia', 'myself'), TEXT.replace('Nia', 'themselves'),
            TEXT.replace('Nia', 'someone'), TEXT.replace('Nia', 'Whoever'),
            TEXT.replace('Nia', 'self'), TEXT.replace('Nia', 'mine'),
            TEXT + ' Only if refundable.', TEXT + ' Do not book it.', TEXT + ' Cancel my old flight.',
            TEXT.replace('and book', 'and do not book'), TEXT.replace('book the', 'maybe book the'),
            TEXT.replace('Nia', 'me'), TEXT.replace('Nia', 'Nia tomorrow'),
            TEXT.replace('Nia', 'Nia with baggage'), TEXT.replace('Nia', 'Nia and Kai'),
            TEXT.replace('Nia', 'the same passenger'), TEXT.replace('Nia', 'Nia under budget'),
            TEXT.replace('Nia', 'Nia refundable'), TEXT.replace('Oslo', 'home'),
            TEXT.replace('Oslo', 'Oslo tomorrow'), TEXT.replace('Oslo', 'Oslo under $500'),
            TEXT.replace('Oslo', '"San José"'), TEXT.replace('Nia', '"Nia"'),
            TEXT.replace('7:45 PM', '00:45 PM'), TEXT.replace('7:45 PM', '13 PM'),
            TEXT.replace('7:45 PM', '7:60 PM'), TEXT.replace('7:45 PM', '7:45'),
            TEXT.replace('7:45 PM', '7:45 PM UTC'), TEXT.replace('7:45 PM', 'earliest'),
            TEXT.replace('7:45 PM', 'cheapest 7:45 PM'), TEXT.replace('for Nia', 'for Nia if free'),
            'Someone said ' + TEXT, 'Suppose I ' + TEXT, TEXT.replace('and book', '\nand book'),
        ]:
            with self.subTest(text=text):
                self.assertIsNone(planning._simple_flight_booking(context(text)))

    def test_prior_state_corrections_media_and_incomplete_turns_defer(self):
        for update in [
            {'current_turn_start': 1}, {'state': {'intent': 'booking', 'slots': {}}},
            {'state': {'intent': '', 'slots': {'origin': 'Lima'}}}, {'actions': [{'status': 'pending'}]},
            {'tool_results': [{'status': 'success'}]}, {'observations': [{'type': 'audio'}]},
            {'planning_error': 'retry'}, {'latest_frame_index': 0},
        ]:
            with self.subTest(update=update):
                self.assertIsNone(planning._simple_flight_booking({**context(), **update}))
        for event in ('interruption', 'user_audio_chunk', 'video_frame'):
            value = context()
            value['messages'][0]['event_type'] = event
            self.assertIsNone(planning._simple_flight_booking(value))
        value = context()
        value['messages'][0]['payload']['end_of_turn'] = False
        self.assertIsNone(planning._simple_flight_booking(value))

    def test_personal_possessive_and_choice_references_defer_in_every_case(self):
        for reference in ('he', 'she', 'we', 'they', 'my', 'your', 'our', 'their', 'its',
                          'none', 'either', 'neither', 'both', 'others', 'what', 'which'):
            for spelling in (reference, reference.upper()):
                with self.subTest(spelling=spelling):
                    self.assertIsNone(planning._simple_flight_booking(context(TEXT.replace('Nia', spelling))))

    def test_changed_or_undeclared_tool_contracts_defer(self):
        changes = [
            ('book_flight', 'kind', 'read_only'),
            ('book_flight', 'description', 'Book a flight and charge an additional membership fee.'),
            ('flight_search', 'description', 'Search previous bookings only.'),
            ('book_flight', 'args', {**TOOLS['book_flight']['args'], 'card': {'type': 'string', 'required': True}}),
            ('book_flight', 'args', {**TOOLS['book_flight']['args'], 'passenger_name': {'type': 'number', 'required': True}}),
            ('book_flight', 'args', {**TOOLS['book_flight']['args'], 'flight_id': {'type': 'string', 'required': False}}),
            ('book_flight', 'args', {**TOOLS['book_flight']['args'], 'flight_id': {**TOOLS['book_flight']['args']['flight_id'], 'required': 1}}),
            ('book_flight', 'result_shape', {'status': 'string', 'booking_id': 'number', 'flight_id': 'string'}),
            ('flight_search', 'result_shape', {'flights': [{'flight_id': 'string', 'depart': 'number', 'price_usd': 'number'}]}),
            ('book_flight', 'conditions', 'Only for account owner'),
        ]
        for name, key, value in changes:
            with self.subTest(name=name, key=key):
                supplied = context()
                supplied['tools'][name][key] = value
                self.assertIsNone(planning._simple_flight_booking(supplied))
        supplied = context()
        del supplied['tools']['book_flight']
        self.assertIsNone(planning._simple_flight_booking(supplied))

    def test_actual_unique_returned_id_and_explicit_authority_reach_controller(self):
        value = context()
        plan = planning._simple_flight_booking(value)
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.tools, agent.messages, agent.revision = value['tools'], value['messages'], 1
        agent._apply(plan)
        read = agent.out_queue.get_nowait()['payload']
        self.assertEqual(read['api_name'], 'flight_search')
        agent._result({'call_id': read['call_id'], 'api_name': read['api_name'], 'status': 'success',
                       'result': {'status': 'success', 'flights': [
                           {'flight_id': 'wrong-row', 'depart': '07:45', 'price_usd': 12},
                           {'flight_id': 'actual-returned-id', 'depart': '19:45', 'price_usd': 29}]}})
        write = agent.out_queue.get_nowait()['payload']
        self.assertEqual(write['api_name'], 'book_flight')
        self.assertEqual(write['args'], {'passenger_name': 'Nia', 'flight_id': 'actual-returned-id'})
        self.assertEqual(len(agent._consumed_grants), 1)


class FlightBookingRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_supported_command_uses_local_evidence_and_near_miss_uses_model_transport(self):
        requests = []
        def transport(request):
            requests.append(request)
            return httpx.Response(200, json={'candidates': [{'finishReason': 'STOP', 'content': {'parts': [
                {'text': json.dumps({'observations': [], 'intent': 'book flight', 'slots': {}, 'tool_calls': [],
                                    'clarification': 'Which constraint should I use?', 'response': None})}]}}]})
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {
            'SECRET_GEMINI_API_KEY': 'offline-test-key', 'PARTICIPANT_MEDIA_ROOT': root, 'PARTICIPANT_PREWARM': '0'
        }, clear=True):
            planner = planning.Planner(transport=httpx.MockTransport(transport))
            await planner.setup()
            try:
                plan = await planner.plan(context())
                self.assertEqual(requests, [])
                self.assertIsNotNone(plan['tool_calls'][0]['after_result'])
                self.assertEqual(planner.evidence[-1]['rule'], 'documented_flight_booking')
                self.assertEqual(planner.evidence[-1]['phase'], 'local_planning')
                self.assertNotIn('model', planner.evidence[-1])
                await planner.plan(context(TEXT + ' Only if refundable.'))
                self.assertEqual(len(requests), 1)
                self.assertEqual(planner.evidence[-1]['phase'], 'planning')
            finally:
                await planner.close()


if __name__ == '__main__':
    unittest.main()
