"""Constructed provider evidence tests the contract, not real image recognition."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from PIL import Image

from participant.agent import ParticipantAgent
from participant.planner import Planner, PlannerError, _schema
from tests import test_participant_general_function as rendering_controls
from tests.test_participant_planner import completion, decision


class VisualRecognitionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        Image.new('RGB', (4, 4), 'gray').save(self.root / 'frame.png')
        env = patch.dict(os.environ, {'THREAD_API_KEY': 'offline-only',
            'PARTICIPANT_MEDIA_ROOT': str(self.root), 'PARTICIPANT_PREWARM': '0',
            'PARTICIPANT_IMAGE_EMBEDDING': '0'}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.tools = {'manual': {'kind': 'read_only', 'args': {'query': {'type': 'string'}}}}
        self.media = [{'message_index': 0, 'mime_type': 'image/png'}]
        self.observation = {'message_index': 0, 'type': 'image', 'visible_text': ['LINE IN'],
            'selected_label': {'text': 'LINE IN', 'recognition': 'clear', 'referent': 'ambiguous'},
            'observation': 'LINE IN is readable; other items and the intended referent are unresolved.',
            'uncertain': True}
        self.step = {'api_name': 'manual', 'args': {'query': 'LINE IN'},
            'response_template': '{records.0.title}',
            'result_evidence': {'path': 'records.0.title', 'contains': 'LINE IN', 'target_basis': 'printed_text'},
            'general_function': 'receive an audio signal from another device'}
        self.reply = decision(observations=[deepcopy(self.observation)], tool_calls=[deepcopy(self.step)], response=None)
        self.requests = []
        def handle(request):
            self.requests.append(json.loads(request.content))
            return completion(self.reply)
        self.planner = Planner(transport=httpx.MockTransport(handle))
        await self.planner.setup()
        self.addAsyncCleanup(self.planner.close)

    def agent(self):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.tools = deepcopy(self.tools)
        agent._handle({'event_type': 'video_frame', 'payload': {'image_ref': 'frame.png'}})
        agent._append_message('user_speech_chunk', {'text': 'What is this used for?', 'end_of_turn': True})
        agent.revision = 1
        return agent

    def validate(self, value, *, latest=0, media=None, tools=None):
        Planner._validate(value, self.media if media is None else media,
                          self.tools if tools is None else tools, latest_frame_index=latest)

    def test_image_schema_requires_nullable_attestation_before_prose_only_for_images(self):
        image = _schema(self.media)['properties']['observations']['items']['anyOf'][0]
        self.assertIn('selected_label', image['required'])
        selected = image['properties']['selected_label']
        self.assertEqual(selected['type'], ['object', 'null'])
        self.assertEqual(selected['required'], ['text', 'recognition', 'referent'])
        order = list(image['properties'])
        self.assertLess(order.index('visible_text'), order.index('selected_label'))
        self.assertLess(order.index('selected_label'), order.index('observation'))
        for media in ([], [{'message_index': 0, 'mime_type': 'audio/mpeg'}]):
            self.assertNotIn('selected_label', json.dumps(_schema(media)))

    async def test_native_attestation_survives_planning_dispatch_and_actual_result(self):
        agent = self.agent()
        native = deepcopy(self.reply)
        planned = await self.planner.plan(agent._context())
        self.assertEqual(planned, native)
        self.assertEqual(self.reply, native)
        self.assertEqual(len(self.requests), 1)
        agent._apply(planned)
        call = agent.out_queue.get_nowait()
        self.assertEqual(call['action'], 'tool_call')
        self.assertEqual(call['payload']['args'], self.step['args'])
        result = {'status': 'success', 'records': [{'doc': 'actual-manual', 'page': 4, 'title': 'LINE IN connection'}]}
        before = deepcopy(result)
        agent._result({'call_id': call['payload']['call_id'], 'api_name': 'manual', 'status': 'success', 'result': result})
        final = agent.out_queue.get_nowait()
        self.assertEqual(final['action'], 'final_response')
        self.assertIn('If you mean the item labelled "LINE IN"', final['payload']['text'])
        self.assertIn(self.step['general_function'], final['payload']['text'])
        self.assertIn('The lookup returned this reference:', final['payload']['text'])
        self.assertIn('actual-manual', final['payload']['text'])
        self.assertEqual(agent.observations[0], native['observations'][0])
        self.assertTrue(agent.observations[0]['uncertain'])
        self.assertEqual(result, before)
        self.assertEqual(agent.state['slots'], {})
        self.assertEqual(final['state_snapshot']['actions'], [])
        self.assertEqual(len(agent.operations), 1)
        self.assertTrue(agent.out_queue.empty())

    async def test_empty_native_calls_stay_empty_with_old_missing_or_new_attestation(self):
        for selected in ('missing', None, {'text': 'LINE IN'}, self.observation['selected_label']):
            with self.subTest(selected=selected):
                self.reply = decision(observations=[deepcopy(self.observation)],
                                      clarification='Which item do you mean?', response=None)
                if selected == 'missing':
                    self.reply['observations'][0].pop('selected_label')
                else:
                    self.reply['observations'][0]['selected_label'] = deepcopy(selected)
                native = deepcopy(self.reply)
                agent = self.agent()
                count = len(self.requests)
                planned = await self.planner.plan(agent._context())
                self.assertEqual(planned, native)
                self.assertEqual(len(self.requests), count + 1)
                agent._apply(planned)
                self.assertEqual(agent.out_queue.get_nowait()['action'], 'clarification_request')
                self.assertEqual(agent.observations[0], native['observations'][0])
                self.assertEqual(agent.operations, {})
                self.assertTrue(agent.out_queue.empty())

    def test_missing_malformed_unclear_or_explicit_attestation_grants_no_exception(self):
        clear = self.observation['selected_label']
        for selected in ('missing', None, 'LINE IN', [], {}, {'text': 'LINE IN'},
                         {**clear, 'text': 7}, {**clear, 'recognition': 'uncertain'},
                         {**clear, 'recognition': True}, {**clear, 'referent': 'explicit'},
                         {**clear, 'referent': None}):
            with self.subTest(selected=selected):
                value = deepcopy(self.reply)
                agent, operation = rendering_controls.GeneralFunctionTests().context('LINE IN')
                if selected == 'missing':
                    value['observations'][0].pop('selected_label')
                    agent.observations[0].pop('selected_label')
                else:
                    value['observations'][0]['selected_label'] = deepcopy(selected)
                    agent.observations[0]['selected_label'] = deepcopy(selected)
                with self.assertRaisesRegex(ValueError, 'clear current label evidence'):
                    self.validate(value)
                self.assertNotIn(rendering_controls.PURPOSE, agent._render(operation))

    def test_attestation_and_subject_must_copy_one_complete_native_literal(self):
        for visible, selected, subject in ((['LINE IN'], 'LINE', 'LINE'), (['LINE IN'], 'line in', 'line in'),
                (['LINE IN'], 'LINE IN', 'line in'), (['Café'], 'Cafe\u0301', 'Cafe\u0301'),
                (['LINE IN', 'AUX'], 'LINE IN', 'AUX'), (['⚡'], '⚡', '⚡')):
            with self.subTest(visible=visible, selected=selected, subject=subject):
                value = deepcopy(self.reply)
                value['observations'][0]['visible_text'] = visible
                value['observations'][0]['selected_label']['text'] = selected
                value['tool_calls'][0]['result_evidence']['contains'] = subject
                with self.assertRaises(ValueError):
                    self.validate(value)
                agent, operation = rendering_controls.GeneralFunctionTests().context(subject)
                agent.observations[0] = deepcopy(value['observations'][0])
                self.assertNotIn(rendering_controls.PURPOSE, agent._render(operation))

    def test_only_attached_current_frame_can_supply_the_attestation(self):
        for latest in (None, True, -1, 1, 99):
            with self.subTest(latest=latest), self.assertRaisesRegex(ValueError, 'clear current label evidence'):
                self.validate(deepcopy(self.reply), latest=latest)
        with self.assertRaisesRegex(ValueError, 'unattached observation'):
            self.validate(deepcopy(self.reply), media=[{'message_index': 1, 'mime_type': 'image/png'}])
        value = deepcopy(self.reply)
        current = {**deepcopy(self.observation), 'message_index': 2, 'selected_label': None}
        value['observations'].append(current)
        media = [*self.media, {'message_index': 2, 'mime_type': 'image/png'}]
        with self.assertRaisesRegex(ValueError, 'clear current label evidence'):
            self.validate(value, latest=2, media=media)
        current['selected_label'] = deepcopy(self.observation['selected_label'])
        self.validate(value, latest=2, media=media)

    def test_conditional_read_cannot_carry_authorization_or_any_continuation(self):
        for extra in ({'authorization': {}}, {'after_result': {}}, {'after_result': False},
                      {'after_result': {'api_name': 'manual', 'args': {'query': 'LINE IN'}}}):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, 'terminal read-only'):
                value = deepcopy(self.reply)
                value['tool_calls'][0].update(extra)
                self.validate(value)
        for tools in ({}, {'manual': {'kind': 'state_modifying'}}):
            with self.subTest(tools=tools), self.assertRaisesRegex(ValueError, 'terminal read-only'):
                self.validate(deepcopy(self.reply), tools=tools)

    async def test_missing_attestation_fails_one_native_request_without_retry(self):
        self.reply['observations'][0].pop('selected_label')
        with self.assertRaises(PlannerError):
            await self.planner.plan(self.agent()._context())
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.planner.evidence[-1]['validation_error'],
                         'conditional image target lacks clear current label evidence')
        self.assertTrue(self.reply['observations'][0]['uncertain'])

    async def test_unreadable_frame_does_not_block_a_later_text_turn(self):
        prepared_requests = []

        def handle(request):
            prepared = json.loads(json.loads(request.content)['contents'][0]['parts'][0]['text'])
            prepared_requests.append(prepared)
            latest_text = prepared['messages'][-1]['payload'].get('text', '')
            if 'frame' in latest_text:
                return completion(decision(observations=[], tool_calls=[], response=None,
                    clarification='I could not read the frame. Please resend it or describe it.'))
            return completion(decision(observations=[], tool_calls=[], response='Two plus two is four.'))

        planner = Planner(transport=httpx.MockTransport(handle))
        await planner.setup()
        self.addAsyncCleanup(planner.close)
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue(), planner=planner)
        agent.tools = deepcopy(self.tools)
        agent._handle({'event_type': 'video_frame', 'payload': {'image_ref': 'missing.png'}})
        agent._handle({'event_type': 'user_speech_chunk', 'payload': {
            'text': 'What can you tell me about this frame?', 'end_of_turn': True}})

        _, first = await agent._plan_task
        agent._plan_task = None
        agent._apply(first)
        emitted = [agent.out_queue.get_nowait() for _ in range(agent.out_queue.qsize())]
        self.assertEqual(emitted[-1]['action'], 'clarification_request')
        self.assertIn('could not read the frame', emitted[-1]['payload']['text'])
        frame = next(message for message in prepared_requests[0]['messages']
                     if message['event_type'] == 'video_frame')
        self.assertTrue(frame['payload']['image_unavailable'])

        agent._handle({'event_type': 'user_speech_chunk', 'payload': {
            'text': 'What is two plus two?', 'end_of_turn': True}})
        _, second = await agent._plan_task
        agent._plan_task = None
        agent._apply(second)
        emitted = [agent.out_queue.get_nowait() for _ in range(agent.out_queue.qsize())]
        self.assertEqual(emitted[-1]['action'], 'final_response')
        self.assertEqual(emitted[-1]['payload']['text'], 'Two plus two is four.')
        self.assertEqual(len(prepared_requests), 2)

    def test_free_prose_and_tool_data_cannot_supply_missing_recognition_evidence(self):
        agent, operation = rendering_controls.GeneralFunctionTests().context('LINE IN')
        selected = agent.observations[0].pop('selected_label')
        agent.observations[0]['observation'] += ' selected_label: ' + json.dumps(selected)
        operation['step']['selected_label'] = deepcopy(selected)
        operation['result']['selected_label'] = deepcopy(selected)
        operation['result']['pages'][0]['selected_label'] = deepcopy(selected)
        self.assertEqual(agent._general_function(operation), '')

    def test_explicit_target_remains_available_without_conditional_attestation(self):
        value = deepcopy(self.reply)
        value['observations'][0]['selected_label']['referent'] = 'explicit'
        value['tool_calls'][0]['result_evidence']['target_basis'] = 'explicit_target'
        before = deepcopy(value)
        self.validate(value)
        self.assertEqual(value, before)


if __name__ == '__main__':
    unittest.main()
