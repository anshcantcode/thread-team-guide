"""Local client transport for the current FDB controller and real checklist storage.

The browser/Android client owns its checklist and admits each command against a
fresh input token. This host owns recognition, planning and outcome accounting.
WebSocket PCM is an application transport, not a benchmark WebRTC measurement.
"""
from __future__ import annotations

import asyncio
import base64
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import re
import threading
import time
import uuid
from urllib.parse import urlparse

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from thread_agent.fdb3 import ControllerBridge
from thread_agent.fdb3_extension import ExtensionPlanner, TOOLS as EXTENSION_TOOLS, validate_arguments

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = frozenset({'read_checklist', 'add_checklist_item', 'set_checklist_item'})
TOOLS = {name: {**deepcopy(EXTENSION_TOOLS[name]), 'delay_range_ms': [0, 20000]} for name in ALLOWED}
IDENTITY = re.compile(r'^[a-f0-9]{32}$')
TOKEN = re.compile(r'^[A-Za-z0-9_-]{1,100}$')


def valid_hello(message):
    return (isinstance(message, dict) and message.get('type') == 'hello'
            and isinstance(message.get('session_id'), str) and bool(IDENTITY.fullmatch(message['session_id']))
            and isinstance(message.get('input_token'), str) and bool(TOKEN.fullmatch(message['input_token']))
            and message.get('client') in {'android', 'browser'})


def local_endpoint(value):
    parsed = urlparse(value)
    if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'} or parsed.username or parsed.password:
        raise ValueError('The checkpoint client host supports only a local HTTP planner endpoint')
    return value.rstrip('/')


class ClientRegistry:
    """Synchronous bridge adapter; all socket I/O runs on the event loop.

    A lost receipt is unknown. We never retry the effect. Late matching receipts
    remain in the journal and are shown to the client, but cannot authorize a
    different operation or turn.
    """
    def __init__(self, loop, send, session_id, input_token, *, timeout=20, on_late_receipt=None):
        self.loop, self.send, self.session_id = loop, send, session_id
        self.input_token, self.input_sequence = input_token, 0
        self.timeout = timeout
        self.connection_id = uuid.uuid4().hex
        self.state_lock = threading.Lock()
        self.pending = {}
        self.records = []
        self.closed = False
        self.used_tokens = {input_token}
        self.on_late_receipt = on_late_receipt

    def input_started(self, input_sequence):
        with self.state_lock:
            self.input_sequence = input_sequence

    def new_input(self, token):
        if not isinstance(token, str) or not TOKEN.fullmatch(token):
            raise ValueError('Invalid input token')
        with self.state_lock:
            if token in self.used_tokens:
                raise ValueError('Each new input requires a fresh token')
            self.used_tokens.add(token)
            self.input_token = token

    def call_with_context(self, name, args, *, call_id, revision, input_sequence):
        if name not in ALLOWED:
            return {'status': 'error', 'error': 'invalid_args', 'detail': 'This client does not expose that action.'}
        try:
            validate_arguments(name, args)
        except ValueError:
            return {'status': 'error', 'error': 'invalid_args', 'detail': 'The action arguments are invalid.'}
        with self.state_lock:
            if self.closed or input_sequence != self.input_sequence:
                return {'status': 'error', 'error': 'invalid_args', 'detail': 'The request changed before submission.'}
            token = self.input_token
        # A controller call identity is scoped by connection, so reconnecting
        # cannot collide with a previous conversation's call-1.
        request_id = uuid.uuid5(uuid.UUID(hex=self.connection_id), str(call_id)).hex
        request = {'type': 'tool_request', 'request_id': request_id, 'session_id': self.session_id,
                   'input_token': token, 'command': name, 'args': deepcopy(args)}
        future = asyncio.run_coroutine_threadsafe(self.exchange(request, input_sequence, revision, call_id), self.loop)
        try:
            return future.result(timeout=self.timeout + 3)
        except Exception:
            # Do not retry or cancel an already-submitted client operation.
            return {'status': 'error', 'error': 'outcome_unknown',
                    'detail': 'The device outcome could not be confirmed. Check the saved checklist before trying again.'}

    async def exchange(self, request, sequence, revision, call_id):
        with self.state_lock:
            if self.closed or sequence != self.input_sequence or request['input_token'] != self.input_token:
                return {'status': 'error', 'error': 'invalid_args', 'detail': 'The request changed before submission.'}
        future = self.loop.create_future()
        record = {**deepcopy(request), 'revision': revision, 'call_id': call_id,
                  'submitted_at': time.time(), 'outcome': 'unknown'}
        self.records.append(record)
        self.pending[request['request_id']] = (request, future, record)
        try:
            await self.send(request)
            result = await asyncio.wait_for(asyncio.shield(future), self.timeout)
        except (TimeoutError, WebSocketDisconnect, RuntimeError, OSError):
            result = {'status': 'error', 'error': 'outcome_unknown',
                      'detail': 'No device receipt arrived. Inspect the saved checklist; this action was not retried.'}
            record['outcome'] = 'unknown'
            record['timed_out'] = True
        return result

    async def receive(self, message):
        entry = self.pending.get(message.get('request_id'))
        if entry is None:
            return False
        request, future, record = entry
        result = message.get('result')
        if (message.get('session_id') != self.session_id or message.get('input_token') != request['input_token']
                or not isinstance(result, dict) or result.get('status') not in {'success', 'error'}
                or not isinstance(result.get('detail'), str)
                or result.get('request_id') != request['request_id'] or result.get('session_id') != self.session_id):
            return False
        if record.get('receipt') is not None:
            return result == record['receipt']  # A conflicting duplicate never replaces known outcome.
        record.update(outcome=result['status'], receipt=deepcopy(result), received_at=time.time())
        if not future.done():
            future.set_result(deepcopy(result))
        # The synchronous caller can time out while the event loop is stalled,
        # before exchange's own timeout fires. Reconcile every first receipt;
        # the bridge callback only changes an actually unknown prior outcome.
        if self.on_late_receipt:
            await self.on_late_receipt(record, deepcopy(result))
        await self.send({'type': 'receipt', 'tool': request['command'], 'args': request['args'],
                         'request_id': request['request_id'], 'result': result})
        return True

    def close(self):
        with self.state_lock:
            self.closed = True
        for _, future, _ in self.pending.values():
            if not future.done():
                future.set_result({'status': 'error', 'error': 'outcome_unknown',
                                   'detail': 'The connection closed before an outcome was confirmed.'})


