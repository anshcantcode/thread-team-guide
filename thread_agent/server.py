"""Local workspace and provisional streaming adapter. Credentials stay server-side."""
from __future__ import annotations

import asyncio
import base64
import binascii
from contextlib import asynccontextmanager
import io
import json
import os
from pathlib import Path
import time
import wave
from secrets import compare_digest

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from PIL import Image, UnidentifiedImageError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .engine import Session
from .fixtures import PACKS, MANUAL
from .capabilities import BUILTINS, safe_execute, validate
from .planner import ModelPlanner, settings
from .protocol import InputEvent
from .live import LiveConversation, VOICES
from .spotify import spotify, SpotifyFailure

ROOT = Path(__file__).resolve().parent.parent
sessions: dict[str, Session] = {}
connections: dict[str, WebSocket] = {}
senders: dict[str, asyncio.Task] = {}
live_connections: dict[str, WebSocket] = {}
planner = ModelPlanner()


@asynccontextmanager
async def lifespan(app):
    global planner
    if planner.client.is_closed: planner = ModelPlanner()
    async def expire():
        while True:
            await asyncio.sleep(60)
            for key, session in list(sessions.items()):
                if time.monotonic() - session.last_activity > 7200:
                    if key in connections:
                        await connections[key].close(code=4000, reason='Session expired')
                    await session.close()
                    sessions.pop(key, None)
    janitor = asyncio.create_task(expire())
    yield
    for connection in list(live_connections.values()):
        try: await connection.close()
        except (RuntimeError, WebSocketDisconnect): pass
    janitor.cancel()
    await asyncio.gather(janitor, return_exceptions=True)
    await asyncio.gather(*(s.close() for s in sessions.values()))
    sessions.clear()
    connections.clear()
    senders.clear()
    live_connections.clear()
    spotify.clear()
    await planner.close()


app = FastAPI(title='THREAD', version='0.6.0', lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])


@app.middleware('http')
async def local_origin(request: Request, call_next):
    if request.url.path != '/api/spotify/callback' and not local_client(request):
        return JSONResponse({'detail': 'This phone backend requires its native client.'}, status_code=401)
    origin = request.headers.get('origin')
    if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
        return JSONResponse({'detail': 'Cross-origin requests are not accepted.'}, status_code=403)
    if int(request.headers.get('content-length', '0')) > 10_000_000:
        return JSONResponse({'detail': 'Request too large.'}, status_code=413)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-store'
    return response


def local_client(request):
    token = os.environ.get('THREAD_LOCAL_TOKEN', '')
    if not token: return os.environ.get('THREAD_EMBEDDED') != 'android'
    return compare_digest(token.encode(), request.headers.get('x-thread-local', '').encode())


@app.get('/')
async def index():
    if os.environ.get('THREAD_EMBEDDED') == 'android':
        return JSONResponse({'app': 'THREAD', 'runtime': 'on this phone'})
    return FileResponse(ROOT / 'web' / 'index.html')


@app.get('/api/config')
async def configuration():
    config = settings()
    local=config['provider']=='local'
    return {'provider': config['provider'], 'model': 'Qwen3.5 4B' if local else config['model'], 'configured': local or bool(config['key']),
            'runtime': 'phone' if os.environ.get('THREAD_EMBEDDED') == 'android' else 'relay',
            'live': {'configured': bool(config['key']), 'provider': 'Gemini Live', 'model': config['live_model'],
                     'voice': config['live_voice'], 'voices': VOICES, 'google_search_enabled': config['live_search']},
            'timezone': config['timezone'], 'protocol': 'thread.v1 (provisional; official kit not yet supplied)',
            'manifests': [m.model_dump() for m in (PACKS | BUILTINS).values()],
            'privacy': 'During a voice connection, audio, typed messages, images and relevant task context go to Google Gemini. Weather, currency and research queries go to their named public data providers. Notes you explicitly save persist in the local THREAD notebook. Raw microphone audio is not saved. Demo services create no real bookings.'}


