import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from PIL import Image

from participant.agent import ParticipantAgent
from participant.planner import Planner, PlannerError
from tests.test_participant_planner import completion, decision


class MissingFrameAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        env = patch.dict(os.environ, {
            'SECRET_GEMINI_API_KEY': 'offline-only',
            'PARTICIPANT_MEDIA_ROOT': str(self.root),
            'PARTICIPANT_PREWARM': '0',
            'PARTICIPANT_IMAGE_EMBEDDING': '0',
        }, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.tools = {'manual': {'kind': 'read_only', 'args': {'query': {'type': 'string'}}}}
        self.reply = None
        self.requests = []

        def handle(request):
            self.requests.append(json.loads(request.content))
            return completion(self.reply)

        self.planner = Planner(transport=httpx.MockTransport(handle))
        await self.planner.setup()
        self.addAsyncCleanup(self.planner.close)

    def agent(self):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue(), planner=self.planner)
        agent.tools = self.tools
        return agent

    async def complete_turn(self, agent):
        revision, planned = await agent._plan_task
        self.assertEqual(revision, agent.revision)
        agent._plan_task = None
        agent._apply(planned)
        return planned

    @staticmethod
    def drain(agent):
        return [agent.out_queue.get_nowait() for _ in range(agent.out_queue.qsize())]

    @staticmethod
    def lookup(evidence='omitted', *, query='LAN'):
        step = {'api_name': 'manual', 'args': {'query': query},
                'response_template': 'The printed LAN port is described by {records.0.title}.'}
        if evidence == 'printed_text':
            step['result_evidence'] = {
                'path': 'records.0.title', 'contains': 'LAN', 'target_basis': 'printed_text'}
        elif evidence != 'omitted':
            step['result_evidence'] = evidence
        return decision(tool_calls=[step], response=None)

    async def test_missing_or_corrupt_current_frame_rejects_every_evidence_variant(self):
        for reference, corrupt in (('missing.png', False), ('corrupt.png', True)):
            if corrupt:
                (self.root / reference).write_bytes(b'not an image')
            for evidence in ('omitted', None, 'printed_text'):
                with self.subTest(reference=reference, evidence=evidence):
                    agent = self.agent()
                    self.reply = self.lookup(evidence)
                    agent._handle({'event_type': 'video_frame', 'payload': {'image_ref': reference}})
                    agent._handle({'event_type': 'user_speech_chunk', 'payload': {
                        'text': 'What is the port in this picture?', 'end_of_turn': True}})
                    await self.complete_turn(agent)

                    prepared = json.loads(self.requests[-1]['contents'][0]['parts'][0]['text'])
                    self.assertTrue(prepared['messages'][0]['payload']['image_unavailable'])
                    self.assertEqual(self.planner.evidence[-1]['input_media'], [])
                    self.assertEqual(self.planner.evidence[-1]['validation_error'],
                                     'the active request image source is unavailable')
                    self.assertNotIn('tool_call', [item['action'] for item in self.drain(agent)])

    async def test_later_picture_reference_after_unrelated_text_clarifies(self):
        for reference, corrupt in (('missing.png', False), ('corrupt.png', True)):
            if corrupt:
                (self.root / reference).write_bytes(b'not an image')
            with self.subTest(reference=reference):
                agent = self.agent()
                self.reply = decision(response='Here is an unrelated fact.')
                agent._handle({'event_type': 'video_frame', 'payload': {'image_ref': reference}})
                agent._handle({'event_type': 'user_speech_chunk', 'payload': {
                    'text': 'Tell me something interesting.', 'end_of_turn': True}})
                await self.complete_turn(agent)
                self.drain(agent)

                self.reply = self.lookup()
                agent._handle({'event_type': 'user_speech_chunk', 'payload': {
                    'text': 'What is the port in that picture?', 'end_of_turn': True}})
                await self.complete_turn(agent)

                actions = self.drain(agent)
                self.assertNotIn('tool_call', [item['action'] for item in actions])
                self.assertIn('clarification_request', [item['action'] for item in actions])
                self.assertEqual(self.planner.evidence[-1]['validation_error'],
                                 'the active request image source is unavailable')

    async def test_later_explicit_text_lookup_is_not_blocked_by_old_missing_frame(self):
        agent = self.agent()
        self.reply = decision(clarification='I could not read the frame. Please describe it.')
        agent._handle({'event_type': 'video_frame', 'payload': {'image_ref': 'missing.png'}})
        agent._handle({'event_type': 'user_speech_chunk', 'payload': {
            'text': 'What is the port in this picture?', 'end_of_turn': True}})
        await self.complete_turn(agent)
        self.drain(agent)

        self.reply = self.lookup(None)
        agent._handle({'event_type': 'user_speech_chunk', 'payload': {
            'text': 'Look up a manual for the LAN port.', 'end_of_turn': True}})

        await self.complete_turn(agent)

        actions = self.drain(agent)
        call = next(item for item in actions if item['action'] == 'tool_call')
        self.assertEqual(call['payload']['args'], {'query': 'LAN'})
        prepared = json.loads(self.requests[-1]['contents'][0]['parts'][0]['text'])
        self.assertTrue(prepared['messages'][0]['payload']['image_unavailable'])
        self.assertEqual(self.planner.evidence[-1]['input_media'], [])
        self.assertNotIn('validation_error', self.planner.evidence[-1])

    async def test_replacement_frame_uses_its_own_observation_source(self):
        replacement = self.root / 'replacement.png'
        Image.new('RGB', (4, 4), 'blue').save(replacement)
        agent = self.agent()
        self.reply = decision(clarification='I could not read the first frame. Please resend it.')
        agent._handle({'event_type': 'video_frame', 'payload': {'image_ref': 'missing.png'}})
        agent._handle({'event_type': 'user_speech_chunk', 'payload': {
            'text': 'What is the port in this picture?', 'end_of_turn': True}})
        await self.complete_turn(agent)
        self.drain(agent)

        observation = {
            'message_index': 2, 'type': 'image', 'visible_text': ['LINE IN'],
            'selected_label': {'text': 'LINE IN', 'recognition': 'clear', 'referent': 'ambiguous'},
            'observation': 'The current frame shows a LINE IN port label.', 'uncertain': True,
        }
        self.reply = decision(observations=[observation], tool_calls=[{
            'api_name': 'manual', 'args': {'query': 'LINE IN'},
            'response_template': '{records.0.title}',
            'result_evidence': {'path': 'records.0.title', 'contains': 'LINE IN',
                                'target_basis': 'printed_text'},
        }], response=None)
        agent._handle({'event_type': 'video_frame', 'payload': {'image_ref': 'replacement.png'}})
        agent._handle({'event_type': 'user_speech_chunk', 'payload': {
            'text': 'Look up the LINE IN port in this picture.', 'end_of_turn': True}})

        planned = await self.complete_turn(agent)

        self.assertEqual(planned['observations'][0]['message_index'], 2)
        self.assertEqual(self.planner.evidence[-1]['input_media'][0]['message_index'], 2)
        self.assertEqual(prepared_index(self.requests[-1]), 2)
        self.assertIn('tool_call', [item['action'] for item in self.drain(agent)])

        self.reply = decision(observations=[{**observation, 'message_index': 0}], response=None)
        with self.assertRaises(PlannerError):
            await self.planner.plan(agent._context())
        self.assertEqual(self.planner.evidence[-1]['validation_error'], 'unattached observation')


def prepared_index(request):
    prepared = json.loads(request['contents'][0]['parts'][0]['text'])
    return prepared['latest_frame_index']


if __name__ == '__main__':
    unittest.main()
