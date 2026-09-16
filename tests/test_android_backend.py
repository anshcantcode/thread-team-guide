"""Portable Android engine boundaries; run in both desktop and phone Python envs."""
import io
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from thread_agent.android_backend import configure, record_voice_metrics
from thread_agent.capabilities import Notebook
from thread_agent.fixtures import PACKS
from thread_agent.live import tool_schema
from thread_agent.protocol import Change, InputEvent, Interpretation, Manifest, ToolSpec
from thread_agent.server import app, sessions


class PortableModelsTests(unittest.TestCase):
    def test_rejects_coercions_at_nested_authority_boundaries(self):
        invalid = [
            (InputEvent, {'id': 'x', 'type': 'text', 'data': [['forged', True]]}),
            (InputEvent, {'id': 12, 'type': 'text'}),
            (InputEvent, {'id': 'x', 'type': 'text', 'data': {12: True}}),
            (Interpretation, {'intent': 'revise', 'remove': [12]}),
            (Interpretation, {'intent': 'revise', 'changes': [[['slot', 'x'], ['value', True]]]}),
            (Interpretation, {'intent': 'revise', 'changes': [{'slot': 12, 'value': True}]}),
        ]
        for model, value in invalid:
            with self.subTest(model=model.__name__, value=value), self.assertRaises(ValueError):
                model.model_validate(value)

    def test_required_any_native_values_and_extra_policies(self):
        with self.assertRaises(ValueError): Change(slot='x')
        for value in (None, False, 1, 1.25, '1', ['x', 1], {'native': [False, None]}):
            self.assertEqual(Change(slot='x', value=value).value, value)
            self.assertIs(type(Change(slot='x', value=value).value), type(value))
        self.assertNotIn('extra', Change(slot='x', value=None, extra=True).model_dump())
        samples = [(Interpretation, {'intent': 'revise'}), (InputEvent, {'id': 'x', 'type': 'text'}),
                   (Manifest, next(iter(PACKS.values())).model_dump()),
                   (ToolSpec, next(iter(PACKS.values())).tools[0].model_dump())]
        for model, value in samples:
            with self.subTest(model=model.__name__), self.assertRaises(ValueError):
                model.model_validate({**value, 'extra': True})

    def test_complete_identifiers_and_uncached_live_schemas(self):
        manifest = next(iter(PACKS.values())).model_dump()
        for invalid in ('valid\n', 'Valid', 'a' * 41):
            with self.subTest(id=invalid), self.assertRaises(ValueError):
                Manifest.model_validate({**manifest, 'id': invalid})
        tool = manifest['tools'][0]
        with self.assertRaises(ValueError): ToolSpec.model_validate({**tool, 'name': 'valid\n'})
        schema = Interpretation.model_json_schema()
        self.assertIn('value', schema['$defs']['Change']['required'])
        schema['$defs']['Change']['properties'].clear()
        self.assertIn('value', Interpretation.model_json_schema()['$defs']['Change']['properties'])
        self.assertEqual(tool_schema(), tool_schema())


class PhoneBoundaryTests(unittest.TestCase):
    def test_native_auth_covers_http_and_both_sockets_without_leaking_key(self):
        token = 'test-local-' * 6
        with patch.dict(os.environ, THREAD_EMBEDDED='android', THREAD_LOCAL_TOKEN=token, THREAD_API_KEY='phone-test-key'), TestClient(app) as client:
            before = len(sessions)
            for path in ('/', '/api/config', '/api/sessions/missing/export', '/docs', '/openapi.json'):
                self.assertEqual(client.get(path).status_code, 401)
            self.assertEqual(client.post('/api/sessions', json={}).status_code, 401)
            self.assertEqual(len(sessions), before)
            auth = {'X-Thread-Local': token}
            config = client.get('/api/config', headers=auth)
            self.assertEqual(config.json()['runtime'], 'phone')
            self.assertNotIn(token, config.text)
            self.assertNotIn('phone-test-key', config.text)
            self.assertEqual(client.get('/api/config', headers={**auth, 'Origin': 'https://example.com'}).status_code, 403)
            sid = client.post('/api/sessions', json={}, headers=auth).json()['session_id']
            for path in ('/live/', '/ws/'):
                for headers in ({}, {'X-Thread-Local': 'wrong'}):
                    with self.subTest(path=path), self.assertRaises(WebSocketDisconnect) as denied:
                        with client.websocket_connect(path + sid, headers=headers): pass
                    self.assertEqual(denied.exception.code, 1008)
            with client.websocket_connect('/ws/' + sid, headers=auth) as socket:
                self.assertEqual(socket.receive_json()['type'], 'history')
            export = client.get(f'/api/sessions/{sid}/export', headers=auth).text
            self.assertNotIn(token, export)
            self.assertNotIn('phone-test-key', export)
            # Browser callback is public, but a made-up state cannot connect an account.
            callback = client.get('/api/spotify/callback?state=forged&code=forged')
            self.assertEqual(callback.status_code, 200)
            self.assertIn('was not connected', callback.text)

    def test_phone_fails_closed_without_token_and_handles_non_ascii_header(self):
        from starlette.requests import Request
        from thread_agent.server import local_client
        request = Request({'type': 'http', 'headers': [(b'x-thread-local', b'\xff')]})
        with patch.dict(os.environ, THREAD_EMBEDDED='android', THREAD_LOCAL_TOKEN=''):
            self.assertFalse(local_client(request))
        with patch.dict(os.environ, THREAD_LOCAL_TOKEN='safe-token'):
            self.assertFalse(local_client(request))

    def test_configuration_is_whitelisted_and_rejects_partial_updates(self):
        with patch.dict(os.environ):
            configure(json.dumps({'THREAD_API_KEY': 'example-key', 'THREAD_LOCAL_URL': 'https://untrusted.invalid'}))
            self.assertEqual(os.environ['THREAD_PROVIDER'], 'gemini')
            self.assertEqual(os.environ['THREAD_API_KEY'], 'example-key')
            self.assertNotEqual(os.environ.get('THREAD_LOCAL_URL'), 'https://untrusted.invalid')
            with self.assertRaises(ValueError):
                configure(json.dumps({'THREAD_API_KEY': 'replacement', 'THREAD_MODEL': 'bad\nmodel'}))
            self.assertEqual(os.environ['THREAD_API_KEY'], 'example-key')
            configure('{}')
            self.assertEqual(os.environ['THREAD_API_KEY'], '')

    def test_notebook_survives_new_instance_in_app_private_directory(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, THREAD_DATA_DIR=directory):
            Notebook().save('phone-persistence-test', {'title': 'Portable note', 'body': 'Same engine, local storage.'})
            self.assertEqual(Notebook().path, Path(directory) / 'notebook.sqlite3')
            self.assertEqual(Notebook().search('Portable')[0]['id'], 'phone-persistence-test')

    def test_release_metrics_are_content_free_and_phone_only(self):
        output = io.StringIO()
        counters = {'input_audio_seconds': 16.5, 'generated_audio_seconds': 0.0, 'connected_seconds': 19.0}
        with patch.dict(os.environ, THREAD_EMBEDDED='android'), redirect_stdout(output): record_voice_metrics(counters)
        self.assertEqual(json.loads(output.getvalue().removeprefix('THREAD_VOICE_METRICS ')), counters)
        output = io.StringIO()
        with patch.dict(os.environ, THREAD_EMBEDDED=''), redirect_stdout(output): record_voice_metrics(counters)
        self.assertEqual(output.getvalue(), '')


if __name__ == '__main__': unittest.main()