@app.post('/api/check')
async def check_connection():
    return await planner.health()


@app.post('/api/spotify/connect')
async def spotify_connect(request: Request):
    data = await request.json()
    if not isinstance(data, dict): raise HTTPException(400, 'Expected a Spotify client ID.')
    try: return spotify.begin(data.get('client_id'))
    except ValueError as exc: raise HTTPException(400, str(exc)) from None


@app.get('/api/spotify/status')
async def spotify_status(request: Request):
    return spotify.status(request.headers.get('x-thread-spotify', ''))


@app.delete('/api/spotify/connection')
async def spotify_disconnect(request: Request):
    spotify.disconnect(request.headers.get('x-thread-spotify', ''))
    return {'disconnected': True}


@app.get('/api/spotify/callback')
async def spotify_callback(request: Request):
    values = dict(request.query_params)
    request.scope['query_string'] = b'' # Do not put OAuth codes/state into the access log.
    try:
        await spotify.complete(values.get('state', ''), values.get('code', ''), values.get('error', ''))
        message = 'Spotify is connected. Return to THREAD and make a fresh music request. No music was started by connecting.'
    except (ValueError, SpotifyFailure):
        message = 'Spotify was not connected. Return to THREAD Settings and try connecting again.'
    return HTMLResponse('<!doctype html><html><head><meta name="viewport" content="width=device-width"><title>THREAD · Spotify</title></head>'
                        '<body style="background:#080d14;color:#f5f7fc;font:18px system-ui;padding:32px;max-width:540px">'
                        '<h1>THREAD</h1><p>' + message + '</p><p>You can close this browser tab.</p></body></html>',
                        headers={'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"})


@app.post('/api/sessions')
async def new_session(request: Request):
    if len(sessions) >= 20:
        raise HTTPException(429, 'Session limit reached. Restart the local server to clear old sessions.')
    options = await request.json()
    if not isinstance(options, dict): raise HTTPException(400, 'Expected a JSON object.')
    session = Session(planner, timezone=settings()['timezone'], external=options.get('external', False) is True)
    if options.get('experience') == 'voice':
        session.sandbox.config.update(read_delay=0.05, write_delay=0.6)
    sessions[session.id] = session
    return {'session_id': session.id, 'state': session.snapshot()}


def get_session(session_id):
    if session_id not in sessions: raise HTTPException(404, 'Session unavailable. A server restart clears session memory and sandbox records.')
    return sessions[session_id]


@app.get('/api/sessions/{session_id}')
async def get_state(session_id: str):
    return get_session(session_id).snapshot()


@app.get('/api/sessions/{session_id}/frame')
async def current_frame(session_id: str):
    media=get_session(session_id).media
    if not media: raise HTTPException(404,'No image in this session.')
    return Response(base64.b64decode(media['base64']),media_type=media['mime'])


@app.get('/api/sessions/{session_id}/export')
async def export(session_id: str):
    session = get_session(session_id)
    return JSONResponse({'format': 'THREAD session evidence v1', 'mode': 'recorded evidence; never execute as a new session',
                         'official_evaluation': False, 'summary': session.summary(), 'state': session.snapshot(),
                         'events': session.trace}, headers={'Content-Disposition': f'attachment; filename="{session_id}.json"'})


@app.get('/api/sessions/{session_id}/artifacts/{result_id}')
async def export_artifact(session_id: str, result_id: str):
    session = get_session(session_id)
    result = next((r for r in [session.results, *session.workspace.values()] if r and r['id']==result_id), None)
    if result is None: raise HTTPException(404, 'This result is not in the current workspace.')
    lines = [f'# {result["items"][0]["title"] if result["items"] else "THREAD result"}',
             f'Source: {result["source"]}', f'Status: {result.get("provenance","returned evidence").upper()}', '']
    for item in result['items']:
        draft = item.get('document')
        if draft:
            if draft.get('summary'): lines.extend([draft['summary'], ''])
            if draft.get('rows'):
                cell = lambda value: str(value).replace('|',r'\|').replace('\n',' ')
                lines.extend(['| '+' | '.join(map(cell,draft['columns']))+' |', '| '+' | '.join('---' for _ in draft['columns'])+' |',
                              *['| '+' | '.join(map(cell,row))+' |' for row in draft['rows']], ''])
            for block in draft['blocks']:
                lines.append('## '+block['heading'])
                if block.get('text'):
                    lines.extend(['````',block['text'],'````'] if draft['kind']=='code' else [block['text']])
                lines.extend(('- [ ] ' if draft['kind']=='checklist' else '- ')+entry for entry in block.get('items',[]))
                lines.append('')
        else:
            lines.extend(['## '+item['title'], *[f'{key.replace("_"," ")}: {value}' for key,value in item.items()
                         if key not in ('id','kind','title') and isinstance(value,(str,int,float,bool))], ''])
            for day in item.get('forecast',[]):
                lines.append(f'- {day["date"]}: high {day["high"]}°C, low {day["low"]}°C; rain probability {day.get("rain", "—")}%')
            for match in item.get('matches',[]):
                lines.extend([f'- {match["date"]} · {match["competition"]}: {match["home"]} {match["home_score"]} – {match["away_score"]} {match["away"]} ({match["status"]})',
                              *( [f'  Goals: {match["goals"]}; assists: {match.get("assists", "unavailable")}'] if match.get('goals') is not None else []), match['url']])
            for record in item.get('records',[]):
                lines.extend([f'- {record["date"]} · {record["title"]}: {record.get("score", "—")}',
                              '  '+str(record.get('subtitle','')),
                              '  '+'; '.join(f'{s["label"]}: {s.get("value", "unavailable")}' for s in record.get('stats',[])),
                              record.get('url','')])
    return Response('\n'.join(lines), media_type='text/markdown',
                    headers={'Content-Disposition':f'attachment; filename="THREAD-{result["domain"]}.md"'})


from .media import validate_media


async def dispatch(session, raw):
    event = InputEvent.model_validate(raw)
    if session.live_feedback is not None and event.type in ('text', 'audio', 'frame', 'partial'):
        raise ValueError('Send conversation input through the active native voice connection.')
    if session.pending_inputs >= 12 and event.type in ('text', 'audio', 'frame', 'partial'):
        raise ValueError('Several inputs are already queued. Pause or wait for interpretation to catch up.')
    validate_media(event)
    await session.accept(event)


@app.post('/api/sessions/{session_id}/events')
async def input_event(session_id: str, request: Request):
    session = get_session(session_id)
    try:
        await dispatch(session, await request.json())
    except (ValueError, KeyError, ValidationError) as exc:
        raise HTTPException(400, str(exc)) from None
    return {'accepted': True, 'state': session.snapshot()}


@app.websocket('/live/{session_id}')
async def live_voice(websocket: WebSocket, session_id: str):
    origin = websocket.headers.get('origin')
    expected = f'http://{websocket.headers.get("host")}'
    session = sessions.get(session_id)
    if not local_client(websocket) or (origin and origin != expected) or not session or session.ended or session.external or session.pending_inputs:
        await websocket.close(code=1008)
        return
    if session_id in live_connections:
        await websocket.close(code=4001, reason='Voice is already connected for this session')
        return
    await websocket.accept()
    live_connections[session_id] = websocket
    try:
        conversation = LiveConversation(session, websocket, websocket.query_params.get('voice', settings()['live_voice']),
                                        android=websocket.query_params.get('client') == 'android')
        conversation.spotify_handle = websocket.headers.get('x-thread-spotify', '') if conversation.phone else ''
        await conversation.run()
    finally:
        if live_connections.get(session_id) is websocket: live_connections.pop(session_id, None)
        try: await websocket.close()
        except (RuntimeError, WebSocketDisconnect): pass


@app.websocket('/ws/{session_id}')
async def websocket(websocket: WebSocket, session_id: str):
    origin = websocket.headers.get('origin')
    expected = f'http://{websocket.headers.get("host")}'
    if not local_client(websocket) or (origin and origin != expected):
        await websocket.close(code=1008)
        return
    session = sessions.get(session_id)
    if not session:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    previous = connections.get(session_id)
    connections[session_id] = websocket
    if previous:
        previous_sender = senders.get(session_id)
        if previous_sender:
            previous_sender.cancel()
            await asyncio.gather(previous_sender, return_exceptions=True)
        await previous.close(code=4001, reason='Session continued in another tab')
    # The history already includes undelivered events. A reconnect must not replay old speech or snapshots.
    while not session.outbox.empty():
        session.outbox.get_nowait()
        session.outbox.task_done()
    await websocket.send_json({'type': 'history', 'events': session.trace, 'state': session.snapshot()})
    async def send_events():
        while True:
            event = await session.outbox.get()
            try:
                await websocket.send_json(event)
            finally:
                session.outbox.task_done()
    sender = asyncio.create_task(send_events())
    senders[session_id] = sender
    try:
        while True:
            data = await websocket.receive_text()
            if len(data) > 9_000_000:
                await websocket.send_json({'type': 'error', 'text': 'Input exceeds the media limit.'})
                continue
            try:
                await dispatch(session, json.loads(data))
            except (ValueError, KeyError, ValidationError) as exc:
                await websocket.send_json({'type': 'error', 'text': str(exc)[:600]})
    except WebSocketDisconnect:
        pass
    finally:
        sender.cancel()
        await asyncio.gather(sender, return_exceptions=True)
        if connections.get(session_id) is websocket:
            connections.pop(session_id, None)
            senders.pop(session_id, None)
            # A disconnected interface cannot safely permit a still-prepared consequence.
            session.yield_floor()
            session.emit('client_disconnected', 'Conversation disconnected. Prepared writes held; submitted actions continue to be accounted for.')
            session.publish()


@app.get('/api/manual')
async def manual():
    return MANUAL


@app.post('/api/widgets/refresh')
async def refresh_widget(request: Request):
    """A widget reuses read-only public tools. No model, arbitrary URL or account access."""
    try: body = await request.json()
    except ValueError: raise HTTPException(400, 'Expected a widget configuration.') from None
    modules = body.get('modules') if isinstance(body, dict) else None
    if not isinstance(modules, list) or not 1 <= len(modules) <= 2:
        raise HTTPException(400, 'A widget has one or two modules.')
    allowed = {'weather', 'sports', 'web', 'currency', 'calculate', 'convert', 'dates', 'clock', 'world_clocks', 'research'}
    for module in modules:
        if not isinstance(module, dict) or module.get('domain') not in allowed:
            raise HTTPException(400, 'This content is a saved snapshot, not a refreshable source.')
        module.setdefault('arguments', {})
        try: validate(module['domain'], module['arguments'])
        except ValueError as exc: raise HTTPException(400, str(exc)[:300]) from None
    async def resolve(module):
        try: result = await asyncio.wait_for(safe_execute(module['domain'], module['arguments']), 35)
        except asyncio.TimeoutError: result = {'status': 'failed', 'error': 'The source did not respond. Previous data remains on the widget.'}
        return {**result, 'id': module.get('id', 'widget'), 'domain': module['domain'], 'arguments': module['arguments']}
    return {'results': await asyncio.gather(*(resolve(module) for module in modules))}


if os.environ.get('THREAD_EMBEDDED') != 'android':
    app.mount('/static', StaticFiles(directory=ROOT / 'web'), name='static')