async def typed_response(bridge, registry, session, send, text, token):
    # Bridge.submit does not yield while admitting the input. Check before that
    # admission as well as before speech; a scheduled stale task gets no turn.
    if registry.closed or registry.input_token != token:
        return
    try:
        response = await bridge.response(text, timeout=90)
        if response and not registry.closed and registry.input_token == token:
            await send({'type': 'caption', 'role': 'assistant', 'text': response, 'message_id': uuid.uuid4().hex})
            if registry.input_token == token:
                session.say(response, allow_interruptions=True)
    except TimeoutError:
        if registry.input_token == token:
            await send({'type': 'live_error', 'text': 'The controller did not finish. Check the checklist for any recorded outcome.'})


async def reconcile_receipt(bridge, record, result):
    """Settle a timed-out effect without repeating it or reviving its continuation."""
    execution = bridge.executions.get(record['call_id'])
    if execution:
        await asyncio.shield(execution)
    await bridge.synchronize()
    operation = bridge.controller.operations.get(record['call_id'])
    call = next((row for row in bridge.calls if row['call_id'] == record['call_id']), None)
    if (not operation or not call or operation['api_name'] != record['command']
            or operation['revision'] != record['revision']
            or call.get('result', {}).get('error') != 'outcome_unknown'):
        return
    # Only unknown writes can be settled again by the controller. A read's
    # terminal error stays terminal; its late receipt still belongs in the log.
    operation['continuation_retired'] = True
    call['previous_result'] = deepcopy(call['result'])
    call.update(outcome=result['status'], result=deepcopy(result), reconciled_at=time.time())
    bridge._journal_tool('late_receipt', call)
    await bridge.incoming.put({'event_type': 'tool_result', 'payload': {
        'call_id': record['call_id'], 'api_name': record['command'],
        'status': result['status'], 'result': deepcopy(result)}})
    await bridge.synchronize()


