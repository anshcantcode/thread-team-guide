"""Mocked native requests exercise joint reads and later independent write gates."""
import asyncio
import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from participant.agent import ParticipantAgent
from participant.planner import Planner, PlannerError
from tests.test_participant_flight_booking import TOOLS as FLIGHT_TOOLS


FLAG = '_audio_joint_only'
TEXTS = ['Find routes to Faro.', 'Actually make that Salta.']
COMMAND = 'Set the label to Harbor.'
TOOLS = {
    'lookup_route': {'kind': 'read_only', 'description': 'Find routes to a city.', 'args': {
        'destination': {'type': 'string', 'required': True}}},
    'set_label': {'kind': 'state_modifying', 'description': 'Set a display label.', 'args': {
        'label': {'type': 'string', 'required': True}}},
}


def rows(texts=TEXTS):
    return [{'message_index': i, 'type': 'audio', 'transcript': text, 'uncertain': False}
            for i, text in enumerate(texts)]


def proposal(observations=None, *, write=False):
    call = ({'api_name': 'set_label', 'args': {'label': 'Harbor'},
             'authorization': {'quote': COMMAND}, 'response_template': 'Label {label}.'} if write else
            {'api_name': 'lookup_route', 'args': {'destination': 'Salta'}, 'response_template': 'Routes {routes}.'})
    return {'observations': rows() if observations is None else observations, 'intent': 'set_label' if write else 'find_routes',
            'slots': deepcopy(call['args']), 'tool_calls': [call], 'response': None, 'clarification': None}


class SingleCallAudioTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        fixtures = Path(__file__).parent / 'fixtures/mp3'
        self.clips = [(fixtures / name).read_bytes() for name in ('tone-cbr.mp3', 'tone-vbr.mp3', 'tone-cbr.mp3')]
        self.restore_clips()
        environment = patch.dict(os.environ, {'SECRET_GEMINI_API_KEY': 'offline-only',
            'PARTICIPANT_MEDIA_ROOT': str(self.root), 'PARTICIPANT_PREWARM': '0',
            'PARTICIPANT_IMAGE_EMBEDDING': '0'}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def restore_clips(self):
        for index, raw in enumerate(self.clips):
            (self.root / f'{index}.mp3').write_bytes(raw)

    async def planner(self, script=None, *, mode='single_call_reads', hook=None):
        script = script if script is not None else {'main': proposal(), 'heard': rows()}
        requests, native = [], []
        async def handle(request):
            body = json.loads(request.content)
            acoustic = 'perception only' in body['systemInstruction']['parts'][0]['text']
            variants = body['generationConfig']['responseJsonSchema']['properties']['observations']['items'].get('anyOf', [])
            targets = [item['properties']['message_index']['enum'][0] for item in variants]
            requests.append({'acoustic': acoustic, 'targets': targets, 'body': body, 'wire': request.content})
            reply = {'observations': deepcopy(script['heard'])} if acoustic else deepcopy(script['main'])
            reply['observations'] = [row for row in reply['observations'] if row['message_index'] in targets]
            if hook is not None:
                reply = await hook(acoustic, body, reply)
            if isinstance(reply, httpx.Response):
                return reply
            native.append(deepcopy(reply))
            return httpx.Response(200, json={'candidates': [{'finishReason': 'STOP',
                'content': {'parts': [{'text': json.dumps(reply)}]}}]})
        if mode is None:
            os.environ.pop('PARTICIPANT_AUDIO_MODE', None)
        else:
            os.environ['PARTICIPANT_AUDIO_MODE'] = mode
        planner = Planner(transport=httpx.MockTransport(handle))
        self.addAsyncCleanup(planner.close)
        await planner.setup()
        return planner, requests, native, script

    def agent(self, planner, *, tools=TOOLS):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue(), planner=planner)
        with patch.object(agent, '_start_plan'):
            agent._handle({'event_type': 'tool_manifest', 'payload': {'tools': deepcopy(tools)}})
            for index in range(2):
                agent._handle({'event_type': 'user_audio_chunk', 'payload': {
                    'audio_ref': f'{index}.mp3', 'end_of_turn': index == 1}})
        self.drain(agent)
        return agent

    @staticmethod
    def drain(agent):
        events = []
        while not agent.out_queue.empty():
            events.append(agent.out_queue.get_nowait())
        return events

    def advance(self, agent, *, audio=False):
        with patch.object(agent, '_start_plan'):
            agent._handle({'event_type': 'user_audio_chunk' if audio else 'user_speech_chunk', 'payload': {
                **({'audio_ref': '2.mp3'} if audio else {'text': COMMAND}), 'end_of_turn': True}})
        self.drain(agent)

    async def apply_plan(self, agent):
        revision, result = await agent._plan(agent._context(), agent.revision)
        self.assertEqual(revision, agent.revision)
        agent._apply(result)
        return result, self.drain(agent)

    def raw_clips(self, request):
        return [base64.b64decode(part['inlineData']['data']) for part in request['body']['contents'][0]['parts']
                if 'inlineData' in part]

    async def test_temperature_and_evidence_match_model_family_on_both_audio_modes(self):
        for model, temperature in (('gemini-3.5-flash-lite', 1.0), ('gemini-2.5-flash', 0)):
            for mode in (None, 'single_call_reads'):
                with self.subTest(model=model, mode=mode):
                    os.environ['PARTICIPANT_MODEL'] = model
                    arrived, release = asyncio.Event(), asyncio.Event()
                    async def hold_verification(acoustic, body, reply):
                        if mode == 'single_call_reads' and acoustic:
                            arrived.set()
                            await release.wait()
                        return reply
                    planner, requests, _, script = await self.planner(mode=mode, hook=hold_verification)
                    agent = self.agent(planner)
                    await self.apply_plan(agent)
                    self.assertEqual(planner.audio_mode, mode or 'independent')
                    self.assertEqual([r['acoustic'] for r in requests], [False] if mode else [False, True])
                    self.advance(agent)
                    script['main'] = proposal(write=True)
                    if mode:
                        task = asyncio.create_task(self.apply_plan(agent))
                        try:
                            await asyncio.wait_for(arrived.wait(), .7)
                            self.assertEqual(planner._audio_cache, {})
                            self.assertTrue(all(FLAG in row for row in agent.observations.values()))
                            self.assertFalse(agent._consumed_grants)
                        finally:
                            release.set()
                        result, events = await task
                        self.assertEqual([r['acoustic'] for r in requests], [False, False, True])
                        self.assertEqual(self.raw_clips(requests[1]), self.clips[:2])
                        self.assertEqual(self.raw_clips(requests[2]), self.clips[:2])
                    else:
                        result, events = await self.apply_plan(agent)
                    self.assertTrue(all(FLAG not in row for row in result['observations']))
                    self.assertTrue(any(event['action'] == 'tool_call' for event in events))
                    self.assertEqual(len(planner._audio_cache), 2)
                    for request in requests:
                        config = request['body']['generationConfig']
                        self.assertEqual(config['temperature'], temperature)
                        self.assertIs(type(config['temperature']), type(temperature))
                        self.assertEqual(config['maxOutputTokens'], 500 if request['acoustic'] else 1500)
                    records = [r for r in planner.evidence if r['phase'] in ('planning', 'acoustic')]
                    self.assertEqual(len(records), len(requests))
                    self.assertTrue(all(record['temperature'] == temperature for record in records))
                    await planner.close()

    async def test_temperature_evidence_survives_main_and_deferred_acoustic_timeouts(self):
        for model, temperature in (('gemini-3.5-flash-lite', 1.0), ('gemini-2.5-flash', 0)):
            with self.subTest(model=model):
                os.environ['PARTICIPANT_MODEL'] = model
                async def fail(acoustic, body, reply):
                    if len(requests) == 1 or acoustic:
                        raise httpx.ReadTimeout('offline timeout')
                    return reply
                planner, requests, _, script = await self.planner(hook=fail)
                agent = self.agent(planner)
                result, events = await self.apply_plan(agent)
                self.assertTrue(result['clarification'])
                self.assertFalse(any(event['action'] == 'tool_call' for event in events))
                self.advance(agent)
                script['main'] = proposal(write=True)
                result, events = await self.apply_plan(agent)
                self.assertTrue(result['clarification'])
                self.assertFalse(any(event['action'] == 'tool_call' for event in events))
                self.assertEqual([r['acoustic'] for r in requests], [False, False, True])
                self.assertEqual(planner._audio_cache, {})
                self.assertEqual(agent.observations, {})
                self.assertTrue(all(request['body']['generationConfig']['temperature'] == temperature for request in requests))
                self.assertTrue(all(record['temperature'] == temperature for record in planner.evidence))
                self.assertEqual([(record['phase'], record['status']) for record in planner.evidence],
                                 [('planning', 'timeout'), ('acoustic', 'timeout'), ('planning', 'acoustic_unverified')])
                await planner.close()

    async def test_default_body_and_independent_behavior_are_unchanged(self):
        captures = []
        for mode in (None, 'independent', 'single_call_reads'):
            planner, requests, native, _ = await self.planner(mode=mode)
            agent = self.agent(planner)
            result, _ = await self.apply_plan(agent)
            captures.append(next(request['wire'] for request in requests if not request['acoustic']))
            self.assertEqual(len(requests), 1 if mode == 'single_call_reads' else 2)
            self.assertEqual([row['transcript'] for row in result['observations']], TEXTS)
            self.assertEqual(len(planner._audio_cache), 0 if mode == 'single_call_reads' else 2)
            self.assertEqual(planner.evidence[-1]['audio_mode'], mode or 'independent')
            if mode != 'single_call_reads':
                self.assertTrue(all(FLAG not in row for row in result['observations']))
                self.assertEqual(native[0]['observations'], rows())
            await planner.close()
        self.assertEqual(captures, [captures[0]] * 3)

    async def test_one_native_call_keeps_raw_sources_and_labels_read_or_no_effect(self):
        for outcome in ('read', 'answer', 'clarification', 'uncertain'):
            with self.subTest(outcome=outcome):
                plan = proposal()
                if outcome in ('answer', 'clarification'):
                    plan.update(tool_calls=[], response='Here is the route overview.' if outcome == 'answer' else None,
                                clarification='Which day?' if outcome == 'clarification' else None)
                if outcome == 'uncertain':
                    plan['observations'][1]['uncertain'] = True
                script = {'main': plan, 'heard': rows()}
                planner, requests, native, _ = await self.planner(script)
                agent = self.agent(planner)
                result, events = await self.apply_plan(agent)
                self.assertEqual(len(requests), 1)
                self.assertEqual(requests[0]['targets'], [0, 1])
                self.assertEqual(self.raw_clips(requests[0]), self.clips[:2])
                self.assertEqual(native, [plan])
                self.assertEqual(planner.evidence[-1]['native_audio_observations'], plan['observations'])
                self.assertEqual(planner.evidence[-1]['native_audio_sha256'],
                    {i: hashlib.sha256(text.encode()).hexdigest() for i, text in enumerate(TEXTS)})
                self.assertEqual([row[FLAG] for row in result['observations']], [
                    (i, 1, 'audio/mpeg', hashlib.sha256(self.clips[i]).hexdigest()) for i in range(2)])
                self.assertEqual(planner._audio_cache, {})
                self.assertEqual(agent._user_texts(), [])
                expected = 'joint_read' if outcome == 'read' else 'blocked' if outcome == 'uncertain' else 'joint_no_effect'
                self.assertEqual(planner.evidence[-1]['audio_admission'], expected)
                if outcome == 'uncertain':
                    self.assertEqual(result['tool_calls'], [])
                    self.assertTrue(result['clarification'])
                    self.assertFalse(any(event['action'] == 'tool_call' for event in events))
                await planner.close()

    async def test_native_flags_cannot_forge_provenance_or_authorize_a_write(self):
        for forged in (False, True, 'false'):
            with self.subTest(forged=forged):
                main = proposal(rows([COMMAND, COMMAND]))
                for row in main['observations']:
                    row[FLAG] = forged
                planner, requests, native, _ = await self.planner({'main': main, 'heard': rows([COMMAND, COMMAND])})
                agent = self.agent(planner)
                result, _ = await self.apply_plan(agent)
                self.assertTrue(all(isinstance(row[FLAG], tuple) and len(row[FLAG]) == 4 for row in result['observations']))
                self.assertEqual(native[0], main)
                self.assertEqual(agent._user_texts(), [])
                agent._dispatch(proposal(write=True)['tool_calls'][0])
                self.assertFalse(any(event['action'] == 'tool_call' for event in self.drain(agent)))
                self.assertFalse(agent._consumed_grants)
                self.assertEqual(planner._audio_cache, {})
                self.assertEqual(len(requests), 1)
                await planner.close()

    async def test_joint_booking_question_uses_actual_read_result_without_authority(self):
        main = proposal(rows(['Book a flight to Faro.', 'Actually make that Salta.']))
        main.update(intent='search_flights', slots={'destination': 'Salta'}, tool_calls=[{
            'api_name': 'flight_search', 'args': {'destination': 'Salta'}, 'response_template': 'Flight {flights.0.flight_id}.'}])
        planner, requests, _, _ = await self.planner({'main': main, 'heard': []})
        agent = self.agent(planner, tools=FLIGHT_TOOLS)
        _, events = await self.apply_plan(agent)
        call = next(event['payload'] for event in events if event['action'] == 'tool_call')
        self.assertFalse(any(event['action'] == 'clarification_request' for event in events))
        agent._result({'call_id': call['call_id'], 'api_name': 'flight_search', 'status': 'success', 'result': {
            'status': 'success', 'flights': [{'flight_id': 'ACTUAL-S', 'depart': '09:25', 'price_usd': 117}]}})
        outputs = self.drain(agent)
        self.assertEqual([event['action'] for event in outputs], ['final_response', 'clarification_request'])
        self.assertIn('ACTUAL-S', outputs[0]['payload']['text'])
        self.assertIn('passenger name', outputs[1]['payload']['text'])
        self.assertEqual(agent.state['intent'], 'book_flight')
        self.assertEqual(agent._user_texts(), [])
        self.assertFalse(agent._consumed_grants)
        self.assertEqual(planner._audio_cache, {})
        self.assertEqual(len(requests), 1)

    async def test_marker_capture_roundtrip_and_missing_or_falsy_values_never_grant_authority(self):
        for marker in ('missing', None, False, True, [], [0, True, 'audio/mpeg', '0' * 64]):
            with self.subTest(marker=marker):
                planner, requests, _, script = await self.planner()
                agent = self.agent(planner)
                result, _ = await self.apply_plan(agent)
                captured = json.loads(json.dumps(result))
                self.assertIsInstance(captured['observations'][0][FLAG], list)
                agent._apply(captured)
                self.drain(agent)
                self.assertEqual(agent._user_texts(), [])
                original = deepcopy(agent.observations)
                malformed = deepcopy(captured)
                if marker == 'missing':
                    malformed['observations'][0].pop(FLAG)
                else:
                    malformed['observations'][0][FLAG] = marker
                agent._apply(malformed)
                self.assertEqual(agent.observations, original)
                self.assertFalse(any(event['action'] == 'tool_call' for event in self.drain(agent)))
                # Corrupt retained state independently of the rejected replacement.
                agent.observations[0] = malformed['observations'][0]
                self.assertEqual(agent._user_texts(), [])
                self.advance(agent)
                script['main'] = proposal(write=True)
                result, events = await self.apply_plan(agent)
                self.assertTrue(result.get('clarification'))
                self.assertFalse(any(event['action'] == 'tool_call' for event in events))
                self.assertEqual(len(requests), 1)
                self.assertEqual(planner._audio_cache, {})
                await planner.close()

    async def test_later_text_and_audio_writes_verify_all_raw_history_before_promotion(self):
        for audio in (False, True):
            with self.subTest(audio=audio):
                planner, requests, _, script = await self.planner()
                agent = self.agent(planner)
                await self.apply_plan(agent)
                joint = deepcopy(agent.observations)
                self.advance(agent, audio=audio)
                texts = [*TEXTS, COMMAND] if audio else TEXTS
                script.update(main=proposal(rows(texts), write=True), heard=rows(texts))
                result, events = await self.apply_plan(agent)
                expected = list(range(len(texts)))
                self.assertEqual([r['acoustic'] for r in requests], [False, False, True])
                self.assertEqual([r['targets'] for r in requests[1:]], [expected, expected])
                self.assertEqual(self.raw_clips(requests[1]), self.clips[:len(texts)])
                self.assertEqual(self.raw_clips(requests[2]), self.clips[:len(texts)])
                supplied_context = json.loads(requests[1]['body']['contents'][0]['parts'][0]['text'])
                self.assertTrue(all(FLAG not in row for row in supplied_context['observations']))
                self.assertTrue(all(row[FLAG] for row in joint.values()))
                self.assertTrue(all(FLAG not in row for row in result['observations']))
                self.assertTrue(all(FLAG not in row for row in agent.observations.values()))
                self.assertEqual({key[0] for key in planner._audio_cache}, set(expected))
                self.assertTrue(all(not row['uncertain'] for row in planner._audio_cache.values()))
                self.assertEqual([e['payload']['api_name'] for e in events if e['action'] == 'tool_call'], ['set_label'])
                self.assertEqual(planner.evidence[-1]['audio_admission'], 'independent')
                self.assertTrue(agent._consumed_grants)
                await planner.close()

    async def test_every_retained_source_failure_blocks_later_writes_without_partial_promotion(self):
        for audio in (False, True):
            for index in range(3 if audio else 2):
                for fault in ('main_uncertain', 'acoustic_uncertain', 'conflict', 'main_missing', 'acoustic_missing'):
                    with self.subTest(audio=audio, index=index, fault=fault):
                        planner, requests, _, script = await self.planner()
                        agent = self.agent(planner)
                        await self.apply_plan(agent)
                        self.advance(agent, audio=audio)
                        texts = [*TEXTS, COMMAND] if audio else TEXTS
                        script.update(main=proposal(rows(texts), write=True), heard=rows(texts))
                        target = script['main']['observations'] if fault.startswith('main') else script['heard']
                        if fault.endswith('uncertain'):
                            target[index]['uncertain'] = True
                        elif fault.endswith('missing'):
                            target.pop(index)
                        else:
                            target[index]['transcript'] += ' Extra material words.'
                        result, events = await self.apply_plan(agent)
                        self.assertTrue(result.get('clarification'))
                        self.assertFalse(result.get('tool_calls'))
                        self.assertFalse(any(event['action'] == 'tool_call' for event in events))
                        self.assertEqual(planner._audio_cache, {})
                        self.assertTrue(all(row.get(FLAG) for row in agent.observations.values()))
                        self.assertFalse(agent._consumed_grants)
                        self.assertEqual(len(requests), 2 if fault.startswith('main') else 3)
                        if audio and fault.endswith('missing'):
                            self.assertEqual(planner._pending_audio_sources, {2: (2, 2, 'audio/mpeg',
                                hashlib.sha256(self.clips[2]).hexdigest())})
                        await planner.close()

    async def test_uncached_history_is_required_even_when_files_disappear(self):
        for index in (0, 1):
            with self.subTest(index=index):
                self.restore_clips()
                planner, requests, _, script = await self.planner()
                agent = self.agent(planner)
                await self.apply_plan(agent)
                self.advance(agent)
                script['main'] = proposal(write=True)
                (self.root / f'{index}.mp3').unlink()
                result, events = await self.apply_plan(agent)
                self.assertTrue(result['clarification'])
                self.assertFalse(any(event['action'] == 'tool_call' for event in events))
                self.assertEqual(len(requests), 1)
                self.assertEqual(planner._audio_cache, {})
                await planner.close()

    async def test_joint_history_rejects_replaced_bytes_before_a_later_write(self):
        for audio in (False, True):
            for index in (0, 1):
                with self.subTest(audio=audio, index=index):
                    self.restore_clips()
                    planner, requests, _, script = await self.planner()
                    agent = self.agent(planner)
                    await self.apply_plan(agent)
                    (self.root / f'{index}.mp3').write_bytes(self.clips[1 - index])
                    self.advance(agent, audio=audio)
                    texts = [*TEXTS, COMMAND] if audio else TEXTS
                    script.update(main=proposal(rows(texts), write=True), heard=rows(texts))
                    result, events = await self.apply_plan(agent)
                    self.assertTrue(result.get('clarification'))
                    self.assertFalse(any(event['action'] == 'tool_call' for event in events))
                    self.assertEqual(planner._audio_cache, {})
                    self.assertFalse(agent._consumed_grants)
                    self.assertEqual(len(requests), 1)
                    await planner.close()

    async def test_noneligible_plans_use_real_acoustic_requests(self):
        for kind in ('write', 'unknown', 'unknown_kind', 'bad_args', 'authorization', 'continuation', 'bindings', 'repair'):
            with self.subTest(kind=kind):
                main = proposal(write=kind == 'write')
                tools = deepcopy(TOOLS)
                call = main['tool_calls'][0]
                if kind == 'unknown':
                    call['api_name'] = 'unlisted_lookup'
                elif kind == 'unknown_kind':
                    tools['lookup_route']['kind'] = 'maybe_read'
                elif kind == 'bad_args':
                    call['args']['destination'] = 17
                elif kind == 'authorization':
                    call['authorization'] = {'quote': TEXTS[0]}
                elif kind == 'continuation':
                    call['after_result'] = proposal(write=True)['tool_calls'][0]
                elif kind == 'bindings':
                    call['result_bindings'] = {'destination': {'call_id': 'unseen', 'path': 'name'}}
                planner, requests, _, _ = await self.planner({'main': main, 'heard': rows()})
                agent = self.agent(planner, tools=tools)
                if kind == 'repair':
                    agent._planning_error = 'Repair the rejected proposal.'
                result = await planner.plan(agent._context())
                self.assertEqual([r['acoustic'] for r in requests], [False, True])
                self.assertEqual([r['targets'] for r in requests], [[0, 1], [0, 1]])
                self.assertTrue(all(FLAG not in row for row in result['observations']))
                self.assertEqual(planner.evidence[-1]['audio_admission'], 'independent')
                await planner.close()

    async def test_joint_reread_preserves_old_uncertainty_until_real_later_corroboration(self):
        main = proposal()
        main['observations'][0]['uncertain'] = True
        planner, requests, native, script = await self.planner({'main': main, 'heard': rows()})
        agent = self.agent(planner)
        await self.apply_plan(agent)
        self.assertTrue(planner._audio_stopped)
        self.advance(agent, audio=True)
        texts = [*TEXTS, 'Find routes to Salta.']
        script.update(main=proposal(rows(texts)), heard=rows(texts))
        result, events = await self.apply_plan(agent)
        self.assertTrue(result['observations'][0]['uncertain'])
        self.assertFalse(native[-1]['observations'][0]['uncertain'])
        self.assertTrue(any(event['action'] == 'tool_call' for event in events))
        self.assertTrue(all(row[FLAG] for row in agent.observations.values()))
        self.assertEqual(planner._audio_cache, {})
        self.advance(agent)
        script['main'] = proposal(rows(texts), write=True)
        result, events = await self.apply_plan(agent)
        self.assertTrue(all(not row['uncertain'] and FLAG not in row for row in result['observations']))
        self.assertEqual(len(planner._audio_cache), 3)
        self.assertEqual([r['acoustic'] for r in requests], [False, False, False, True])
        self.assertTrue(any(event['action'] == 'tool_call' for event in events))
        self.assertTrue(native[0]['observations'][0]['uncertain'])

    async def test_deferred_acoustic_budget_includes_main_time_and_failure_is_latched(self):
        async def slow_main(acoustic, body, reply):
            self.assertFalse(acoustic, 'No acoustic POST is allowed after its original absolute deadline.')
            await asyncio.sleep(.06)
            return reply
        planner, requests, _, _ = await self.planner({'main': proposal(write=True), 'heard': rows()}, hook=slow_main)
        planner.acoustic_timeout, planner.timeout = .035, .2
        agent = self.agent(planner)
        result, events = await self.apply_plan(agent)
        self.assertTrue(result['clarification'])
        self.assertFalse(any(event['action'] == 'tool_call' for event in events))
        self.assertEqual(len(requests), 1)
        self.assertEqual(planner._audio_cache, {})
        self.assertTrue(planner._audio_stopped)
        self.assertEqual(next(r for r in planner.evidence if r['phase'] == 'acoustic')['status'], 'timeout')
        again = await planner.plan(agent._context())
        self.assertTrue(again['clarification'])
        self.assertEqual(len(requests), 1)

    async def test_changed_bytes_or_revision_cannot_commit_joint_or_verified_rows(self):
        for write in (False, True):
            for change in ('first_clip', 'second_clip', 'revision'):
                with self.subTest(write=write, change=change):
                    self.restore_clips()
                    candidate = None
                    async def mutate(acoustic, body, reply):
                        if acoustic == write:
                            if change == 'revision':
                                candidate['messages'][0]['revision'] += 1
                            else:
                                index = 0 if change == 'first_clip' else 1
                                (self.root / f'{index}.mp3').write_bytes(self.clips[1 - index])
                        return reply
                    planner, requests, _, _ = await self.planner({'main': proposal(write=write), 'heard': rows()}, hook=mutate)
                    agent = self.agent(planner)
                    candidate = agent._context()
                    result = await planner.plan(candidate)
                    self.assertTrue(result['clarification'])
                    self.assertEqual(result['tool_calls'], [])
                    self.assertEqual(planner._audio_cache, {})
                    self.assertEqual(planner.evidence[-1]['audio_admission'], 'blocked')
                    self.assertEqual(len(requests), 2 if write else 1)
                    await planner.close()

    async def test_cancellation_or_new_turn_cannot_promote_late_native_output(self):
        for write in (False, True):
            for cancel in (False, True):
                with self.subTest(write=write, cancel=cancel):
                    arrived, release = asyncio.Event(), asyncio.Event()
                    async def delayed(acoustic, body, reply):
                        if acoustic == write:
                            arrived.set()
                            try:
                                await release.wait()
                            except asyncio.CancelledError:
                                return reply
                        return reply
                    planner, _, _, _ = await self.planner({'main': proposal(write=write), 'heard': rows()}, hook=delayed)
                    agent = self.agent(planner)
                    task = asyncio.create_task(planner.plan(agent._context()))
                    await asyncio.wait_for(arrived.wait(), .5)
                    if cancel:
                        task.cancel()
                    else:
                        self.advance(agent)
                    release.set()
                    result = (await asyncio.gather(task, return_exceptions=True))[0]
                    self.assertTrue(isinstance(result, asyncio.CancelledError) or result.get('clarification'))
                    self.assertEqual(planner._audio_cache, {})
                    self.assertEqual(agent.observations, {})
                    self.assertEqual(planner._pending_audio_sources, self.source_keys())
                    await planner.close()
                    self.assertEqual(planner._pending_audio_sources, {})
                    self.assertEqual(planner._pending_tasks, set())

    async def test_outer_commit_rechecks_epoch_after_generation_has_finished(self):
        planner, requests, _, _ = await self.planner({'main': proposal(write=True), 'heard': rows()})
        agent = self.agent(planner)
        generate = planner._generate
        async def superseded(*args):
            result = await generate(*args)
            self.assertTrue(all(FLAG in row for row in result['observations']))
            self.advance(agent)
            return result
        with patch.object(planner, '_generate', superseded):
            result = await planner.plan(agent._context())
        self.assertTrue(result['clarification'])
        self.assertEqual(result['tool_calls'], [])
        self.assertEqual(planner._audio_cache, {})
        self.assertEqual(agent.observations, {})
        self.assertEqual(len(requests), 2)
        self.assertEqual(planner._pending_audio_sources, self.source_keys())
        self.assertEqual(planner.evidence[-1]['audio_admission'], 'blocked')

    async def next_action(self, agent, action):
        async def receive():
            while True:
                event = await agent.out_queue.get()
                if event['action'] == action:
                    return event
        return await asyncio.wait_for(receive(), .7)

    def source_keys(self):
        return {i: (i, 1, 'audio/mpeg', hashlib.sha256(raw).hexdigest())
                for i, raw in enumerate(self.clips[:2])}

    async def test_failed_first_main_recovers_in_real_session_with_fresh_typed_read_or_write(self):
        for fault in ('http_503', 'missing', 'malformed', 'timeout'):
            for write in (False, True):
                with self.subTest(fault=fault, write=write):
                    arrived, release = asyncio.Event(), asyncio.Event()
                    async def transport(acoustic, body, reply):
                        if len(requests) == 1:
                            if fault == 'http_503':
                                return httpx.Response(503, json={'error': {'message': 'offline fault'}})
                            if fault == 'timeout':
                                raise httpx.ReadTimeout('offline fault')
                            if fault == 'missing':
                                reply['observations'].pop()
                            else:
                                reply['observations'][0]['transcript'] = 17
                        elif acoustic == write:
                            arrived.set()
                            await release.wait()
                        return reply
                    planner, requests, _, script = await self.planner(hook=transport)
                    agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue(), planner=planner)
                    running = asyncio.create_task(agent.run())
                    try:
                        agent.in_queue.put_nowait({'event_type': 'tool_manifest', 'payload': {'tools': TOOLS}})
                        for index in range(2):
                            agent.in_queue.put_nowait({'event_type': 'user_audio_chunk', 'payload': {
                                'audio_ref': f'{index}.mp3', 'end_of_turn': index == 1}})
                        await self.next_action(agent, 'clarification_request')
                        self.assertEqual(agent.observations, {})
                        self.assertEqual(agent.operations, {})
                        self.assertEqual(planner._audio_cache, {})
                        self.assertEqual(planner._pending_audio_sources, self.source_keys())
                        script['main'] = proposal(write=write)
                        agent.in_queue.put_nowait({'event_type': 'user_speech_chunk', 'payload': {
                            'text': COMMAND if write else 'Find routes to Salta.', 'end_of_turn': True}})
                        await asyncio.wait_for(arrived.wait(), .7)
                        self.assertEqual(agent.observations, {})
                        self.assertEqual(agent.operations, {})
                        self.assertEqual(planner._audio_cache, {})
                        self.assertEqual(planner._pending_audio_sources, self.source_keys())
                        self.assertEqual([r['acoustic'] for r in requests], [False, False, True] if write else [False, False])
                        for request in requests[1:]:
                            self.assertEqual(request['targets'], [0, 1])
                            self.assertEqual(self.raw_clips(request), self.clips[:2])
                        release.set()
                        event = await self.next_action(agent, 'tool_call')
                        call = event['payload']
                        self.assertEqual(event['state_snapshot']['revision'], 2)
                        self.assertEqual(call['api_name'], 'set_label' if write else 'lookup_route')
                        self.assertEqual(planner._pending_audio_sources, {})
                        self.assertEqual(len(planner._audio_cache), 2 if write else 0)
                        self.assertTrue(all((FLAG not in row) == write for row in agent.observations.values()))
                        actual = {'label': 'Harbor'} if write else {'routes': 'ACTUAL-SALTA'}
                        agent.in_queue.put_nowait({'event_type': 'tool_result', 'payload': {
                            'call_id': call['call_id'], 'api_name': call['api_name'], 'status': 'success', 'result': actual}})
                        final = await self.next_action(agent, 'final_response')
                        self.assertIn('Harbor' if write else 'ACTUAL-SALTA', final['payload']['text'])
                    finally:
                        release.set()
                        running.cancel()
                        await asyncio.gather(running, return_exceptions=True)
                    self.assertEqual(planner._pending_audio_sources, {})

    async def test_pending_identity_rejects_mutation_or_missing_source_without_partial_registration(self):
        for fault in ('bytes', 'revision', 'missing_message', 'unreadable'):
            with self.subTest(fault=fault):
                self.restore_clips()
                async def fail_first(acoustic, body, reply):
                    if len(requests) == 1:
                        reply['observations'].pop()
                    return reply
                planner, requests, _, script = await self.planner(hook=fail_first)
                agent = self.agent(planner)
                await self.apply_plan(agent)
                pending = deepcopy(planner._pending_audio_sources)
                self.assertEqual(pending, self.source_keys())
                self.advance(agent, audio=True)
                if fault == 'bytes':
                    (self.root / '0.mp3').write_bytes(self.clips[1])
                elif fault == 'revision':
                    agent.messages[0]['revision'] += 1
                elif fault == 'missing_message':
                    agent.messages[0] = {'message_index': 0, 'revision': 1,
                                         'event_type': 'user_speech_chunk', 'payload': {'text': 'Changed.'}}
                else:
                    (self.root / '0.mp3').unlink()
                script['main'] = proposal(rows([*TEXTS, COMMAND]), write=True)
                result, events = await self.apply_plan(agent)
                self.assertTrue(result['clarification'])
                self.assertFalse(any(event['action'] == 'tool_call' for event in events))
                self.assertEqual(len(requests), 1)
                self.assertEqual(planner._pending_audio_sources, pending)
                self.assertEqual(planner._audio_cache, {})
                self.assertEqual(agent.observations, {})
                await planner.close()

    async def test_ready_joint_result_keeps_pending_until_controller_stores_it(self):
        arrived, release = asyncio.Event(), asyncio.Event()
        discarded = []
        async def transport(acoustic, body, reply):
            self.assertFalse(acoustic)
            if len(requests) == 1:
                def queue_correction(task):
                    discarded.append((deepcopy(agent.observations), deepcopy(planner._pending_audio_sources)))
                    agent.in_queue.put_nowait({'event_type': 'user_speech_chunk', 'payload': {
                        'text': 'Find routes to Salta.', 'end_of_turn': True}})
                agent._plan_task.add_done_callback(queue_correction)
            else:
                arrived.set()
                await release.wait()
            return reply
        planner, requests, _, script = await self.planner(hook=transport)
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue(), planner=planner)
        running = asyncio.create_task(agent.run())
        try:
            agent.in_queue.put_nowait({'event_type': 'tool_manifest', 'payload': {'tools': TOOLS}})
            for index in range(2):
                agent.in_queue.put_nowait({'event_type': 'user_audio_chunk', 'payload': {
                    'audio_ref': f'{index}.mp3', 'end_of_turn': index == 1}})
            await asyncio.wait_for(arrived.wait(), .7)
            self.assertEqual(discarded, [({}, self.source_keys())])
            self.assertEqual(agent.observations, {})
            self.assertEqual(agent.operations, {})
            self.assertEqual(planner._audio_cache, {})
            self.assertEqual(planner._pending_audio_sources, self.source_keys())
            self.assertEqual(len(requests), 2)
            self.assertEqual(self.raw_clips(requests[1]), self.clips[:2])
            release.set()
            event = await self.next_action(agent, 'tool_call')
            self.assertEqual(event['state_snapshot']['revision'], 2)
            self.assertEqual(planner._pending_audio_sources, {})
            self.assertEqual(set(agent.observations), {0, 1})
            # A row lost after actual acceptance must not re-enter the pending fallback.
            agent.observations.pop(0)
            script['main'] = proposal(write=True)
            agent.in_queue.put_nowait({'event_type': 'user_speech_chunk', 'payload': {
                'text': COMMAND, 'end_of_turn': True}})
            await self.next_action(agent, 'clarification_request')
            self.assertEqual(len(requests), 2)
            self.assertEqual(planner._pending_audio_sources, {})
            self.assertEqual(planner._audio_cache, {})
            self.assertFalse(any(op['kind'] == 'state_modifying' for op in agent.operations.values()))
        finally:
            release.set()
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)

    async def test_rejected_controller_apply_keeps_pending_and_stores_no_partial_rows(self):
        planner, requests, _, _ = await self.planner()
        agent = self.agent(planner)
        result = await planner.plan(agent._context())
        self.assertEqual(planner._pending_audio_sources, self.source_keys())
        result['observations'][1].pop(FLAG)
        agent._apply(result)
        events = self.drain(agent)
        self.assertTrue(any(event['action'] == 'clarification_request' for event in events))
        self.assertFalse(any(event['action'] == 'tool_call' for event in events))
        self.assertEqual(agent.observations, {})
        self.assertEqual(planner._pending_audio_sources, self.source_keys())
        self.assertEqual(planner._audio_cache, {})
        self.assertEqual(len(requests), 1)

    async def test_late_initial_preparation_cannot_register_after_supersession_cancel_close_or_deadline(self):
        for fault in ('new_turn', 'cancel', 'close', 'deadline'):
            with self.subTest(fault=fault):
                planner, requests, _, _ = await self.planner()
                agent = self.agent(planner)
                arrived, release = asyncio.Event(), asyncio.Event()
                prepare = planner.media.prepare
                async def delayed(messages):
                    result = await prepare(messages)
                    arrived.set()
                    try:
                        await release.wait()
                    except asyncio.CancelledError:
                        await release.wait()
                    return result
                if fault == 'deadline':
                    planner.timeout = .04
                with patch.object(planner.media, 'prepare', delayed):
                    task = asyncio.create_task(planner.plan(agent._context()))
                    await asyncio.wait_for(arrived.wait(), .7)
                    if fault == 'new_turn':
                        self.advance(agent)
                    elif fault == 'cancel':
                        task.cancel()
                    elif fault == 'close':
                        await planner.close()
                    else:
                        with self.assertRaises(PlannerError):
                            await task
                    release.set()
                    await asyncio.gather(task, return_exceptions=True)
                    pending = planner._pending_tasks.copy()
                    if pending:
                        await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), .7)
                self.assertEqual(requests, [])
                self.assertEqual(planner._pending_audio_sources, {})
                self.assertEqual(planner._audio_cache, {})
                self.assertEqual(agent.observations, {})
                await planner.close()

    async def test_early_main_uncertainty_must_rehash_before_accepting_or_retiring_pending(self):
        for changed in (False, True):
            with self.subTest(changed=changed):
                self.restore_clips()
                main = proposal(write=True)
                main['observations'][0]['uncertain'] = True
                async def transport(acoustic, body, reply):
                    self.assertFalse(acoustic)
                    if changed:
                        (self.root / '0.mp3').write_bytes(self.clips[1])
                    return reply
                planner, requests, _, _ = await self.planner({'main': main, 'heard': rows()}, hook=transport)
                agent = self.agent(planner)
                result, events = await self.apply_plan(agent)
                self.assertTrue(result['clarification'])
                self.assertFalse(any(event['action'] == 'tool_call' for event in events))
                self.assertEqual(len(requests), 1)
                self.assertEqual(planner._audio_cache, {})
                self.assertEqual(planner._pending_audio_sources, self.source_keys() if changed else {})
                self.assertEqual(set(agent.observations), set() if changed else {0, 1})
                if changed:
                    self.assertEqual(result['observations'], [])
                await planner.close()



if __name__ == '__main__':
    unittest.main()
