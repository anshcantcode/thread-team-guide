"""Offline checks for bounded ordinary speech formatting on terminal flight reads."""
import asyncio
import hashlib
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from participant.planner import Planner, _flight_read_audio_format_agreement


MAIN = ['uh book a flight to Quito', 'Actually make that Reykjavík.']
HEARD = ['Uh book a flight to Quito.', MAIN[1]]


def context(count=2):
    return {'revision': 1, 'current_turn_start': 0, 'state': {'intent': '', 'slots': {}},
            'messages': [{'message_index': i, 'revision': 1, 'event_type': 'user_audio_chunk',
                          'payload': {'audio_ref': f'{i}.mp3', 'duration_ms': 1000,
                                      'end_of_turn': i == count - 1}} for i in range(count)],
            'tools': {'flight_search': {'kind': 'read_only',
                'description': 'Search flights to a destination city on a given date.', 'args': {
                    'destination': {'type': 'string', 'required': True,
                                    'description': 'Destination city name or airport code.'}}}}}


def observations(texts):
    return [{'message_index': i, 'type': 'audio', 'transcript': text, 'uncertain': False}
            for i, text in enumerate(texts)]


def read_decision(main, destination='Reykjavík'):
    return {'observations': main, 'intent': 'book flight', 'slots': {'destination': destination},
            'tool_calls': [{'api_name': 'flight_search', 'args': {'destination': destination},
                            'response_template': 'Option {flights.0.flight_id}.'}],
            'clarification': None, 'response': None}


def agrees(candidate=None, main=None, acoustic=None, *, destination='Reykjavík', decision=None):
    main = observations(MAIN) if main is None else main
    acoustic = observations(HEARD) if acoustic is None else acoustic
    return _flight_read_audio_format_agreement(context() if candidate is None else candidate,
        read_decision(main, destination) if decision is None else decision,
        {o['message_index']: o for o in acoustic})