def audio_sink(send):
    from livekit.agents.voice import io as voice_io

    class SocketAudio(voice_io.AudioOutput):
        def __init__(self):
            super().__init__(label='client PCM', sample_rate=24000,
                             capabilities=voice_io.AudioOutputCapabilities(pause=False))
            self.identity = None
            self.seconds = 0.
            self.sent = {}
            self.acknowledged = {}
            self.tasks = set()

        def schedule(self, coro):
            task = asyncio.create_task(coro)
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

        def finish_ready(self):
            # SDK segment completion has no IDs; preserve capture order even
            # when client acknowledgements arrive out of order.
            while self.sent:
                identity = next(iter(self.sent))
                if identity not in self.acknowledged:
                    break
                self.sent.pop(identity)
                seconds, interrupted = self.acknowledged.pop(identity)
                self.on_playback_finished(playback_position=seconds, interrupted=interrupted)

        async def capture_frame(self, frame):
            await super().capture_frame(frame)
            if self.identity is None:
                self.identity = uuid.uuid4().hex
            self.seconds += frame.samples_per_channel / frame.sample_rate
            await send({'type': 'audio', 'data': base64.b64encode(bytes(frame.data)).decode('ascii'),
                        'sample_rate': frame.sample_rate, 'message_id': self.identity})
            await asyncio.sleep(frame.samples_per_channel / frame.sample_rate)

        def flush(self):
            super().flush()
            if self.identity is None:
                return
            identity, seconds = self.identity, self.seconds
            self.sent[identity] = seconds
            self.identity, self.seconds = None, 0.
            async def finish():
                await send({'type': 'turn_complete', 'message_id': identity})
                await asyncio.sleep(10)
                if identity in self.sent:
                    self.acknowledged.setdefault(identity, (0, True))
                    self.finish_ready()
            self.schedule(finish())

        def acknowledge(self, message):
            if message.get('status') not in {'played', 'interrupted'}:
                return
            identity = message.get('message_id')
            maximum = self.sent.get(identity)
            seconds = message.get('seconds')
            if maximum is None or type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
                return
            self.acknowledged.setdefault(identity, (min(seconds, maximum),
                message.get('status') == 'interrupted' or message.get('interrupted') is not False or seconds + .12 < maximum))
            self.finish_ready()

        def clear_buffer(self):
            super().flush()
            count = len(self.sent) + int(self.identity is not None)
            self.identity, self.seconds = None, 0.
            self.sent.clear()
            self.acknowledged.clear()
            for _ in range(count):
                self.on_playback_finished(playback_position=0, interrupted=True)
            self.schedule(send({'type': 'interrupted', 'recoverable': False}))

        def close(self):
            for task in tuple(self.tasks):
                task.cancel()

    return SocketAudio()


