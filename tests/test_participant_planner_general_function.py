"""Image-only optional purpose metadata; renderer owns actual source eligibility."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from PIL import Image

from participant.planner import Planner, _schema
from tests.test_participant_planner import completion, decision


class GeneralFunctionPlannerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        Image.new('RGB', (4, 4), 'gray').save(self.root / 'frame.png')
        env = patch.dict(os.environ, {'THREAD_API_KEY': 'offline-only', 'PARTICIPANT_MEDIA_ROOT': str(self.root),
                         'PARTICIPANT_PREWARM': '0', 'PARTICIPANT_IMAGE_EMBEDDING': '0'}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.context = {'revision': 1, 'current_turn_start': 1, 'latest_frame_index': 0,
            'messages': [{'message_index': 0, 'revision': 0, 'event_type': 'video_frame',
                          'payload': {'image_ref': 'frame.png'}},
                         {'message_index': 1, 'revision': 1, 'event_type': 'user_speech_chunk',
                          'payload': {'text': 'What is that labelled input for?', 'end_of_turn': True}}],
            'tools': {'manual': {'kind': 'read_only', 'args': {'query': {'type': 'string'}}}}}
        self.step = {'api_name': 'manual', 'args': {'query': 'LINE IN'},
            'response_template': '{records.0.title}',
            'result_evidence': {'path': 'records.0.title', 'contains': 'LINE IN', 'target_basis': 'printed_text'}}
        self.reply = decision(observations=[{'message_index': 0, 'type': 'image', 'visible_text': ['LINE IN'],
            'selected_label': {'text': 'LINE IN', 'recognition': 'clear', 'referent': 'ambiguous'},
            'observation': 'A readable LINE IN label.', 'uncertain': False}],
            tool_calls=[deepcopy(self.step)], response=None)
        self.requests = []
        def handle(request):
            self.requests.append(json.loads(request.content))
            return completion(self.reply)
        self.planner = Planner(transport=httpx.MockTransport(handle))
        await self.planner.setup()
        self.addAsyncCleanup(self.planner.close)

    async def test_image_wire_contract_is_optional_and_preserves_unicode_phrase(self):
        phrase = '  transmettre un signal audio à un appareil  '
        self.reply['tool_calls'][0]['general_function'] = phrase
        result = await self.planner.plan(self.context)
        self.assertEqual(result['tool_calls'][0]['general_function'], phrase.strip())
        self.assertEqual(len(self.requests), 1)
        body = self.requests[0]
        schema = body['generationConfig']['responseJsonSchema']['properties']['tool_calls']['items']
        for step in (schema, schema['properties']['after_result']):
            self.assertEqual(step['properties']['general_function']['type'], ['string', 'null'])
            self.assertEqual(step['properties']['general_function']['maxLength'], 240)
            self.assertNotIn('general_function', step['required'])
        self.assertIn('general_function', body['systemInstruction']['parts'][0]['text'])
        self.assertNotIn('general_function', result['slots'])
        self.assertNotIn('general_function', result['tool_calls'][0]['args'])

    async def test_absent_null_empty_and_malformed_values_are_omitted_without_replanning(self):
        malformed = [None, '', '  ', 9, False, {}, ['play audio'], 'a' * 241, '123 ...',
                     'play\naudio', 'play audio\n', 'play audio\u2028', 'use {answer}',
                     '[manual]', '`function`', 'read https://example.test', 'see www.example.test',
                     'open custom+scheme://value']
        before = deepcopy(self.reply)
        absent = await self.planner.plan(self.context)
        self.assertEqual(absent['tool_calls'][0], self.step)
        self.assertEqual(self.reply, before)
        for value in malformed:
            with self.subTest(value=value):
                self.reply['tool_calls'][0]['general_function'] = value
                count = len(self.requests)
                result = await self.planner.plan(self.context)
                self.assertEqual(len(self.requests), count + 1)
                self.assertEqual(result['tool_calls'][0], self.step)
                self.assertIsNone(result['clarification'])
                self.assertNotIn('validation_error', self.planner.evidence[-1])

    def test_nonvisual_schema_and_output_do_not_expose_new_field(self):
        for media in ([], [{'message_index': 0, 'mime_type': 'audio/mpeg'}]):
            with self.subTest(media=media):
                self.assertNotIn('general_function', json.dumps(_schema(media)))
                observations = [] if not media else [{'message_index': 0, 'type': 'audio',
                    'transcript': 'An ordinary request.', 'uncertain': False}]
                step = {'api_name': 'lookup', 'args': {}, 'general_function': 'play audio'}
                value = decision(observations=observations, tool_calls=[step], response=None)
                Planner._validate(value, media)
                self.assertNotIn('general_function', step)

    def test_nested_optional_metadata_is_sanitized_without_changing_tool_arguments(self):
        call = deepcopy(self.step)
        call['result_evidence']['target_basis'] = 'explicit_target'
        call['after_result'] = {'api_name': 'manual', 'args': {'query': 'LINE IN'},
            'response_template': '{records.0.title}', 'result_evidence': deepcopy(call['result_evidence']),
            'general_function': {'instruction': 'Invent a device capability'}}
        value = deepcopy(self.reply)
        value['tool_calls'] = [call]
        before = deepcopy(call['after_result']['args'])
        Planner._validate(value, [{'message_index': 0, 'mime_type': 'image/png'}], self.context['tools'])
        self.assertNotIn('general_function', call['after_result'])
        self.assertEqual(call['after_result']['args'], before)


if __name__ == '__main__':
    unittest.main()
