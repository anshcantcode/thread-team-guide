import asyncio
import json
import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import AsyncMock

import httpx

from thread_agent.engine import Session
from thread_agent.live import LiveConversation
from thread_agent.phone import authorizes_phone
from thread_agent.spotify import SpotifyConnections, SCOPES


class SmartPhoneTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.session = Session(None, date='2026-09-14')
        self.live = LiveConversation(self.session, None, android=True)
        self.sent = []
        async def reply(kind, **event):
            self.sent.append(event)
            self.live.phone.result({'request_id': event['request_id'], 'result': {'status': 'handed_off', 'detail': 'Opened search destination.'}})
        self.live.client = AsyncMock(side_effect=reply)

    async def asyncTearDown(self): await self.session.close()

    async def request(self, words, action='web_search', **args):
        self.live.begin_input_turn(words)
        self.live.client_input_id = 'native-' + str(self.live.input_epoch)
        return await self.live.handle_tool({'id': 'case-' + str(self.live.input_epoch), 'name': 'phone_' + action,
            'args': {'user_request': words, 'input_token': self.live.input_token, 'base_revision': self.session.revision, **args}})

    async def test_compound_google_request_has_one_native_effect_and_local_input_binding(self):
        result = await self.request('On Google search for cat images and open the videos tab.', query='cat images', tab='videos')
        self.assertEqual(result['status'], 'handed_off')
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]['arguments'], {'query': 'cat images', 'tab': 'videos'})
        self.assertEqual(self.sent[0]['client_input_id'], 'native-1')

    async def test_tab_correction_keeps_query_even_if_model_proposes_another(self):
        await self.request('Search Google for cats.', query='cats', tab='all')
        result = await self.request('Images instead.', query='unrequested dogs', tab='images')
        self.assertTrue(result['ok'])
        self.assertEqual(self.sent[-1]['arguments'], {'query': 'cats', 'tab': 'images'})

    async def test_tab_without_current_query_and_arbitrary_url_are_rejected(self):
        self.assertFalse((await self.request('Open the videos tab.', tab='videos'))['ok'])
        self.assertFalse((await self.request('Search Google for cats.', query='cats', tab='all', url='https://evil.invalid'))['ok'])
        self.assertFalse(self.sent)

    async def test_media_search_requires_named_provider(self):
        self.assertTrue((await self.request('Search YouTube for cat videos.', 'media_search', provider='youtube', query='cat videos'))['ok'])
        self.assertFalse((await self.request('Search YouTube for cat videos.', 'media_search', provider='spotify', query='cat videos'))['ok'])

    async def test_new_search_cannot_borrow_old_query_or_substitute_a_tab(self):
        await self.request('Search Google for cats.', query='cats', tab='all')
        self.assertFalse((await self.request('Search Google for dogs.', tab='all'))['ok'])
        self.assertFalse((await self.request('Images instead.', tab='news'))['ok'])
        self.assertFalse((await self.request('Search Google for cats and open the videos tab.', query='cats', tab='images'))['ok'])
        self.assertEqual(len(self.sent), 1)

    async def test_tab_words_inside_a_query_are_data(self):
        result = await self.request('Search Google for how to open the news tab.', query='how to open the news tab', tab='all')
        self.assertEqual(result['status'], 'handed_off')
        self.assertEqual(self.sent[-1]['arguments']['tab'], 'all')

    async def test_spotify_needs_connection_and_cannot_drop_repeat_or_change_period(self):
        words = 'Open my most played on Spotify and play it on loop.'
        self.assertEqual((await self.request(words, 'spotify_top_track', time_range='medium_term', repeat=True))['status'], 'needs_connection')
        self.assertFalse((await self.request(words, 'spotify_top_track', time_range='medium_term', repeat=False))['ok'])
        self.assertFalse((await self.request('Play my top Spotify track from this month.', 'spotify_top_track', time_range='long_term', repeat=False))['ok'])
        self.assertFalse(self.sent)

    async def test_current_command_bounds_remain_strict(self):
        for words in ['Yes, that looks right.', 'My friend said play my top Spotify track.', 'Do not play my top Spotify track.',
                      'If I agree, play my top Spotify track.', 'Play my top Spotify track. Actually never mind.', 'Can you explain how to play my top Spotify track?']:
            with self.subTest(words=words): self.assertFalse(authorizes_phone('spotify_top_track', words))
        self.assertTrue(authorizes_phone('spotify_top_track', 'Play my top Spotify track on repeat.'))
        self.assertFalse((await self.request('Pause Spotify.', 'spotify_control', command='resume'))['ok'])


class SpotifyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = []
        self.current = True
        self.playing = False
        self.repeat = 'off'
        self.track = 'spotify:track:' + 'a' * 22
        self.interrupt_on_top = False
        self.timeout_play = False
        self.ignore_repeat = False
        self.null_item = False
        self.disconnect_after_write = False
        self.store = SpotifyConnections(transport=httpx.MockTransport(self.handle))
        self.connection = self.store.begin('A' * 32)
        self.handle_id = self.connection['connection_handle']
        self.state = parse_qs(urlparse(self.connection['url']).query)['state'][0]
        await self.store.complete(self.state, 'test-code')
        self.calls.clear()

    def handle(self, request):
        self.calls.append((request.method, request.url.path, dict(request.url.params), request.content))
        if request.url.path == '/api/token':
            return httpx.Response(200, json={'access_token': 'fixture-access', 'refresh_token': 'fixture-refresh', 'scope': SCOPES, 'expires_in': 3600})
        if request.url.path == '/v1/me/top/tracks':
            if self.interrupt_on_top: self.current = False
            return httpx.Response(200, json={'items': [{'uri': self.track, 'name': 'Fixture song'}]})
        if request.method == 'PUT':
            if self.disconnect_after_write: self.store.disconnect(self.handle_id)
            if request.url.path.endswith('/play'):
                if self.timeout_play: raise httpx.ReadTimeout('private provider text')
                self.playing = True
            if request.url.path.endswith('/pause'): self.playing = False
            if request.url.path.endswith('/repeat') and not self.ignore_repeat: self.repeat = request.url.params['state']
            return httpx.Response(204)
        return httpx.Response(200, json={'device': {'id': 'test-device', 'name': 'Test phone', 'is_active': True, 'is_restricted': False},
                                        'is_playing': self.playing, 'repeat_state': self.repeat, 'item': None if self.null_item else {'uri': self.track}})

    def check(self):
        if not self.current: raise ValueError('Newer input')

    async def perform(self):
        return await self.store.perform(self.handle_id, 'spotify_top_track', {'time_range': 'medium_term', 'repeat': True}, self.check)

    async def test_oauth_pkce_is_one_use_and_status_never_exposes_credentials(self):
        params = parse_qs(urlparse(self.connection['url']).query)
        self.assertEqual(params['code_challenge_method'], ['S256'])
        self.assertNotEqual(params['state'][0], self.handle_id)
        self.assertEqual(len(params['code_challenge'][0]), 43)
        self.assertEqual(self.store.status(self.handle_id), {'connected': True, 'pending': False, 'local_development': True})
        with self.assertRaises(ValueError): await self.store.complete(self.state, 'test-code')
        with self.assertRaises(ValueError): await self.store.complete('unrelated-state', 'test-code')

    async def test_top_play_repeat_requires_provider_readback_between_effects(self):
        result = await self.perform()
        self.assertEqual(result['status'], 'completed')
        writes = [c for c in self.calls if c[0] == 'PUT']
        self.assertEqual([c[1] for c in writes], ['/v1/me/player/play', '/v1/me/player/repeat'])
        play_index = self.calls.index(writes[0]); repeat_index = self.calls.index(writes[1])
        self.assertTrue(any(c[:2] == ('GET', '/v1/me/player') for c in self.calls[play_index + 1:repeat_index]))
        self.assertEqual(json.loads(writes[0][3]), {'uris': [self.track]})
        self.assertNotIn('fixture-access', json.dumps(result))

    async def test_correction_while_personal_history_is_loading_prevents_playback(self):
        self.interrupt_on_top = True
        self.assertEqual((await self.perform())['status'], 'cancelled')
        self.assertFalse(any(c[0] == 'PUT' for c in self.calls))

    async def test_lost_playback_response_never_retries_or_enables_repeat(self):
        self.timeout_play = True
        result = await self.perform()
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(len([c for c in self.calls if c[0] == 'PUT']), 1)
        self.assertNotIn('private provider text', json.dumps(result))

    async def test_repeat_not_verified_is_partial_not_success(self):
        self.ignore_repeat = True
        result = await self.perform()
        self.assertEqual(result['status'], 'partial')
        self.assertIn('repeat-one was not confirmed', result['detail'])
        self.assertEqual(len([c for c in self.calls if c[0] == 'PUT']), 2)

    async def test_nullable_playback_item_retains_an_unknown_receipt(self):
        self.null_item = True
        result = await self.perform()
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(len([c for c in self.calls if c[0] == 'PUT']), 1)
        self.assertIn('not confirmed', result['detail'])

    async def test_disconnect_prevents_new_effects(self):
        self.store.disconnect(self.handle_id)
        self.assertEqual((await self.perform())['status'], 'needs_connection')
        self.assertFalse(self.calls)

    async def test_disconnect_after_unverified_resume_is_unknown_not_partial(self):
        self.disconnect_after_write = True
        result = await self.store.perform(self.handle_id, 'spotify_control', {'command': 'resume'}, self.check)
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['steps'], [])
        self.assertEqual(len([c for c in self.calls if c[0] == 'PUT']), 1)

    async def test_oauth_expiry_and_denial_do_not_create_a_connection(self):
        pending = self.store.begin('B' * 32)
        handle = pending['connection_handle']
        state = parse_qs(urlparse(pending['url']).query)['state'][0]
        with self.assertRaises(ValueError): await self.store.complete(state, '', 'access_denied')
        self.assertFalse(self.store.status(handle)['connected'])
        self.store.connections[handle]['expires'] = 0
        with self.assertRaises(ValueError): await self.store.complete(state, 'later')

    async def test_pause_and_repeat_off_read_back_the_actual_state(self):
        self.playing = True; self.repeat = 'track'
        for command in ('pause', 'repeat_off'):
            result = await self.store.perform(self.handle_id, 'spotify_control', {'command': command}, self.check)
            self.assertEqual(result['status'], 'completed')
        self.assertFalse(self.playing); self.assertEqual(self.repeat, 'off')


if __name__ == '__main__': unittest.main()