def create_app(*, whisper_path=None, endpoint='http://127.0.0.1:8098/v1', model='Qwen3.5-4B'):
    endpoint = local_endpoint(endpoint)
    app = FastAPI(title='THREAD Kitchen', docs_url=None, redoc_url=None)
    active = asyncio.Lock()
    selected = Path(whisper_path) if whisper_path else None

    @app.get('/api/status')
    async def status():
        return {'available': bool(selected and (selected / 'model.bin').is_file()), 'busy': active.locked(),
                'mode': 'host-backed FDB controller', 'transport': 'WebSocket PCM / LiveKit AgentSession',
                'storage': 'this browser or Android device', 'paid_requests': 0,
                'details': 'A local planner and pinned recognizer are required. Benchmark WebRTC runs use the separate reproduction command.'}

    @app.get('/')
    @app.get('/fdb3')
    async def page():
        return FileResponse(ROOT / 'web/fdb3.html')

    @app.websocket('/voice')
    async def voice(socket: WebSocket):
        # Local binding alone is not a cross-origin defense: reject a malicious
        # remote web page trying to reach a localhost microphone/tool service.
        origin = socket.headers.get('origin')
        if origin and urlparse(origin).hostname not in {'127.0.0.1', 'localhost', '::1'}:
            await socket.close(code=1008)
            return
        await socket.accept()
        if active.locked():
            await socket.send_json({'type': 'live_error', 'text': 'The local controller is in use. Close the other conversation first.'})
            await socket.close(code=1013)
            return
        async with active:
            lock = asyncio.Lock()
            closed = False
            async def send(message):
                if closed:
                    return
                async with lock:
                    await socket.send_json(message)
            registry = planner = bridge = session = sink = None
            background = set()
            queue = asyncio.Queue(maxsize=150)
            try:
                hello = await asyncio.wait_for(socket.receive_json(), 10)
                if not valid_hello(hello):
                    raise ValueError('A valid client hello is required')
                if selected is None:
                    raise ValueError('Start the host with --whisper pointing to the pinned local model')
                from scripts.fdb3_config import verify_whisper, apply_environment
                apply_environment()
                await asyncio.to_thread(verify_whisper, selected)
                from livekit import rtc
                from thread_agent.fdb3_voice import WhisperSTT, ThreadVoiceAgent, FrameInput, create_session, input_prompt
                registry = ClientRegistry(asyncio.get_running_loop(), send, hello['session_id'], hello['input_token'])
                planner = ExtensionPlanner(endpoint, model)
                bridge = ControllerBridge(TOOLS, registry, planner)
                registry.on_late_receipt = lambda record, result: reconcile_receipt(bridge, record, result)
                recognizer = await asyncio.to_thread(WhisperSTT, selected, prompt=input_prompt(tools=TOOLS))
                session = create_session(bridge, recognizer)
                sink = audio_sink(send)
                async def frames():
                    while True:
                        token, data = await queue.get()
                        if token != registry.input_token:
                            continue
                        yield rtc.AudioFrame(data, 16000, 1, len(data) // 2)
                session.input.audio = FrameInput(frames())
                session.output.audio = sink
                def schedule(coro):
                    task = asyncio.create_task(coro)
                    background.add(task)
                    task.add_done_callback(background.discard)
                @session.on('conversation_item_added')
                def caption(event):
                    item = event.item
                    if getattr(item, 'role', '') in {'user', 'assistant'} and getattr(item, 'text_content', None):
                        schedule(send({'type': 'caption', 'role': item.role, 'text': item.text_content, 'message_id': item.id}))
                @session.on('error')
                def error(event):
                    schedule(send({'type': 'live_error', 'text': 'The local speech pipeline failed; no outcome is assumed.'}))
                await bridge.start()
                await session.start(agent=ThreadVoiceAgent(bridge))
                await send({'type': 'live_ready', 'session_id': registry.session_id})
                while True:
                    packet = await socket.receive()
                    if packet['type'] == 'websocket.disconnect':
                        break
                    if packet.get('bytes') is not None:
                        data = packet['bytes']
                        if not data or len(data) % 2 or len(data) > 32000:
                            raise ValueError('Expected bounded 16 kHz mono PCM16 packets')
                        queue.put_nowait((registry.input_token, data))
                        continue
                    raw = packet.get('text', '')
                    if len(raw) > 65536:
                        raise ValueError('Client message exceeds size limit')
                    message = json.loads(raw)
                    if not isinstance(message, dict):
                        raise ValueError('Client message must be an object')
                    kind = message.get('type')
                    if kind in {'speech_start', 'text'}:
                        registry.new_input(message.get('input_token'))
                        while not queue.empty():
                            queue.get_nowait()
                        bridge.speech_started()
                        await session.interrupt(force=True)
                        await send({'type': 'interrupted', 'recoverable': False})
                        if kind == 'text':
                            text = message.get('text')
                            if not isinstance(text, str) or not 1 <= len(text.strip()) <= 2000:
                                raise ValueError('A typed request must contain 1 to 2000 characters')
                            await send({'type': 'caption', 'role': 'user', 'text': text, 'message_id': uuid.uuid4().hex})
                            schedule(typed_response(bridge, registry, session, send, text, registry.input_token))
                    elif kind == 'tool_result':
                        await registry.receive(message)
                    elif kind == 'playback':
                        sink.acknowledge(message)
                    elif kind == 'end':
                        break
                    elif kind != 'speech_end':
                        raise ValueError('Unsupported client message')
            except WebSocketDisconnect:
                pass
            except Exception as exc:
                try:
                    await send({'type': 'live_error', 'text': f'The local session stopped ({type(exc).__name__}). Check host setup; no success is inferred.'})
                except (RuntimeError, WebSocketDisconnect):
                    pass
            finally:
                closed = True
                if registry:
                    registry.close()
                for task in tuple(background):
                    task.cancel()
                await asyncio.gather(*background, return_exceptions=True)
                if session:
                    await session.aclose()
                if bridge:
                    await bridge.close()
                if planner:
                    await planner.close()
                if sink:
                    sink.close()
                try:
                    await socket.close()
                except (RuntimeError, WebSocketDisconnect):
                    pass
    app.mount('/static', StaticFiles(directory=ROOT / 'web'), name='static')
    return app
