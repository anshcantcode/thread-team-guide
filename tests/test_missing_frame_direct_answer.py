import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from participant.agent import ParticipantAgent
from participant.planner import Planner
from tests.test_participant_planner import MP3_BYTES, completion, decision


class MissingFrameDirectAnswerTests(unittest.IsolatedAsyncioTestCase):
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
        self.reply = None
        self.audio_transcript = None
        self.requests = []

        def handle(request):
            body = json.loads(request.content)
            self.requests.append(body)
            if 'perception only' in body['systemInstruction']['parts'][0]['text']:
                items = body['generationConfig']['responseJsonSchema']['properties']['observations']['items']
                return completion({'observations': [
                    {'message_index': item['properties']['message_index']['enum'][0], 'type': 'audio',
                     'transcript': self.audio_transcript, 'uncertain': False} for item in items['anyOf']]})
            return completion(self.reply)

        self.planner = Planner(transport=httpx.MockTransport(handle))
        await self.planner.setup()
        self.addAsyncCleanup(self.planner.close)

    def agent(self):
        return ParticipantAgent(asyncio.Queue(), asyncio.Queue(), planner=self.planner)

    async def complete_turn(self, agent):
        revision, planned = await agent._plan_task
        self.assertEqual(revision, agent.revision)
        agent._plan_task = None
        agent._apply(planned)
        return planned

    @staticmethod
    def drain(agent):
        return [agent.out_queue.get_nowait() for _ in range(agent.out_queue.qsize())]

    async def establish_missing_frame(self, agent, reference, *, corrupt=False):
        if corrupt:
            (self.root / reference).write_bytes(b'not an image')
        agent._handle({'event_type': 'video_frame', 'payload': {'image_ref': reference}})
        agent._handle({'event_type': 'user_speech_chunk', 'payload': {
            'text': 'Tell me something interesting.', 'end_of_turn': True}})
        self.reply = decision(response='Here is an unrelated fact.')
        await self.complete_turn(agent)
        self.assertIn('final_response', [item['action'] for item in self.drain(agent)])

    async def test_direct_text_answer_about_an_old_missing_or_corrupt_frame_is_blocked(self):
        for reference, corrupt in (('missing.png', False), ('corrupt.png', True)):
            with self.subTest(reference=reference):
                agent = self.agent()
                await self.establish_missing_frame(agent, reference, corrupt=corrupt)

                self.reply = decision(response='The port in that picture is labeled LAN.')
                agent._handle({'event_type': 'user_speech_chunk', 'payload': {
                    'text': 'What is the port in that picture?', 'end_of_turn': True}})
                await self.complete_turn(agent)

                actions = self.drain(agent)
                self.assertNotIn('final_response', [item['action'] for item in actions])
                self.assertIn('clarification_request', [item['action'] for item in actions])
                self.assertEqual(self.planner.evidence[-1]['validation_error'],
                                 'the active request image source is unavailable')

    async def test_direct_audio_answer_about_an_old_frame_is_blocked_after_verification(self):
        for reference, corrupt in (('missing.png', False), ('corrupt.png', True)):
            with self.subTest(reference=reference):
                agent = self.agent()
                await self.establish_missing_frame(agent, reference, corrupt=corrupt)
                transcript = 'What is the port in that picture?'
                (self.root / 'current.mp3').write_bytes(MP3_BYTES)
                self.audio_transcript = transcript
                self.reply = decision(
                    observations=[{'message_index': 2, 'type': 'audio', 'transcript': transcript, 'uncertain': False}],
                    response='The port in that picture is labeled LAN.')
                agent._handle({'event_type': 'user_audio_chunk', 'payload': {
                    'audio_ref': 'current.mp3', 'end_of_turn': True}})
                await self.complete_turn(agent)

                actions = self.drain(agent)
                self.assertNotIn('final_response', [item['action'] for item in actions])
                self.assertIn('clarification_request', [item['action'] for item in actions])
                self.assertTrue(any(row.get('phase') == 'acoustic' and row.get('status') == 200
                                    for row in self.planner.evidence))
                self.assertEqual(self.planner.evidence[-1]['validation_error'],
                                 'the active request image source is unavailable')

    async def test_unrelated_and_explicit_nonvisual_direct_answers_still_work(self):
        agent = self.agent()
        await self.establish_missing_frame(agent, 'missing.png')

        self.reply = decision(response='A LAN port connects a device to a local network.')
        agent._handle({'event_type': 'user_speech_chunk', 'payload': {
            'text': 'Explain generally what a LAN port does without using that picture.',
            'end_of_turn': True}})
        await self.complete_turn(agent)

        actions = self.drain(agent)
        self.assertIn('final_response', [item['action'] for item in actions])
        self.assertNotIn('validation_error', self.planner.evidence[-1])


if __name__ == '__main__':
    unittest.main()
