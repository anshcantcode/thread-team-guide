"""Offline checks for the opt-in, source-bound local acoustic pass."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from participant.planner import Planner


CLIPS = [(Path(__file__).parent / 'fixtures' / 'mp3' / name).read_bytes()
         for name in ('tone-cbr.mp3', 'tone-vbr.mp3')]
HEARD = ('Find option 0.', 'Use option 1.')


class FakeASR:
    def __init__(self):
        self.calls = []

    def prewarm(self):
        pass

    def transcribe(self, raw, mime_type, *, timeout):
        self.calls.append((raw, mime_type, timeout))
        index = CLIPS.index(raw)
        return {'transcript': HEARD[index], 'evidence': {
            'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
            'mime_type': mime_type}}


class LocalASRRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        for index, raw in enumerate(CLIPS):
            (self.root / f'{index}.mp3').write_bytes(raw)
        environment = patch.dict(os.environ, {
            'SECRET_GEMINI_API_KEY': 'offline-only',
            'PARTICIPANT_MEDIA_ROOT': str(self.root),
            'PARTICIPANT_ACOUSTIC_PROVIDER': 'local_whisper_cuda',
            'PARTICIPANT_PREWARM': '0',
        }, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.fake = FakeASR()

    def context(self):
        return {'messages': [
            {'message_index': index, 'revision': 1, 'event_type': 'user_audio_chunk',
             'payload': {'audio_ref': f'{index}.mp3', 'end_of_turn': index == 1}}
            for index in range(2)],
            'revision': 1, 'current_turn_start': 0,
            'tools': {'lookup': {'kind': 'read_only', 'args': {}}}}

    async def planner(self, *, main_transcripts=HEARD):
        async def handle(request):
            body = json.loads(request.content)
            self.assertNotIn('perception only', body['systemInstruction']['parts'][0]['text'])
            observations = [{'message_index': index, 'type': 'audio',
                             'transcript': transcript, 'uncertain': False}
                            for index, transcript in enumerate(main_transcripts)]
            decision = {'intent': 'lookup', 'slots': {}, 'tool_calls': [
                {'api_name': 'lookup', 'args': {}}], 'observations': observations,
                'response': None, 'clarification': None}
            return httpx.Response(200, json={'candidates': [{'finishReason': 'STOP',
                'content': {'parts': [{'text': json.dumps(decision)}]}}]})

        with patch('participant.local_asr.LocalASR', return_value=self.fake):
            planner = Planner(transport=httpx.MockTransport(handle))
            await planner.setup()
        self.addAsyncCleanup(planner.close)
        return planner

    async def test_local_pass_uses_exact_validated_bytes_and_admits_matching_plan(self):
        planner = await self.planner()
        context = self.context()
        planner.observe_input(context['messages'][0], 0)
        planner.observe_input(context['messages'][1], 0)
        decision = await planner.plan(context)
        self.assertEqual([call[0] for call in self.fake.calls], CLIPS)
        self.assertTrue(all(call[1] == 'audio/mpeg' and 0 < call[2] <= 3.5
                            for call in self.fake.calls))
        self.assertEqual([row['transcript'] for row in decision['observations']], list(HEARD))
        self.assertEqual(decision['tool_calls'][0]['api_name'], 'lookup')
        record = next(row for row in planner.evidence if row['phase'] == 'acoustic')
        self.assertEqual(record['status'], 200)
        self.assertEqual(record['provider'], 'local_whisper_cuda')
        self.assertNotIn('audio_bytes', repr(record))

    async def test_main_disagreement_vetoes_tool_and_clear_cache(self):
        planner = await self.planner(main_transcripts=('Find other option.', HEARD[1]))
        context = self.context()
        planner.observe_input(context['messages'][0], 0)
        planner.observe_input(context['messages'][1], 0)
        decision = await planner.plan(context)
        self.assertEqual(decision['tool_calls'], [])
        self.assertIsNotNone(decision['clarification'])
        self.assertTrue(any(key[0] == 0 for key in planner._audio_cache))
        self.assertTrue(all(row['uncertain'] for key, row in planner._audio_cache.items()
                            if key[0] == 0))

    async def test_tampered_audio_bytes_fail_before_recognition(self):
        planner = await self.planner()
        original = planner.media.prepare

        async def tampered(messages, *, include_audio_bytes=False):
            result = await original(messages, include_audio_bytes=include_audio_bytes)
            if include_audio_bytes:
                clean, parts, sources, audio = result
                audio[0] = {**audio[0], 'audio_bytes': CLIPS[1]}
                return clean, parts, sources, audio
            return result

        with patch.object(planner.media, 'prepare', tampered):
            decision = await planner.plan(self.context())
        self.assertEqual(decision['tool_calls'], [])
        self.assertIsNotNone(decision['clarification'])
        self.assertEqual(self.fake.calls, [])
        self.assertFalse(planner._audio_cache)


if __name__ == '__main__':
    unittest.main()