class PrefixContractTests(unittest.TestCase):
    def test_leading_filler_omission_has_distinct_evidence_and_preserves_native_strings(self):
        pairs = [
            ('Uh, book a flight to Funchal.', 'Book a flight to Funchal', 'Funchal'),
            ('um find flights to Valparaíso', 'Find flights to Valparai\u0301so.', 'Valparaíso'),
            ('Um search flights to Kuopio.', 'search flights to Kuopio.', 'Kuopio'),
            ('uh, search flights to Kuopio', 'Search flights to Kuopio.', 'Kuopio'),
        ]
        for supplied, omitted, destination in pairs:
            canonical_hashes = []
            for omitted_by in ('main', 'acoustic'):
                with self.subTest(supplied=supplied, omitted_by=omitted_by):
                    main, acoustic = (omitted, supplied) if omitted_by == 'main' else (supplied, omitted)
                    candidate, planned, heard = context(1), observations([main]), observations([acoustic])
                    original = deepcopy((candidate, planned, heard))
                    result = agrees(candidate, planned, heard, destination=destination)
                    self.assertEqual(set(result), {0})
                    row = result[0]
                    self.assertEqual(row['basis'], 'leading_discourse_filler_omission')
                    self.assertEqual(row['role'], 'request')
                    self.assertEqual(row['rules'], ['leading_discourse_filler_omission'])
                    self.assertEqual(row['omitted_by'], omitted_by)
                    self.assertEqual(row['omitted_prefix'], supplied.split(' ', 1)[0])
                    self.assertEqual(row['main_sha256'], hashlib.sha256(main.encode()).hexdigest())
                    self.assertEqual(row['acoustic_sha256'], hashlib.sha256(acoustic.encode()).hexdigest())
                    canonical_hashes.append(row['canonical_sha256'])
                    self.assertEqual((candidate, planned, heard), original)
            if canonical_hashes:
                self.assertEqual(len(set(canonical_hashes)), 1)

    def test_leading_filler_omission_keeps_material_words_coverage_and_terminal_read_bounds(self):
        plain, full = 'book a flight to Funchal.', 'Uh, book a flight to Funchal.'
        pairs = [
            ('Um, book a flight to Funchal.', full),
            (plain, 'Uh uh book a flight to Funchal.'),
            (plain, 'Uh, um, book a flight to Funchal.'),
            (plain, 'Erm, book a flight to Funchal.'),
            (plain, 'Uh, please book a flight to Funchal.'),
            (plain, 'Uh, book flight to Funchal.'),
            (plain, 'Uh, do not book a flight to Funchal.'),
            (plain, 'Uh, book a flight to Funchal not Lagos.'),
            (plain, 'Uh, find flights to Funchal.'),
            (plain, 'Uh, Book a flight to Funchal.'),
            (plain, 'Uh, book a flight to funchal.'),
            (plain, 'Uh, book a flight to Portimão.'),
            (plain, 'Uh, book a flight to Funchal if refundable.'),
            (plain, 'Uh, book a flight to Funchal and reserve it.'),
            (plain, 'Uh, book a flight to "Funchal".'),
            (plain, 'Uh, book a flight to Funchal!'),
            ('I said Funchal.', 'Uh, I said Funchal.'),
            ('Actually make that Funchal.', 'Uh, actually make that Funchal.'),
        ]
        for main, acoustic in pairs:
            for reverse in (False, True):
                with self.subTest(main=main, acoustic=acoustic, reverse=reverse):
                    a, b = (acoustic, main) if reverse else (main, acoustic)
                    self.assertFalse(agrees(context(1), observations([a]), observations([b]), destination='Funchal'))
        for destination in ('uppercase Funchal', 'Funchal period', 'Literal'):
            with self.subTest(literal_destination=destination):
                self.assertFalse(agrees(context(1), observations(['book a flight to ' + destination]),
                    observations(['Uh, book a flight to ' + destination + '.']), destination=destination))

        planned = observations([plain, 'Actually make that Valparaíso.'])
        heard = observations([full, planned[1]['transcript']])
        plan = read_decision(planned, 'Valparaíso')
        for native in (0, 1):
            for index in (0, 1):
                for defect in ('uncertain', 'missing', 'duplicate', 'extra_field'):
                    with self.subTest(native=native, index=index, defect=defect):
                        bad_plan, bad_heard = deepcopy(plan), deepcopy(heard)
                        rows = (bad_plan['observations'], bad_heard)[native]
                        if defect == 'uncertain':
                            rows[index]['uncertain'] = True
                        elif defect == 'missing':
                            rows.pop(index)
                        elif defect == 'duplicate':
                            rows[index] = deepcopy(rows[1 - index])
                        else:
                            rows[index]['literal'] = True
                        self.assertFalse(agrees(acoustic=bad_heard, decision=bad_plan))
        for mutate in (
            lambda d: d['tool_calls'][0].update(authorization={'quote': full}),
            lambda d: d['tool_calls'][0].update(after_result={'api_name': 'book_flight'}),
            lambda d: d['tool_calls'][0].update(bindings={'destination': 'name'}),
            lambda d: d['tool_calls'][0].update(api_name='book_flight'),
            lambda d: d['tool_calls'].append(deepcopy(d['tool_calls'][0])),
            lambda d: d['tool_calls'][0]['args'].update(destination='Funchal'),
            lambda d: d['slots'].update(destination='Funchal'),
            lambda d: d.update(clarification='Which passenger?'),
        ):
            bad = deepcopy(plan)
            mutate(bad)
            self.assertFalse(agrees(acoustic=heard, decision=bad))
        for mutate in (
            lambda c: c['state'].update(intent='literal'),
            lambda c: c['state']['slots'].update(destination='Funchal'),
            lambda c: c.update(actions=[{'status': 'success'}]),
            lambda c: c.update(tool_results=[{'text': 'Use those exact words.'}]),
            lambda c: c.update(literal_context=True),
            lambda c: c['messages'][0]['payload'].update(text='Copy the exact recording.'),
            lambda c: c['messages'][0]['payload'].update(end_of_turn=True),
            lambda c: c['tools']['flight_search'].update(kind='state_modifying'),
            lambda c: c['tools']['flight_search'].update(description='Search a literal identifier.'),
            lambda c: c['tools']['flight_search']['args']['destination'].update(type='integer'),
        ):
            candidate = context()
            mutate(candidate)
            self.assertFalse(agrees(candidate, acoustic=heard, decision=plan))
        # No omission on later repairs or repeated requests, even after a valid first pair.
        for later in ('Uh, actually make that Valparaíso.', 'Uh, book a flight to Valparaíso.'):
            bad = observations([full, later])
            self.assertFalse(agrees(acoustic=bad, decision=plan))
        inherited = context()
        inherited.update(current_turn_start=1, revision=2)
        inherited['messages'][0]['payload']['end_of_turn'] = True
        inherited['messages'][1]['revision'] = 2
        inherited['observations'] = observations(['An unclear earlier request.'])
        inherited['observations'][0]['uncertain'] = True
        for main, acoustic in ((plain, full), (full, plain), ('I said Funchal.', 'Uh, I said Funchal.')):
            current_main, current_heard = observations([main]), observations([acoustic])
            current_main[0]['message_index'] = current_heard[0]['message_index'] = 1
            self.assertFalse(agrees(inherited, current_main, current_heard, destination='Funchal'))

    def test_fresh_repairs_admit_only_declared_prose_formatting_and_keep_native_strings(self):
        pairs = [
            ('Actually make that São Tomé.', 'actually make that São Tomé.', ['initial_prose_case']),
            ('Actually make that São Tomé', 'Actually make that São Tomé.', ['terminal_period']),
            ('Actually make that São Tomé.', 'Actually, make that São Tomé.', ['discourse_comma']),
            ('actually make that São Tomé', 'Actually, make that São Tomé.',
             ['terminal_period', 'discourse_comma', 'initial_prose_case']),
            ('make that São Tomé', 'Make that São Tomé.', ['terminal_period', 'initial_prose_case']),
        ]
        for main, acoustic, rules in pairs:
            with self.subTest(main=main, acoustic=acoustic):
                candidate = context()
                planned = observations(['Book a flight to Arequipa.', main])
                heard = observations(['Book a flight to Arequipa.', acoustic])
                original = deepcopy((candidate, planned, heard))
                result = agrees(candidate, planned, heard, destination='São Tomé')
                self.assertEqual(set(result), {1})
                self.assertEqual(result[1]['role'], 'repair')
                self.assertEqual(result[1]['rules'], rules)
                self.assertEqual(result[1]['main_sha256'], hashlib.sha256(main.encode()).hexdigest())
                self.assertEqual(result[1]['acoustic_sha256'], hashlib.sha256(acoustic.encode()).hexdigest())
                self.assertEqual((candidate, planned, heard), original)
        with self.subTest(three_clips=True):
            planned = observations(['um find flights to Arequipa', 'Actually make that São Tomé.', 'Make that Mérida.'])
            heard = observations(['Um, find flights to Arequipa.', 'actually, make that São Tomé', 'make that Me\u0301rida'])
            original = deepcopy((planned, heard))
            result = agrees(context(3), planned, heard, destination='Mérida')
            self.assertEqual(set(result), {0, 1, 2})
            self.assertEqual([result[i]['role'] for i in range(3)], ['request', 'repair', 'repair'])
            self.assertEqual((planned, heard), original)

    def test_fresh_repair_formatting_keeps_words_entities_authority_and_history_bounds(self):
        planned = observations(['Book a flight to Arequipa.', 'actually make that São Tomé'])
        heard = observations(['Book a flight to Arequipa.', 'Actually, make that São Tomé.'])
        plan = read_decision(planned, 'São Tomé')
        for text in ('Actually, make that São tomé.', 'Actually, make that Salvador.',
                     'Make that São Tomé.', 'Actually, do not make that São Tomé.',
                     'Actually, make that São Tomé if refundable.', 'Actually, make that São Tomé and reserve it.',
                     'Actually, make that "São Tomé".', 'Actually, make that São Tomé period.',
                     'Actually make, that São Tomé.', 'Actually, make that São Tomé!', 'Actually, make that São Tomé..'):
            with self.subTest(unsupported=text):
                bad = observations([heard[0]['transcript'], text])
                self.assertFalse(agrees(acoustic=bad, decision=plan))
        for extra in ({'authorization': {'quote': 'Book it'}}, {'after_result': {}}, {'bindings': {}}):
            bad = deepcopy(plan)
            bad['tool_calls'][0].update(extra)
            self.assertFalse(agrees(acoustic=heard, decision=bad))
        for mutate in (lambda d: d['tool_calls'].append(deepcopy(d['tool_calls'][0])),
                       lambda d: d['tool_calls'][0].update(api_name='book_flight'),
                       lambda d: d['tool_calls'].extend([{'api_name': 'book_flight', 'args': {}},
                                                       {'api_name': 'cancel_booking', 'args': {}}]),
                       lambda d: d['tool_calls'][0]['args'].update(destination='Arequipa'),
                       lambda d: d['slots'].update(destination='Arequipa')):
            bad = deepcopy(plan)
            mutate(bad)
            self.assertFalse(agrees(acoustic=heard, decision=bad))
        for native in (0, 1):
            for index in (0, 1):
                bad_plan, bad_heard = deepcopy(plan), deepcopy(heard)
                (bad_plan['observations'], bad_heard)[native][index]['uncertain'] = True
                self.assertFalse(agrees(acoustic=bad_heard, decision=bad_plan))
        self.assertFalse(agrees(acoustic=heard[:1], decision=plan))
        self.assertFalse(agrees(acoustic=[heard[0], heard[0]], decision=plan))
        # An exact later repair may accompany existing confirmation formatting,
        # but inherited uncertain history cannot gain the new repair policy.
        inherited = context(3)
        inherited.update(current_turn_start=1, revision=2)
        inherited['messages'][0]['payload']['end_of_turn'] = True
        for message in inherited['messages'][1:]:
            message['revision'] = 2
        inherited['observations'] = observations(['An earlier unclear request.'])
        inherited['observations'][0]['uncertain'] = True
        prior_main = observations(['I said Arequipa', 'Actually make that São Tomé.'])
        prior_heard = observations(['I said Arequipa.', 'Actually make that São Tomé.'])
        for rows in (prior_main, prior_heard):
            for row in rows:
                row['message_index'] += 1
        self.assertEqual(set(agrees(inherited, prior_main, prior_heard, destination='São Tomé')), {1})
        for text in ('actually make that São Tomé.', 'Actually make that São Tomé', 'Actually, make that São Tomé.'):
            bad = deepcopy(prior_heard)
            bad[1]['transcript'] = text
            self.assertFalse(agrees(inherited, prior_main, bad, destination='São Tomé'))
        # Even identical comma-bearing repairs retain the old inherited grammar.
        for rows in (prior_main, prior_heard):
            rows[1]['transcript'] = 'Actually, make that São Tomé.'
        self.assertFalse(agrees(inherited, prior_main, prior_heard, destination='São Tomé'))

    def test_complete_read_grammar_admits_declared_request_formatting(self):
        for main, acoustic in [('uh book a flight to Quito', 'Uh book a flight to Quito.'),
                               ('Um book a flight to Quito.', 'um book a flight to Quito'),
                               ('Uh, book a flight to Quito.', 'Uh book a flight to Quito.'),
                               ('Um, find flights to Quito', 'um find flights to Quito.'),
                               ('Book a flight to Quito.', 'book a flight to Quito.'),
                               ('book a flight to San José', 'Book a flight to San Jose\u0301.')]:
            with self.subTest(main=main, acoustic=acoustic):
                candidate, planned, heard = context(), observations([main, MAIN[1]]), observations([acoustic, HEARD[1]])
                original = deepcopy((candidate, planned, heard))
                self.assertTrue(agrees(candidate, planned, heard))
                self.assertEqual((candidate, planned, heard), original)
        self.assertTrue(agrees(context(3), observations([*MAIN, 'Make that Oslo.']),
                               observations([*HEARD, 'Make that Oslo.']), destination='Oslo'))

        for main, heard in [('Book a flight to Quito', 'Book a flight to Quito.'),
                            ('Find flights to Quito.', 'find flights to Quito'),
                            ('Search flights to Quito', 'Search flights to Quito.')]:
            with self.subTest(complete_request=main):
                self.assertTrue(agrees(context(1), observations([main]), observations([heard]), destination='Quito'))

    def test_material_words_entities_literals_and_extra_goals_stay_exact(self):
        pairs = [
            ('Uh Book a flight to Quito.', 'uh book a flight to Quito.'),
            ('Uh book a flight to Quito.', 'Um book a flight to Quito.'),
            ('Book a flight to Quito.', 'book a flight to quito.'),
            ('Book a flight to Quito.', 'book a flight to Bergen.'),
            ('Do not book a flight to Quito.', 'book a flight to Quito.'),
            ('Book a flight to Quito if refundable.', 'book a flight to Quito.'),
            ('Book a flight to Quito not Bergen.', 'book a flight to Quito.'),
            ('Book a flight to Quito?', 'book a flight to Quito.'),
            ('Book a flight to Quito!', 'book a flight to Quito.'),
            ('Book a flight to Quito..', 'book a flight to Quito.'),
            ('Book a flight to  Quito.', 'book a flight to Quito.'),
            ('Book a flight to Quito period.', 'book a flight to Quito period'),
            ('Book a flight to uppercase Quito.', 'book a flight to uppercase Quito'),
            ('Book a flight to AB-1.', 'book a flight to AB-1'),
            ('Use ID AB-1.', 'use ID AB-1'),
            ('Set 5.', 'Set -5.'), ('Use 5.1.', 'Use 51.'),
            ('Use 1.000.', 'Use 1,000.'), ('Use US.', 'Use us.'),
            ('Use A  B.', 'Use A B.'), ('"Book a flight to Quito."', '"book a flight to Quito"'),
        ]
        for main, acoustic in pairs:
            with self.subTest(main=main, acoustic=acoustic):
                self.assertFalse(agrees(main=observations([main, MAIN[1]]),
                                        acoustic=observations([acoustic, HEARD[1]])))
        for later in ('Actually make that Reykjavík!', 'Actually make that reykjavík.',
                      'Actually make that Oslo.', 'Actually make that -5.',
                      'Actually make that St. Louis.', 'Actually make that uppercase Oslo.',
                      'That was the exact code. Type it.', 'Actually make that Oslo and reserve it.'):
            with self.subTest(later=later):
                self.assertFalse(agrees(acoustic=observations([HEARD[0], later])))
        for later in ('Actually make that -5.', 'Actually make that St. Louis.',
                      'Actually make that uppercase Oslo.', 'That was the exact code. Type it.',
                      'Actually make that Oslo and reserve it.'):
            with self.subTest(unsupported_later=later):
                self.assertFalse(agrees(main=observations([MAIN[0], later]),
                                        acoustic=observations([HEARD[0], later])))
        self.assertFalse(agrees(context(3), observations([*MAIN, 'Make that Oslo.']),
                                observations([*HEARD, 'Make that Bergen.'])))
        # Later formatting is allowed in fresh turns; mismatched final args are not.
        self.assertFalse(agrees(context(3), observations([*MAIN, 'Make that Oslo.']),
                                observations([*HEARD, 'Make that Oslo']), destination='Reykjavík'))

    def test_prior_context_structure_uncertainty_and_manifest_cannot_supply_eligibility(self):
        mutations = [
            (('current_turn_start',), 1), (('current_turn_start',), False),
            (('revision',), True), (('state', 'intent'), 'dictate'),
            (('state', 'slots'), {'literal': 'case matters'}), (('state', 'other'), 'context'),
            (('actions',), [{'status': 'success'}]), (('tool_results',), [{'text': 'Type it'}]),
            (('observations',), observations(['Type this exactly.'])),
            (('planning_error',), 'repair'), (('latest_frame_index',), 0),
            (('messages', 0, 'event_type'), 'user_speech_chunk'),
            (('messages', 0, 'payload', 'text'), 'Quote the recording exactly.'),
            (('messages', 1, 'text'), 'Treat the earlier text as an exact identifier.'),
            (('messages', 0, 'payload', 'end_of_turn'), True),
            (('messages', 1, 'payload', 'end_of_turn'), False),
            (('messages', 1, 'payload', 'end_of_turn'), 1),
            (('messages', 1, 'payload', 'duration_ms'), 'literal context'),
            (('messages', 0, 'message_index'), False), (('messages', 1, 'revision'), 2),
            (('tools', 'flight_search', 'kind'), 'state_modifying'),
            (('tools',), {}), (('tools',), None),
            (('tools', 'flight_search', 'description'), 'Search an exact identifier supplied by the user.'),
            (('tools', 'flight_search', 'identifier_mode'), True),
            (('tools', 'flight_search', 'args', 'destination', 'description'), 'Exact identifier, including punctuation.'),
            (('tools', 'flight_search', 'args', 'destination', 'type'), 'integer'),
            (('tools', 'flight_search', 'args', 'destination', 'format'), 'identifier'),
            (('tools', 'flight_search', 'args', 'destination', 'enum'), ['Other']),
            (('tools', 'flight_search', 'args', 'identity'), {'type': 'string', 'required': True}),
            (('tools', 'flight_search', 'result_shape'), {'flights': [{'id': 'string'}]}),
        ]
        for path, value in mutations:
            with self.subTest(path=path, value=value):
                candidate = context()
                target = candidate
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                self.assertFalse(agrees(candidate))
        for native in (0, 1):
            for index in (0, 1):
                with self.subTest(native=native, index=index):
                    planned, heard = observations(MAIN), observations(HEARD)
                    (planned, heard)[native][index]['uncertain'] = True
                    self.assertFalse(agrees(main=planned, acoustic=heard))
        self.assertFalse(agrees(acoustic=observations(HEARD[:1])))
        self.assertFalse(agrees(main=[observations(MAIN)[0]] * 2))


    def test_confirmation_is_only_a_terminal_read_policy_and_keeps_failed_history(self):
        candidate = context()
        candidate['current_turn_start'] = 1
        candidate['revision'] = 2
        candidate['messages'][0]['payload']['end_of_turn'] = True
        candidate['messages'][1]['revision'] = 2
        # No verified prior goal is inferred from these actual retained wrong words.
        candidate['observations'] = observations(['Book of Flight 2 [cough] [throat-clearing] First'])
        candidate['observations'][0]['uncertain'] = True
        main, heard = observations(['I said Porto']), observations(['I said Porto.'])
        main[0]['message_index'] = heard[0]['message_index'] = 1
        plan = read_decision(main, 'Porto')
        original = deepcopy((candidate, plan, heard))
        admitted = agrees(candidate, acoustic=heard, decision=plan)
        self.assertEqual(admitted[1]['role'], 'confirmation')
        self.assertEqual(admitted[1]['rules'], ['terminal_period'])
        self.assertEqual(admitted[1]['main_sha256'], hashlib.sha256(b'I said Porto').hexdigest())
        self.assertEqual(admitted[1]['acoustic_sha256'], hashlib.sha256(b'I said Porto.').hexdigest())
        self.assertEqual((candidate, plan, heard), original)
        for mutate in (
            lambda d: d['tool_calls'][0]['args'].update(destination='Bergen'),
            lambda d: d['slots'].update(destination='Bergen'),
            lambda d: d['tool_calls'][0]['args'].update(date='Friday'),
            lambda d: d['slots'].update(date='Friday'),
            lambda d: d['tool_calls'][0].update(after_result={'api_name': 'book_flight', 'args': {}}),
            lambda d: d['tool_calls'][0].update(authorization={'quote': 'I said Porto'}),
            lambda d: d['tool_calls'][0].update(bindings={'destination': 'name'}),
            lambda d: d['tool_calls'][0].update(api_name='book_flight'),
            lambda d: d['tool_calls'].append(deepcopy(d['tool_calls'][0])),
        ):
            bad = deepcopy(plan)
            mutate(bad)
            self.assertFalse(agrees(candidate, acoustic=heard, decision=bad))
        for old_text in ('Repeat my next utterance.', 'Use the exact identifier.', 'Copy the next quoted words.'):
            with self.subTest(exposed_literal_history=old_text):
                bad = deepcopy(candidate)
                bad['observations'][0]['transcript'] = old_text
                self.assertFalse(agrees(bad, acoustic=heard, decision=plan))
        # Rejecting known literal instructions does not prove an unknown old goal.
        # Independent QA preserves the baseline's broader intent-selection limit.
        for value in (False, None):
            bad = deepcopy(candidate)
            bad['observations'][0]['uncertain'] = value
            self.assertFalse(agrees(bad, acoustic=heard, decision=plan))
        for text in ('I said porto.', 'I said 12.5.', 'I said Porto!', 'I said Port o.', 'I said Porto..'):
            bad = deepcopy(heard)
            bad[0]['transcript'] = text
            self.assertFalse(agrees(candidate, acoustic=bad, decision=plan))


    def test_bare_destination_requires_one_complete_acoustic_confirmation_and_exact_read(self):
        candidate = context()
        candidate['current_turn_start'], candidate['revision'] = 1, 2
        candidate['messages'][0]['payload']['end_of_turn'] = True
        candidate['messages'][1]['revision'] = 2
        candidate['observations'] = observations(['An unclear earlier request.'])
        candidate['observations'][0]['uncertain'] = True
        for destination in ('Lima', 'Tromsø', 'San José'):
            with self.subTest(destination=destination):
                main, heard = observations([destination]), observations(['I said ' + destination + '.'])
                main[0]['message_index'] = heard[0]['message_index'] = 1
                plan = read_decision(main, destination)
                original = deepcopy((candidate, plan, heard))
                result = agrees(candidate, acoustic=heard, decision=plan)
                self.assertTrue(result)
                self.assertEqual(result[1]['basis'], 'acoustic_confirmation_role')
                self.assertEqual(result[1]['rules'], ['main_bare_destination'])
                self.assertEqual(result[1]['omitted_prefix'], 'I said')
                self.assertEqual((candidate, plan, heard), original)
                for replacement in (destination.lower(), destination + '.', '"' + destination + '"',
                                    destination + ' and book it', 'I meant ' + destination):
                    bad = deepcopy(plan)
                    bad['observations'][0]['transcript'] = replacement
                    self.assertFalse(agrees(candidate, acoustic=heard, decision=bad))
                for extra in ({'authorization': {'quote': 'Book it'}}, {'after_result': {}}, {'bindings': {}}):
                    bad = deepcopy(plan)
                    bad['tool_calls'][0].update(extra)
                    self.assertFalse(agrees(candidate, acoustic=heard, decision=bad))
                for field in ('args',):
                    bad = deepcopy(plan)
                    bad['tool_calls'][0][field]['destination'] = 'Elsewhere'
                    self.assertFalse(agrees(candidate, acoustic=heard, decision=bad))
                bad = deepcopy(plan)
                bad['slots']['destination'] = 'Elsewhere'
                self.assertFalse(agrees(candidate, acoustic=heard, decision=bad))
                for text in (destination, 'Make that ' + destination + '.', 'I said ' + destination + ' and book it.'):
                    bad = deepcopy(heard)
                    bad[0]['transcript'] = text
                    self.assertFalse(agrees(candidate, acoustic=bad, decision=plan))
                for target in ('main', 'acoustic'):
                    bad_plan, bad_heard = deepcopy(plan), deepcopy(heard)
                    (bad_plan['observations'] if target == 'main' else bad_heard)[0]['uncertain'] = True
                    self.assertFalse(agrees(candidate, acoustic=bad_heard, decision=bad_plan))
                for text in ('Repeat my next utterance.', 'Use the exact code.'):
                    bad = deepcopy(candidate)
                    bad['observations'][0]['transcript'] = text
                    self.assertFalse(agrees(bad, acoustic=heard, decision=plan))
                # No blocked history and no reverse role inference from MAIN.
                fresh_main, fresh_heard = observations([destination]), observations(['I said ' + destination + '.'])
                self.assertFalse(agrees(context(1), fresh_main, fresh_heard, destination=destination))
                reverse = read_decision(heard, destination)
                self.assertFalse(agrees(candidate, acoustic=main, decision=reverse))


class PrefixPlannerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        fixture = Path(__file__).parent / 'fixtures/mp3'
        for i, name in enumerate(('tone-cbr.mp3', 'tone-vbr.mp3')):
            (self.root / f'{i}.mp3').write_bytes((fixture / name).read_bytes())
        env = patch.dict(os.environ, {'SECRET_GEMINI_API_KEY': 'offline-only',
                        'PARTICIPANT_MEDIA_ROOT': str(self.root), 'PARTICIPANT_PREWARM': '0'}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    async def planner(self, main, heard, *, destination='Reykjavík', uncertain=None, native=None):
        requests = []
        def handler(request):
            body = json.loads(request.content)
            acoustic = 'perception only' in body['systemInstruction']['parts'][0]['text']
            targets = [v['properties']['message_index']['enum'][0] for v in
                       body['generationConfig']['responseJsonSchema']['properties']['observations']['items']['anyOf']]
            requests.append((acoustic, targets))
            rows = observations(heard if acoustic else main)
            for row in rows:
                row['uncertain'] = (acoustic, row['message_index']) == uncertain
            reply = {'observations': [row for row in rows if row['message_index'] in targets]}
            if not acoustic:
                reply.update(intent='book flight', slots={'destination': destination}, clarification=None, response=None,
                             tool_calls=[{'api_name': 'flight_search', 'args': {'destination': destination},
                                          'response_template': 'Option {flights.0.flight_id}.'}])
            if native is not None:
                native.append(deepcopy(reply))
            return httpx.Response(200, json={'candidates': [{'finishReason': 'STOP',
                                  'content': {'parts': [{'text': json.dumps(reply)}]}}]})
        planner = Planner(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(planner.close)
        await planner.setup()
        return planner, requests

    async def test_leading_filler_policy_keeps_native_records_and_vetoes_in_both_completion_orders(self):
        repair = 'Actually make that Valparaíso.'
        cases = [
            (['book a flight to Funchal'], ['Uh, book a flight to Funchal.'], 'Funchal', 'omission'),
            (['Um search flights to Kuopio.'], ['Search flights to Kuopio'], 'Kuopio', 'omission'),
            (['find flights to Funchal', 'actually make that Valparai\u0301so'],
             ['Um, find flights to Funchal.', 'Actually, make that Valparaíso.'], 'Valparaíso', 'omission'),
            (['uh book a flight to Funchal', repair], ['Book a flight to Funchal.', repair], 'Valparaíso', 'omission'),
            (['um find flights to Funchal'], ['Um, find flights to Funchal.'], 'Funchal', 'format'),
            (['Book a flight to Funchal.'], ['Book a flight to Funchal.'], 'Funchal', 'exact'),
            (['Uh, book a flight to Funchal.'], ['Um, book a flight to Funchal.'], 'Funchal', 'blocked'),
            (['book a flight to Funchal.'], ['Uh, please book a flight to Funchal.'], 'Funchal', 'blocked'),
            (['book a flight to Funchal.', repair], ['Uh, book a flight to Kuopio.', repair], 'Valparaíso', 'blocked'),
            (['book a flight to Funchal.', repair],
             ['Uh, book a flight to Funchal.', 'Make that Valparaíso.'], 'Valparaíso', 'blocked'),
            (['book a flight to Funchal.'], ['Uh, book a flight to Funchal.'], 'Kuopio', 'blocked'),
        ]
        for main, heard, destination, expected in cases:
            for main_first in (False, True):
                with self.subTest(main=main, heard=heard, destination=destination, main_first=main_first):
                    native = []
                    planner, requests = await self.planner(main, heard, destination=destination, native=native)
                    candidate = context(len(main))
                    original = deepcopy(candidate)
                    main_done, audio_done, completed = asyncio.Event(), asyncio.Event(), []
                    decide, listen = planner._decide, planner._current_audio
                    async def ordered_main(*args):
                        if not main_first:
                            await audio_done.wait()
                        result = await decide(*args)
                        completed.append('main')
                        main_done.set()
                        return result
                    async def ordered_audio(*args):
                        if main_first:
                            await main_done.wait()
                        result = await listen(*args)
                        completed.append('audio')
                        audio_done.set()
                        return result
                    with patch.object(planner, '_decide', ordered_main), patch.object(planner, '_current_audio', ordered_audio):
                        result = await asyncio.wait_for(planner.plan(candidate), 1)
                    self.assertEqual(completed, ['main', 'audio'] if main_first else ['audio', 'main'])
                    self.assertEqual(candidate, original)
                    self.assertEqual(sorted(requests), [(False, list(range(len(main)))), (True, list(range(len(main))))])
                    self.assertEqual([row['observations'] for row in native],
                        [observations(texts) for texts in ((main, heard) if main_first else (heard, main))])
                    audit = planner.evidence[-1]
                    if expected == 'blocked':
                        self.assertEqual(result['tool_calls'], [])
                        self.assertTrue(result['clarification'])
                        self.assertTrue(any(row['uncertain'] for row in result['observations']))
                        self.assertIn(0, audit['audio_transcript_conflicts'])
                    else:
                        self.assertEqual(result['tool_calls'], read_decision([], destination)['tool_calls'])
                        self.assertEqual(result['slots'], {'destination': destination})
                        self.assertEqual(result['observations'], observations(heard))
                        self.assertIsNone(result['clarification'])
                        self.assertNotIn('audio_transcript_conflicts', audit)
                    if expected == 'omission':
                        rows = audit['audio_filler_omission_equivalence']
                        self.assertEqual(len(rows), 1)
                        self.assertEqual(rows[0]['message_index'], 0)
                        self.assertEqual(rows[0]['rules'], ['leading_discourse_filler_omission'])
                        self.assertEqual(rows[0]['main_sha256'], hashlib.sha256(main[0].encode()).hexdigest())
                        self.assertEqual(rows[0]['acoustic_sha256'], hashlib.sha256(heard[0].encode()).hexdigest())
                        self.assertTrue(all(row['message_index'] > 0 for row in audit.get('audio_format_equivalence', [])))
                    else:
                        self.assertNotIn('audio_filler_omission_equivalence', audit)
                    if expected == 'format':
                        self.assertEqual([row['message_index'] for row in audit['audio_format_equivalence']], [0])
                    if expected in ('exact', 'blocked'):
                        self.assertNotIn('audio_format_equivalence', audit)
                    self.assertNotIn('audio_confirmation_role_equivalence', audit)
                    self.assertEqual([row['transcript'] for row in planner._audio_cache.values()], heard)
                    await planner.close()
                    self.assertEqual(planner._pending_tasks, set())
                    self.assertIsNone(planner.client)

    async def test_fresh_formatted_repair_passes_both_completion_orders_without_rewriting_native_evidence(self):
        main = ['uh book a flight to Arequipa', 'actually make that São Tomé']
        heard = ['Uh, book a flight to Arequipa.', 'Actually, make that São Tomé.']
        for main_first in (False, True):
            with self.subTest(main_first=main_first):
                native = []
                planner, requests = await self.planner(main, heard, destination='São Tomé', native=native)
                candidate = context()
                original = deepcopy(candidate)
                planner.observe_input(candidate['messages'][0], 0)
                main_done, audio_done = asyncio.Event(), asyncio.Event()
                decide, listen = planner._decide, planner._current_audio
                async def ordered_main(*args):
                    if not main_first:
                        await audio_done.wait()
                    result = await decide(*args)
                    main_done.set()
                    return result
                async def ordered_audio(*args):
                    if main_first:
                        await main_done.wait()
                    result = await listen(*args)
                    audio_done.set()
                    return result
                with patch.object(planner, '_decide', ordered_main), patch.object(planner, '_current_audio', ordered_audio):
                    result = await asyncio.wait_for(planner.plan(candidate), 1)
                self.assertEqual(result['tool_calls'], read_decision([], 'São Tomé')['tool_calls'])
                self.assertEqual(result['slots'], {'destination': 'São Tomé'})
                self.assertEqual(result['observations'], observations(heard))
                self.assertEqual(candidate, original)
                self.assertEqual(sorted(requests), [(False, [0, 1]), (True, [0, 1])])
                admitted = planner.evidence[-1]['audio_format_equivalence']
                self.assertEqual([(row['message_index'], row['role']) for row in admitted], [(0, 'request'), (1, 'repair')])
                for index, row in enumerate(admitted):
                    self.assertEqual(row['rules'], ['terminal_period', 'discourse_comma', 'initial_prose_case'])
                    self.assertEqual(row['main_sha256'], hashlib.sha256(main[index].encode()).hexdigest())
                    self.assertEqual(row['acoustic_sha256'], hashlib.sha256(heard[index].encode()).hexdigest())
                self.assertNotIn('audio_transcript_conflicts', planner.evidence[-1])
                self.assertNotIn('audio_confirmation_role_equivalence', planner.evidence[-1])
                self.assertEqual([row['observations'] for row in native],
                                 [observations(texts) for texts in ((main, heard) if main_first else (heard, main))])
                self.assertEqual([row['transcript'] for row in planner._audio_cache.values()], heard)
                await planner.close()
                self.assertEqual(planner._pending_tasks, set())
                self.assertIsNone(planner.client)

    async def test_both_completion_orders_preserve_native_records_and_selected_destination(self):
        for main_first, prefix in ((False, MAIN[0]), (True, MAIN[0]),
                                   (False, 'Uh, book a flight to Quito.'), (True, 'Uh, book a flight to Quito.')):
            with self.subTest(main_first=main_first, prefix=prefix):
                planner, requests = await self.planner([prefix, MAIN[1]], HEARD)
                candidate = context()
                original_context = deepcopy(candidate)
                planner.observe_input(candidate['messages'][0], 0)
                await asyncio.sleep(0)
                self.assertEqual(requests, [])
                self.assertEqual(planner._audio_jobs, {})
                self.assertEqual(planner._audio_cache, {})
                main_done, audio_done, completed = asyncio.Event(), asyncio.Event(), []
                decide, listen = planner._decide, planner._current_audio
                async def ordered_main(*args):
                    if not main_first:
                        await audio_done.wait()
                    result = await decide(*args)
                    completed.append('main')
                    main_done.set()
                    return result
                async def ordered_audio(*args):
                    if main_first:
                        await main_done.wait()
                    result = await listen(*args)
                    completed.append('audio')
                    audio_done.set()
                    return result
                with patch.object(planner, '_decide', ordered_main), patch.object(planner, '_current_audio', ordered_audio):
                    result = await asyncio.wait_for(planner.plan(candidate), 1)
                self.assertEqual(completed, ['main', 'audio'] if main_first else ['audio', 'main'])
                self.assertEqual(result['observations'], observations(HEARD))
                self.assertEqual(result['slots'], {'destination': 'Reykjavík'})
                self.assertEqual(result['tool_calls'], [{'api_name': 'flight_search', 'args': {'destination': 'Reykjavík'},
                                                        'response_template': 'Option {flights.0.flight_id}.'}])
                self.assertEqual(candidate, original_context)
                self.assertEqual(len(requests), 2)
                self.assertEqual(sorted(requests), [(False, [0, 1]), (True, [0, 1])])
                admitted = planner.evidence[-1]['audio_format_equivalence']
                self.assertEqual([row['message_index'] for row in admitted], [0])
                self.assertEqual(admitted[0]['role'], 'request')
                self.assertEqual(admitted[0]['main_sha256'], hashlib.sha256(prefix.encode()).hexdigest())
                self.assertEqual(admitted[0]['acoustic_sha256'], hashlib.sha256(HEARD[0].encode()).hexdigest())
                self.assertNotIn('audio_transcript_conflicts', planner.evidence[-1])
                self.assertEqual([row['transcript'] for row in planner._audio_cache.values()], HEARD)
                await planner.close()
                self.assertEqual(planner._pending_tasks, set())
                self.assertEqual(planner._audio_cache, {})
                self.assertIsNone(planner.client)

    async def test_real_retained_word_conflict_changed_entity_and_unsupported_punctuation_still_veto(self):
        # First pair is actual retained pub05r2 native output, replayed only offline.
        cases = [(['Book a flight to [cough] Boston.'],
                  ['Book of Flight 2 [cough] [throat-clearing] First'], 'Boston'),
                 (['Find flights to Quito.'], ['Find flights to Bergen.'], 'Quito'),
                 (MAIN, [HEARD[0], 'Actually make that Reykjavík!'], 'Reykjavík')]
        for main, heard, destination in cases:
            with self.subTest(main=main, heard=heard):
                planner, requests = await self.planner(main, heard, destination=destination)
                result = await planner.plan(context(len(main)))
                self.assertEqual(result['tool_calls'], [])
                self.assertTrue(result['clarification'])
                self.assertTrue(any(row['uncertain'] for row in result['observations']))
                self.assertNotIn('audio_format_equivalence', planner.evidence[-1])
                self.assertEqual(len(requests), 2)
                await planner.close()
                self.assertEqual(planner._pending_tasks, set())


    async def test_bare_confirmation_preserves_failed_history_and_has_a_separate_trace(self):
        native = []
        def handler(request):
            body = json.loads(request.content)
            acoustic = 'perception only' in body['systemInstruction']['parts'][0]['text']
            variants = body['generationConfig']['responseJsonSchema']['properties']['observations']['items']['anyOf']
            targets = [v['properties']['message_index']['enum'][0] for v in variants]
            self.assertIn(targets, ([0], [1]))
            index = targets[0]
            text = (('Book of Flight 2 [cough] [throat-clearing] First' if acoustic
                     else 'Book a flight to [cough] Cuenca.') if index == 0
                    else ('I said Arusha.' if acoustic else 'Arusha'))
            row = {'message_index': index, 'type': 'audio', 'transcript': text, 'uncertain': False}
            reply = {'observations': [row]} if acoustic else read_decision([row], 'Cuenca' if index == 0 else 'Arusha')
            native.append(deepcopy(reply))
            return httpx.Response(200, json={'candidates': [{'finishReason': 'STOP',
                                  'content': {'parts': [{'text': json.dumps(reply)}]}}]})
        planner = Planner(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(planner.close)
        await planner.setup()
        initial = await planner.plan(context(1))
        self.assertEqual(initial['tool_calls'], [])
        self.assertTrue(initial['observations'][0]['uncertain'])
        prior_cache = deepcopy(planner._audio_cache)
        self.assertTrue(all(row['uncertain'] for row in prior_cache.values()))
        current = context()
        current['current_turn_start'], current['revision'] = 1, 2
        current['messages'][0]['payload']['end_of_turn'] = True
        current['messages'][1]['revision'] = 2
        current['observations'] = deepcopy(initial['observations'])
        original = deepcopy(current)
        planner.observe_input(current['messages'][1], 1)
        result = await planner.plan(current)
        self.assertEqual(result['tool_calls'], read_decision([], 'Arusha')['tool_calls'])
        self.assertEqual(result['observations'], [{'message_index': 1, 'type': 'audio',
                         'transcript': 'I said Arusha.', 'uncertain': False}])
        self.assertEqual(current, original)
        for key, value in prior_cache.items():
            self.assertEqual(planner._audio_cache[key], value)
        admitted = planner.evidence[-1]['audio_confirmation_role_equivalence']
        self.assertNotIn('audio_format_equivalence', planner.evidence[-1])
        self.assertNotIn('audio_transcript_conflicts', planner.evidence[-1])
        self.assertEqual(admitted[0]['rules'], ['main_bare_destination'])
        self.assertEqual(admitted[0]['main_sha256'], hashlib.sha256(b'Arusha').hexdigest())
        self.assertEqual(admitted[0]['acoustic_sha256'], hashlib.sha256(b'I said Arusha.').hexdigest())
        self.assertEqual(len(native), 4)
        self.assertEqual({r['observations'][0]['transcript'] for r in native[-2:]}, {'Arusha', 'I said Arusha.'})
        await planner.close()
        self.assertEqual(planner._pending_tasks, set())
        self.assertIsNone(planner.client)

    async def test_native_uncertainty_still_vetoes_an_otherwise_supported_dialogue(self):
        for acoustic in (False, True):
            with self.subTest(acoustic=acoustic):
                planner, _ = await self.planner(MAIN, HEARD, uncertain=(acoustic, 1))
                result = await planner.plan(context())
                self.assertEqual(result['tool_calls'], [])
                self.assertTrue(result['clarification'])
                self.assertNotIn('audio_format_equivalence', planner.evidence[-1])
                self.assertTrue(all(row['uncertain'] for row in planner._audio_cache.values()))
                await planner.close()
                self.assertEqual(planner._pending_tasks, set())


if __name__ == '__main__':
    unittest.main()
