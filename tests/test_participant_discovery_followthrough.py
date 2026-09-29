"""Injected decisions/results exercise conversational recovery, never provider quality."""
import asyncio
from copy import deepcopy
import unittest
from unittest.mock import patch

from participant.agent import ParticipantAgent
from tests.test_participant_flight_booking import TOOLS


ROWS = [{'flight_id': 'RETURNED-A', 'depart': '06:20', 'price_usd': 83},
        {'flight_id': 'RETURNED-B', 'depart': '16:40', 'price_usd': 71}]


def speech(text, end=True):
    return ('user_speech_chunk', {'text': text, 'end_of_turn': end})


def correction(text):
    return ('interruption', {'text': text})


def audio(index, end):
    return ('user_audio_chunk', {'audio_ref': f'clip-{index}.mp3', 'end_of_turn': end})


class DiscoveryFollowThroughTests(unittest.TestCase):
    def agent(self, events=None, *, destination='Porto', date=None, observations=(), slots=None, template='', tools=None):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        # Only planning is injected. Real input handling establishes revisions/authority.
        with patch.object(agent, '_start_plan'):
            agent._handle({'event_type': 'tool_manifest', 'payload': {'tools': deepcopy(tools or TOOLS)}})
            for kind, payload in events or [speech('Please book a flight to Porto.')]:
                agent._handle({'event_type': kind, 'payload': payload})
        args = {'destination': destination, **({'date': date} if date is not None else {})}
        agent._apply({'intent': 'search_flights', 'slots': args if slots is None else slots,
                      'observations': list(observations), 'tool_calls': [
                          {'api_name': 'flight_search', 'args': args, 'response_template': template}]})
        emitted = self.drain(agent)
        calls = [item['payload'] for item in emitted if item['action'] == 'tool_call']
        self.assertEqual(len(calls), 1)
        return agent, calls[0]

    @staticmethod
    def drain(agent):
        result = []
        while not agent.out_queue.empty():
            result.append(agent.out_queue.get_nowait())
        return result

    def deliver(self, agent, call, result=None):
        agent._result({'call_id': call['call_id'], 'api_name': call['api_name'],
                       'status': 'success', 'result': result or {'status': 'success', 'flights': deepcopy(ROWS)}})
        return self.drain(agent)

    def test_verified_booking_gets_facts_then_one_latched_question(self):
        agent, call = self.agent()
        before_messages, before_step = deepcopy(agent.messages), deepcopy(agent.operations[call['call_id']]['step'])
        outputs = self.deliver(agent, call)
        self.assertEqual([o['action'] for o in outputs], ['final_response', 'clarification_request'])
        self.assertIn('RETURNED-A', outputs[0]['payload']['text'])
        self.assertIn('passenger name', outputs[1]['payload']['text'])
        self.assertEqual(agent.state, {'intent': 'book_flight', 'slots': {'destination': 'Porto'}})
        self.assertTrue(agent._awaiting_clarification)
        self.assertFalse(agent._consumed_grants)
        self.assertEqual(agent.messages, before_messages)
        self.assertEqual(agent.operations[call['call_id']]['step'], before_step)
        self.assertEqual(self.deliver(agent, call), [])

    def test_fragmented_text_goal_survives_only_destination_correction(self):
        events = [speech('Please book a flight to ', False), speech('Lima for Friday.'),
                  correction('Wait, actually make it Porto.')]
        agent, call = self.agent(events, date='Friday')
        self.assertEqual(agent._request_start, 2)
        self.assertEqual(agent._user_texts(), [(2, 'Wait, actually make it Porto.')])
        outputs = self.deliver(agent, call)
        self.assertEqual([o['action'] for o in outputs], ['final_response', 'clarification_request'])
        self.assertEqual(agent._request_start, 2)
        self.assertEqual(agent.state['slots'], {'destination': 'Porto', 'date': 'Friday'})

    def test_completed_text_corrections_preserve_only_uninterrupted_booking_lineage(self):
        cases = [
            [speech('Book a flight to Lima.'), speech('Make that Porto.')],
            [speech('Book a flight to ', False), speech('Lima.'),
             speech('Actually make ', False), speech('that Porto.')],
            [speech('Book a flight to Lima.'), speech('Make that Dakar.'), correction('Make it Porto.')],
            [speech('Book a flight to Lima.'), correction('Make that Dakar.'), speech('Make it Porto.')],
        ]
        for events in cases:
            with self.subTest(events=events):
                agent, call = self.agent(events)
                messages, authority, request_start = deepcopy(agent.messages), agent._user_texts(), agent._request_start
                outputs = self.deliver(agent, call)
                self.assertEqual([o['action'] for o in outputs], ['final_response', 'clarification_request'])
                self.assertEqual(agent.state, {'intent': 'book_flight', 'slots': {'destination': 'Porto'}})
                self.assertEqual(agent.messages, messages)
                self.assertEqual(agent._user_texts(), authority)
                self.assertEqual(agent._request_start, request_start)
                self.assertFalse(agent._consumed_grants)
                self.assertEqual(len(agent.operations), 1)

    def test_unrelated_retracted_or_unclosed_text_breaks_completed_correction_lineage(self):
        cases = [
            [speech('Book a flight to Lima.'), speech('What is the weather?'), speech('Make that Porto.')],
            [speech('Book a flight to Lima.'), speech('Never mind.'), speech('Make that Porto.')],
            [speech('Book a flight to Lima.'), correction('Never mind.'), speech('Make that Porto.')],
            [speech('Book a flight to Lima.'), speech('Never mind.'), correction('Make that Porto.')],
            [speech('Book a flight to Lima.'), speech('Make th', False), speech('at Porto.')],
            [speech('Book a flight to Lima.', False), correction('Make that Porto.')],
        ]
        for events in cases:
            with self.subTest(events=events):
                agent, call = self.agent(events)
                self.assertEqual([o['action'] for o in self.deliver(agent, call)], ['final_response'])
                self.assertFalse(agent._awaiting_clarification)

    def test_full_booking_interruption_establishes_its_own_goal(self):
        cases = [
            [correction('Book a flight to Porto.')],
            [speech('What is the weather?'), correction('Book a flight to Porto.')],
            [speech('Book a flight to Lima.'), speech('Never mind.'), correction('Book a flight to Porto.')],
            [correction('Book a flight to Lima.'), speech('Make that Porto.')],
        ]
        for events in cases:
            with self.subTest(events=events):
                agent, call = self.agent(events)
                messages, authority, request_start = deepcopy(agent.messages), agent._user_texts(), agent._request_start
                self.assertEqual([o['action'] for o in self.deliver(agent, call)], ['final_response', 'clarification_request'])
                self.assertEqual(agent.state, {'intent': 'book_flight', 'slots': {'destination': 'Porto'}})
                self.assertEqual(agent.messages, messages)
                self.assertEqual(agent._user_texts(), authority)
                self.assertEqual(agent._request_start, request_start)
                self.assertFalse(agent._consumed_grants)
                self.assertEqual(len(agent.operations), 1)

    def test_unsupported_current_interruption_cannot_recover_a_prior_goal(self):
        for text in ('Do not book a flight to Porto.', '"Book a flight to Porto."',
                     'Book a flight to Porto if refundable.', 'Suppose I book a flight to Porto.',
                     'Find flights to Porto.', 'Book a flight to Porto for Nia.'):
            with self.subTest(text=text):
                agent, call = self.agent([speech('Book a flight to Lima.'), correction(text)])
                self.assertEqual([o['action'] for o in self.deliver(agent, call)], ['final_response'])
                self.assertFalse(agent._awaiting_clarification)

    def test_completed_text_lineage_keeps_prior_write_and_audio_barriers(self):
        for status in ('pending', 'cancel_requested', 'unknown', 'success', 'error'):
            with self.subTest(prior_write_status=status):
                agent, call = self.agent([speech('Book a flight to Lima.'), speech('Make that Porto.')])
                agent.operations['earlier-write'] = {**deepcopy(agent.operations[call['call_id']]),
                    'operation_id': 'earlier-write', 'kind': 'state_modifying', 'status': status,
                    'request_start': 0, 'revision': agent.messages[0]['revision']}
                self.assertEqual([o['action'] for o in self.deliver(agent, call)], ['final_response'])
        for uncertain in (True, False):
            with self.subTest(prior_audio_uncertain=uncertain):
                agent, call = self.agent([audio(0, True), speech('Make that Porto.')], observations=[
                    {'message_index': 0, 'type': 'audio', 'transcript': 'Book a flight to Lima.', 'uncertain': uncertain}])
                self.assertEqual([o['action'] for o in self.deliver(agent, call)], ['final_response'])

    def test_clear_current_audio_booking_and_repair_are_eligible(self):
        observations = [
            {'message_index': 0, 'type': 'audio', 'transcript': 'Uh, book a flight to Lima.', 'uncertain': False},
            {'message_index': 1, 'type': 'audio', 'transcript': 'Actually make that Porto.', 'uncertain': False}]
        agent, call = self.agent([audio(0, False), audio(1, True)], observations=observations)
        outputs = self.deliver(agent, call)
        self.assertEqual(outputs[-1]['action'], 'clarification_request')
        self.assertEqual(list(agent.observations.values()), observations)

    def test_unclear_old_audio_cannot_supply_booking_goal_to_confirmation(self):
        events = [audio(0, True), audio(1, True)]
        for uncertain in (True, False):
            with self.subTest(prior_uncertain=uncertain):
                observations = [
                    {'message_index': 0, 'type': 'audio', 'transcript': 'Book a flight to [unclear].', 'uncertain': uncertain},
                    {'message_index': 1, 'type': 'audio', 'transcript': 'I said Porto.', 'uncertain': False}]
                agent, call = self.agent(events, observations=observations)
                self.assertEqual([o['action'] for o in self.deliver(agent, call)], ['final_response'])

    def test_unsupported_or_retracted_dialogue_preserves_existing_answer(self):
        cases = [
            [speech('Find flights to Porto.')], [speech('Do not book a flight to Porto.')],
            [speech('Suppose I book a flight to Porto.')], [speech('"Book a flight to Porto."')],
            [speech('Book a flight to Porto if refundable.')], [speech('Book a flight to Porto for Nia.')],
            [speech('Book the morning flight to Porto.')], [speech('Book a flight to Porto. Cancel my hotel.')],
            [speech('Book a flight to Lima.'), correction('Actually, just search Porto.')],
            [speech('Book a flight to Lima.'), correction('Make it Porto and cancel the booking.')],
            [speech('Book a flight to Lima.'), correction('Make it Dakar.')],
            [speech('Book a flight to Lima.'), speech('Search for Porto.')],
            [speech('Book a flight to Lima.'), correction('Never mind.'), correction('Make it Porto.')],
            [speech('Book a flight to Li', False), speech('ma.'), correction('Make it Porto.')],
        ]
        for events in cases:
            with self.subTest(events=events):
                agent, call = self.agent(events)
                receipt = {'status': 'success', 'flights': deepcopy(ROWS)}
                self.assertEqual(agent.operations[call['call_id']]['status'], 'pending')
                # Predict presentation of the completed receipt, not a pending
                # operation with an injected body that has never been admitted.
                expected = agent._render({**agent.operations[call['call_id']],
                                          'status': 'success', 'result': receipt})
                outputs = self.deliver(agent, call)
                self.assertEqual([o['action'] for o in outputs], ['final_response'])
                self.assertEqual(outputs[0]['payload']['text'], expected)
                self.assertFalse(agent._awaiting_clarification)
                self.assertFalse(agent._consumed_grants)
                self.assertEqual(len(agent.operations), 1)
                self.assertEqual(agent.operations[call['call_id']]['kind'], 'read_only')
                self.assertEqual(agent.operations[call['call_id']]['status'], 'success')
                self.assertEqual(agent.operations[call['call_id']]['result'], receipt)

    def test_supplied_details_extra_constraints_and_existing_question_disable_fallback(self):
        for slots in ({'destination': 'Porto', 'passenger_name': 'Nia'}, {'destination': 'Porto', 'depart': '06:20'},
                      {'destination': 'Porto', 'budget': 90}, {'destination': 'Lima'}, {}):
            with self.subTest(slots=slots):
                agent, call = self.agent(slots=slots)
                # Check canonical state at delivery; dispatch may synchronize known slots.
                agent.state['slots'] = deepcopy(slots)
                self.assertEqual([o['action'] for o in self.deliver(agent, call)], ['final_response'])
        agent, call = self.agent(template='Flight {flights.0.flight_id}. Which flight and passenger name should I use?')
        self.assertEqual([o['action'] for o in self.deliver(agent, call)], ['final_response'])

    def test_changed_contracts_or_noncanonical_results_disable_fallback(self):
        for name, key, value in [
            ('book_flight', 'kind', 'read_only'), ('book_flight', 'description', 'Book a flight and charge membership.'),
            ('book_flight', 'args', {**TOOLS['book_flight']['args'], 'account': {'type': 'string', 'required': True}}),
            ('flight_search', 'description', 'Search historical bookings.'),
            ('flight_search', 'conditions', 'Staff only'),
        ]:
            with self.subTest(name=name, key=key):
                tools = deepcopy(TOOLS)
                tools[name][key] = value
                agent, call = self.agent(tools=tools)
                self.assertEqual([o['action'] for o in self.deliver(agent, call)], ['final_response'])
        for result in ({'status': 'success', 'flights': []}, {'status': 'success', 'flights': [{'flight_id': 'X'}]},
                       {'status': 'success', 'flights': [{**ROWS[0], 'flight_id': None}]},
                       {'status': 'success', 'flights': ROWS, 'warning': 'Unverified availability'}):
            with self.subTest(result=result):
                agent, call = self.agent()
                self.assertEqual([o['action'] for o in self.deliver(agent, call, result)], ['final_response'])

    def test_other_operation_and_stale_result_cannot_create_question(self):
        agent, call = self.agent()
        agent._dispatch({'api_name': 'flight_search', 'args': {'destination': 'Lima'}, 'response_template': ''})
        self.drain(agent)
        self.assertEqual([o['action'] for o in self.deliver(agent, call)], ['final_response'])
        agent, call = self.agent()
        with patch.object(agent, '_start_plan'):
            agent._handle({'event_type': 'interruption', 'payload': {'text': 'Forget that.'}})
        self.drain(agent)
        self.assertEqual(self.deliver(agent, call), [])

    def test_question_latch_blocks_ready_plan_and_frame_or_manifest_resumption(self):
        agent, call = self.agent()
        self.deliver(agent, call)
        with patch.object(agent, '_start_plan') as start:
            agent._handle({'event_type': 'video_frame', 'payload': {'image_ref': 'frame.png'}})
            agent._handle({'event_type': 'tool_manifest', 'payload': {'tools': {**deepcopy(TOOLS), 'other': {
                'kind': 'read_only', 'args': {}}}}})
            start.assert_not_called()
        agent._apply({'intent': 'ignored', 'slots': {}, 'response': 'A stale ready answer.'})
        self.assertEqual(self.drain(agent), [])
        self.assertEqual(agent.state['intent'], 'book_flight')

    def test_bare_details_after_question_do_not_authorize_write(self):
        agent, call = self.agent()
        self.deliver(agent, call)
        with patch.object(agent, '_start_plan'):
            agent._handle({'event_type': 'user_speech_chunk', 'payload': {'text': 'RETURNED-A for Nia.', 'end_of_turn': True}})
        self.drain(agent)
        agent._apply({'intent': 'book_flight', 'slots': {}, 'tool_calls': [{
            'api_name': 'book_flight', 'args': {'flight_id': 'RETURNED-A', 'passenger_name': 'Nia'},
            'authorization': {'quote': 'Please book a flight to Porto.'},
            'result_bindings': {'flight_id': {'call_id': call['call_id'], 'path': 'flights.0.flight_id'}}}]})
        outputs = self.drain(agent)
        self.assertEqual([o['action'] for o in outputs], ['clarification_request'])
        self.assertFalse(any(op['kind'] == 'state_modifying' for op in agent.operations.values()))
        self.assertFalse(agent._consumed_grants)

    def test_bounded_variants_and_repeated_text_corrections(self):
        cases = [
            ([speech('Can you please reserve a flight to Porto?')], 'Porto', None),
            ([speech('Book a flight to São Paulo.')], 'São Paulo', None),
            ([speech('Book a flight to Porto on 2026-10-16.')], 'Porto', '2026-10-16'),
            ([speech('Book a flight to Porto for tomorrow.')], 'Porto', 'tomorrow'),
            ([speech('Book a flight to Lima.'), correction('Make that Dakar.'),
              correction('Wait, actually make it Porto!')], 'Porto', None),
        ]
        for events, destination, date in cases:
            with self.subTest(events=events):
                agent, call = self.agent(events, destination=destination, date=date)
                self.assertEqual([o['action'] for o in self.deliver(agent, call)], ['final_response', 'clarification_request'])

    def test_date_suffix_is_literal_bounded_and_not_an_arbitrary_name(self):
        for text, date in [('Book a flight to Porto for Nia.', 'Nia'),
                           ('Book a flight to Porto for 2026-02-30.', '2026-02-30'),
                           ('Book a flight to Porto for next Friday.', 'next Friday'),
                           ('Book a flight to Porto for Thursday.', 'Friday'),
                           ('Book a flight to Porto.', 'Friday')]:
            with self.subTest(text=text, date=date):
                agent, call = self.agent([speech(text)], date=date)
                self.assertEqual([o['action'] for o in self.deliver(agent, call)], ['final_response'])
        tools = deepcopy(TOOLS)
        tools['flight_search']['args']['date']['description'] = 'ISO date only.'
        agent, call = self.agent([speech('Book a flight to Porto for tomorrow.')], date='tomorrow', tools=tools)
        self.assertEqual([o['action'] for o in self.deliver(agent, call)], ['final_response'])

    def test_retry_counts_as_one_logical_operation(self):
        agent, call = self.agent()
        agent._result({'call_id': call['call_id'], 'api_name': call['api_name'], 'status': 'error',
                       'result': {'status': 'error', 'error': 'timeout'}})
        outputs = self.drain(agent)
        retried = [o['payload'] for o in outputs if o['action'] == 'tool_call']
        self.assertEqual(len(retried), 1)
        self.assertEqual(len(agent.operations), 2)
        self.assertEqual(len({op['operation_id'] for op in agent.operations.values()}), 1)
        self.assertEqual([o['action'] for o in self.deliver(agent, retried[0])], ['final_response', 'clarification_request'])

    def test_malformed_optional_date_metadata_is_ineligible(self):
        for description in (None, 17, {'format': 'free-form'}):
            with self.subTest(description=description):
                tools = deepcopy(TOOLS)
                tools['flight_search']['args']['date']['description'] = description
                agent, call = self.agent([speech('Book a flight to Porto for Friday.')], date='Friday', tools=tools)
                self.assertEqual([o['action'] for o in self.deliver(agent, call)], ['final_response'])
        tools = deepcopy(TOOLS)
        tools['flight_search']['args']['date']['type'] = 'number'
        agent, call = self.agent([speech('Book a flight to Porto for 17.')], date=17, tools=tools)
        self.assertEqual([o['action'] for o in self.deliver(agent, call)], ['final_response'])

    def test_any_older_write_in_accepted_correction_lineage_disables_fallback(self):
        events = [speech('Book a flight to Lima.'), correction('Make that Dakar.'), correction('Make it Porto.')]
        for status in ('pending', 'cancel_requested', 'unknown', 'success', 'error'):
            with self.subTest(status=status):
                agent, call = self.agent(events)
                # Retained ledger state is injected, including unresolved older revisions.
                prior = {**deepcopy(agent.operations[call['call_id']]), 'operation_id': 'earlier-write',
                         'call_id': 'earlier-write', 'api_name': 'book_flight', 'kind': 'state_modifying',
                         'request_start': 0, 'revision': agent.messages[0]['revision'], 'status': status}
                agent.operations['earlier-write'] = prior
                self.assertEqual([o['action'] for o in self.deliver(agent, call)], ['final_response'])
                self.assertEqual(agent.operations['earlier-write'], prior)
        agent, call = self.agent([speech('An unrelated earlier turn.'), speech('Book a flight to Porto.')])
        agent.operations['unrelated-write'] = {**deepcopy(agent.operations[call['call_id']]),
            'operation_id': 'unrelated-write', 'kind': 'state_modifying', 'status': 'unknown',
            'request_start': 0, 'revision': agent.messages[0]['revision']}
        self.assertEqual([o['action'] for o in self.deliver(agent, call)], ['final_response', 'clarification_request'])

    def test_every_current_audio_clip_needs_a_verified_attachment(self):
        observations = [
            {'message_index': 0, 'type': 'audio', 'transcript': 'Book a flight to Lima.', 'uncertain': False},
            {'message_index': 1, 'type': 'audio', 'transcript': 'Make that Porto.', 'uncertain': False}]
        for delivered in ([], observations[:1], observations[1:],
                          [{**observations[0], 'uncertain': None}, observations[1]],
                          [observations[0], {**observations[1], 'message_index': '1'}]):
            with self.subTest(observations=delivered):
                agent, call = self.agent([audio(0, False), audio(1, True)], observations=delivered)
                self.assertEqual([o['action'] for o in self.deliver(agent, call)], ['final_response'])


if __name__ == '__main__':
    unittest.main()
