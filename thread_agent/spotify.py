"""Local-development Spotify connection. OAuth tokens stay in expiring relay memory.

Only the verified PhoneBridge calls perform(). No unauthenticated playback route.
The connection handle is an opaque capability stored by the Android client, never
included in a model prompt, card, URL, exported trace or provider error message.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import re
import secrets
import time
from urllib.parse import urlencode

import httpx

REDIRECT = os.environ.get('THREAD_SPOTIFY_REDIRECT', 'http://127.0.0.1:8766/api/spotify/callback')
SCOPES = 'user-top-read user-read-playback-state user-modify-playback-state'
PERIODS = {'short_term': 'last four weeks', 'medium_term': 'last six months', 'long_term': 'last year'}


def object_field(value, key):
    field = value.get(key) if isinstance(value, dict) else None
    return field if isinstance(field, dict) else {}


class SpotifyFailure(Exception):
    def __init__(self, detail, status='failed'):
        self.detail, self.status = detail, status


class SpotifyConnections:
    def __init__(self, *, transport=None):
        self.connections = {}
        self.transport = transport

    def _get(self, handle):
        for key, connection in list(self.connections.items()):
            if connection['expires'] < time.monotonic(): self.connections.pop(key, None)
        return self.connections.get(handle)

    def begin(self, client_id):
        if not isinstance(client_id, str) or not re.fullmatch(r'[A-Za-z0-9]{32}', client_id):
            raise ValueError('Enter the public 32-character client ID from your Spotify Developer app.')
        self._get('')
        if len(self.connections) >= 12: raise ValueError('Too many pending Spotify connections. Disconnect one or restart the local relay.')
        handle, state, verifier = (secrets.token_urlsafe(32) for _ in range(3))
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        self.connections[handle] = {'client_id': client_id, 'state': state, 'verifier': verifier,
                                    'expires': time.monotonic() + 600, 'lock': asyncio.Lock()}
        query = urlencode({'client_id': client_id, 'response_type': 'code', 'redirect_uri': REDIRECT,
                           'scope': SCOPES, 'state': state, 'code_challenge_method': 'S256', 'code_challenge': challenge})
        return {'connection_handle': handle, 'url': 'https://accounts.spotify.com/authorize?' + query, 'redirect_uri': REDIRECT}

    def status(self, handle):
        connection = self._get(handle)
        return {'connected': bool(connection and connection.get('access_token')),
                'pending': bool(connection and connection.get('state')), 'local_development': True}

    def disconnect(self, handle):
        self.connections.pop(handle, None)

    def clear(self):
        self.connections.clear()

    async def _request(self, method, url, **kwargs):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5), transport=self.transport, follow_redirects=False) as client:
                response = await client.request(method, url, **kwargs)
        except httpx.HTTPError:
            raise SpotifyFailure('Spotify did not confirm the request. Check playback before trying again.', 'unknown') from None
        if response.status_code == 401: raise SpotifyFailure('Spotify access expired or was revoked. Reconnect Spotify.', 'needs_connection')
        if response.status_code == 403: raise SpotifyFailure('Spotify refused this action. Check Premium, the developer app user list and the granted permissions.')
        if response.status_code == 404: raise SpotifyFailure('No active Spotify playback device. Start Spotify on the device you want, then make a fresh request.', 'needs_device')
        if response.status_code == 429: raise SpotifyFailure('Spotify has reached its request allowance. Wait before making a new request; this action was not retried.')
        if not 200 <= response.status_code < 300: raise SpotifyFailure('Spotify did not accept this request. No successful outcome was confirmed.', 'unknown' if response.status_code >= 500 else 'failed')
        if response.status_code == 204 or not response.content: return {}
        try:
            value = response.json()
            if not isinstance(value, dict): raise ValueError()
            return value
        except (ValueError, UnicodeError): raise SpotifyFailure('Spotify returned an unreadable response. Check the current playback state.', 'unknown') from None

    async def complete(self, state, code, error=''):
        self._get('')
        connection = next((c for c in self.connections.values() if c.get('state') and secrets.compare_digest(c['state'], state)), None)
        if not connection: raise ValueError('This Spotify sign-in is expired or was already used. Start Connect Spotify again.')
        connection.pop('state') # One callback only, including denied and failed exchanges.
        if error or not code:
            connection.pop('verifier', None)
            raise ValueError('Spotify access was not granted. Return to THREAD to connect again.')
        verifier = connection.pop('verifier')
        token = await self._request('POST', 'https://accounts.spotify.com/api/token', data={
            'grant_type': 'authorization_code', 'code': code, 'redirect_uri': REDIRECT,
            'client_id': connection['client_id'], 'code_verifier': verifier})
        if not token.get('access_token') or not token.get('refresh_token'): raise ValueError('Spotify did not return a complete connection. Connect again.')
        if not set(SCOPES.split()).issubset(set(token.get('scope', '').split())): raise ValueError('Spotify did not grant all requested playback/history permissions.')
        # A disconnect during the exchange cannot resurrect the removed connection.
        if not any(c is connection for c in self.connections.values()): raise ValueError('This Spotify connection was disconnected.')
        connection.update(access_token=token['access_token'], refresh_token=token['refresh_token'],
                          token_expires=time.monotonic() + min(int(token.get('expires_in', 3600)), 3600) - 30,
                          expires=time.monotonic() + 14400)

    async def perform(self, handle, action, args, check_current, progress=lambda steps: None):
        steps = []
        wrote = False
        confirmed_effect = False
        title = 'Spotify'
        def step(label, status='completed'):
            steps.append({'label': label, 'status': status})
            progress(list(steps))
        def outcome(status, detail):
            return {'status': status, 'detail': detail, 'title': title, 'steps': steps, 'provider': 'Spotify'}
        connection = self._get(handle)
        if not connection or not connection.get('access_token'):
            return outcome('needs_connection', 'Connect Spotify in THREAD Settings, then repeat your request. Connecting will not start playback automatically.')
        try:
            async with connection['lock']:
                def current():
                    check_current()
                    if self._get(handle) is not connection: raise ValueError('Spotify was disconnected.')
                current()
                if connection['token_expires'] < time.monotonic():
                    token = await self._request('POST', 'https://accounts.spotify.com/api/token', data={
                        'grant_type': 'refresh_token', 'refresh_token': connection['refresh_token'], 'client_id': connection['client_id']})
                    current()
                    if not token.get('access_token'): raise SpotifyFailure('Reconnect Spotify to renew playback access.', 'needs_connection')
                    connection.update(access_token=token['access_token'], refresh_token=token.get('refresh_token', connection['refresh_token']),
                                      token_expires=time.monotonic() + min(int(token.get('expires_in', 3600)), 3600) - 30)
                headers = {'Authorization': 'Bearer ' + connection['access_token']}
                async def api(method, path, **kwargs):
                    current()
                    result = await self._request(method, 'https://api.spotify.com/v1/' + path, headers=headers, **kwargs)
                    current()
                    return result
                playback = await api('GET', 'me/player')
                device = object_field(playback, 'device')
                if not device.get('id') or not device.get('is_active') or device.get('is_restricted'):
                    return outcome('needs_device', 'Start Spotify on the device you want to use, then make a fresh request. THREAD did not choose or transfer to another device.')
                device_id = device['id']
                device_name = str(device.get('name', 'active Spotify device'))[:100]
                async def verify(predicate):
                    for attempt in range(3):
                        if attempt: await asyncio.sleep(.25 * attempt)
                        value = await api('GET', 'me/player')
                        if object_field(value, 'device').get('id') == device_id and predicate(value): return True
                    return False
                async def write(path, **kwargs):
                    nonlocal wrote
                    current()
                    # Spotify player endpoints have no idempotency key. Never retry writes.
                    wrote = True
                    return await api('PUT', path, params={'device_id': device_id, **kwargs.pop('params', {})}, **kwargs)
                if action == 'spotify_top_track':
                    period = args.get('time_range', 'medium_term')
                    if period not in PERIODS or type(args.get('repeat')) is not bool: raise ValueError('Invalid Spotify selection.')
                    top = await api('GET', 'me/top/tracks', params={'time_range': period, 'limit': 1})
                    track = next(iter(top.get('items') or []), {})
                    if not isinstance(track, dict): track = {}
                    uri = track.get('uri', '')
                    if not re.fullmatch(r'spotify:track:[A-Za-z0-9]{22}', uri): return outcome('failed', 'Spotify did not return a playable top track for this period.')
                    title = str(track.get('name', 'Your top Spotify track'))[:160]
                    step('Found ' + title + ' · ' + PERIODS[period])
                    await write('me/player/play', json={'uris': [uri]})
                    if not await verify(lambda p: p.get('is_playing') is True and object_field(p, 'item').get('uri') == uri):
                        step('Playback not confirmed', 'unknown')
                        return outcome('unknown', 'Spotify accepted the play request, but the requested track was not confirmed on ' + device_name + '. Repeat was not changed. Check Spotify; the action was not retried.')
                    step('Playing on ' + device_name)
                    confirmed_effect = True
                    if args['repeat']:
                        await write('me/player/repeat', params={'state': 'track'})
                        if not await verify(lambda p: p.get('repeat_state') == 'track' and p.get('is_playing') is True and object_field(p, 'item').get('uri') == uri):
                            step('Repeat not confirmed', 'unknown')
                            return outcome('partial', title + ' started playing, but repeat-one was not confirmed. Check Spotify.')
                        step('Repeat one verified')
                    return outcome('completed', f'{title} is playing on {device_name}' + (' with repeat one.' if args['repeat'] else '.') + f' Spotify ranked it highest by affinity for the {PERIODS[period]}, not an exact play count.')
                if action != 'spotify_control': raise ValueError('Unsupported Spotify workflow.')
                command = args.get('command')
                if command not in ('pause', 'resume', 'repeat_one', 'repeat_off'): raise ValueError('Unsupported Spotify control.')
                if command in ('pause', 'resume'):
                    await write('me/player/' + ('pause' if command == 'pause' else 'play'))
                    matches = lambda p: p.get('is_playing') is (command == 'resume')
                    detail = ('Paused' if command == 'pause' else 'Resumed') + ' Spotify on ' + device_name + '.'
                else:
                    repeat = 'track' if command == 'repeat_one' else 'off'
                    await write('me/player/repeat', params={'state': repeat})
                    matches = lambda p: p.get('repeat_state') == repeat
                    detail = ('Repeat one is on' if repeat == 'track' else 'Repeat is off') + ' on ' + device_name + '.'
                if not await verify(matches):
                    step('New playback state not confirmed', 'unknown')
                    return outcome('unknown', 'Spotify accepted the request, but the new state was not confirmed. Check Spotify before retrying.')
                step(detail)
                return outcome('completed', detail)
        except asyncio.CancelledError:
            # Return effect uncertainty so a caller cannot treat cancelled transport as rollback.
            return outcome('partial' if confirmed_effect else 'unknown' if wrote else 'cancelled', 'The task stopped. Check Spotify for any already submitted playback change.' if wrote else 'Stopped before changing Spotify playback.')
        except ValueError:
            return outcome('partial' if confirmed_effect else 'unknown' if wrote else 'cancelled', 'The request changed. Remaining steps stopped; check Spotify for any playback already started.' if wrote else 'The request changed or the account disconnected. Playback was not started.')
        except SpotifyFailure as exc:
            step(exc.detail, exc.status)
            return outcome('partial' if confirmed_effect else exc.status, exc.detail)


spotify = SpotifyConnections()
