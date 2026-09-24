"""Offline read-only release probes; usage: python -B this_file.py CHECKOUT_OR_PACKAGE.

Injects proposals and synthetic media/results, never provider calls or device actions.
Outputs observations, not a claim about how often a live model makes these errors.
"""
import asyncio
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch
import wave

sys.dont_write_bytecode = True
ROOT = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(ROOT))
from participant.agent import ParticipantAgent
from participant.authorization import authorization_grant
from participant.planner import Planner, PlannerError
import httpx


@contextmanager
def offline():
    attempts = []
    connect, connect_ex, dns = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo
    def guarded(original):
        def call(sock, address):
            if isinstance(address, tuple) and address[0] in ('127.0.0.1', '::1'):
                return original(sock, address)
            attempts.append('connect')
            raise RuntimeError('External network disabled')
        return call
    def lookup(host, *args, **kwargs):
        if host in (None, 'localhost', '127.0.0.1', '::1', b'localhost', b'127.0.0.1', b'::1'):
            return dns(host, *args, **kwargs)
        attempts.append('dns')
        raise RuntimeError('External DNS disabled')
    with patch.dict(os.environ, {}, clear=True), patch.object(socket.socket, 'connect', guarded(connect)), \
            patch.object(socket.socket, 'connect_ex', guarded(connect_ex)), patch.object(socket, 'getaddrinfo', lookup):
        yield attempts


def event(agent, kind, **payload):
    agent._handle({'event_type': kind, 'payload': payload})


def drain(agent):
    return [agent.out_queue.get_nowait() for _ in range(agent.out_queue.qsize())]


def agent_for(tools, text=None, planner=None):
    agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue(), planner=planner)
    agent._start_plan = lambda: None
    event(agent, 'tool_manifest', tools=tools)
    if text is not None:
        event(agent, 'user_speech_chunk', text=text, end_of_turn=True)
    drain(agent)
    return agent


def decision(calls=(), observations=(), response=None):
    return {'intent': 'probe', 'slots': {}, 'tool_calls': list(calls),
            'observations': list(observations), 'clarification': None, 'response': response}


def primitive(text, args, descriptor=None):
    field = next(iter(args))
    tool = {'kind': 'state_modifying', 'description': f'Set {field} for a customer.',
            'args': {field: descriptor or {'type': 'number'}, 'customer': {'type': 'string'}}}
    name = 'set_' + field
    agent = agent_for({name: tool}, text)
    step = {'api_name': name, 'args': args, 'authorization': {'quote': text, 'message_index': 0},
            'response_template': 'Updated.'}
    proposal = decision([step])
    Planner._validate(proposal, [], agent.tools)
    agent._apply(proposal)
    return {'text': text, 'args': args, 'grant': authorization_grant(step, tool, [(0, text)]),
            'actions': drain(agent)}


def bound_write(result_value=2000):
    text = 'Read the sensor for lab. Then set limit 2 for Nia.'
    tools = {'read_sensor': {'kind': 'read_only', 'args': {'location': {'type': 'string'}}},
             'set_limit': {'kind': 'state_modifying', 'description': 'Set a limit for a customer.',
                           'args': {'limit': {'type': 'integer'}, 'customer': {'type': 'string'}}}}
    agent = agent_for(tools, text)
    step = {'api_name': 'read_sensor', 'args': {'location': 'lab'}, 'response_template': '',
            'after_result': {'api_name': 'set_limit', 'args': {'customer': 'Nia'},
                             'bindings': {'limit': 'temperature'},
                             'authorization': {'quote': 'set limit 2 for Nia.'},
                             'response_template': 'Updated.'}}
    proposal = decision([step])
    Planner._validate(proposal, [], tools)
    agent._apply(proposal)
    event(agent, 'tool_result', call_id='call-1', api_name='read_sensor', status='success',
          result={'temperature': result_value})
    return {'text': text, 'proposal': step, 'actions': drain(agent)}


def completion(raw, finish='STOP'):
    candidate = {'content': {'parts': [{'text': raw}]}}
    if finish is not None:
        candidate['finishReason'] = finish
    return httpx.Response(200, json={'candidates': [candidate]})


async def main_json_matrix():
    tools = {'read_record': {'kind': 'read_only', 'args': {'name': {'type': 'string'}}}}
    good = json.dumps(decision([{'api_name': 'read_record', 'args': {'name': 'sample'},
                                'response_template': '{name}'}]))
    variants = {'valid': (good, 'STOP'), 'missing_finish': (good, None),
                'truncated_finish': (good, 'MAX_TOKENS'), 'truncated_json': (good[:-1], 'STOP'),
                'trailing_document': (good + '{}', 'STOP'),
                'duplicate_root': ('{"clarification":"Stop",' + good[1:], 'STOP'),
                'duplicate_argument': (good.replace('"name": "sample"', '"name":"bad","name":"sample"'), 'STOP'),
                'escaped_duplicate': (good.replace('"name": "sample"', '"name":"bad","\\u006eame":"sample"'), 'STOP')}
    output = {}
    with patch.dict(os.environ, {'THREAD_API_KEY': 'offline-only', 'PARTICIPANT_PREWARM': '0',
                                 'PARTICIPANT_IMAGE_EMBEDDING': '0'}, clear=True):
        for label, (raw, finish) in variants.items():
            planner = Planner(transport=httpx.MockTransport(lambda req: completion(raw, finish)))
            await planner.setup()
            agent = agent_for(tools, 'Read sample.', planner)
            try:
                proposal = await planner.plan(agent._context())
                agent._apply(proposal)
                output[label] = {'accepted': True, 'actions': drain(agent)}
            except PlannerError:
                output[label] = {'accepted': False, 'actions': drain(agent)}
            finally:
                await planner.close()
    assert output['valid']['accepted'] and all(not row['accepted'] for key, row in output.items() if key != 'valid')
    return output


async def media_probe(mode):
    visual = mode.startswith('image_')
    duplicate = mode == 'acoustic_duplicate'
    missing_finish = mode == 'acoustic_missing_finish'
    text = 'What is the port in that picture?' if visual else 'Set amount 2 for Nia.'
    if mode == 'image_text_paraphrase':
        text = 'Look up a manual for the port I showed you.'
    tools = ({'manual': {'kind': 'read_only', 'args': {'query': {'type': 'string'}}}} if visual else
             {'set_amount': {'kind': 'state_modifying', 'description': 'Set amount for a customer.',
                             'args': {'amount': {'type': 'number'}, 'customer': {'type': 'string'}}}})
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            'THREAD_API_KEY': 'offline-only', 'PARTICIPANT_PREWARM': '0',
            'PARTICIPANT_IMAGE_EMBEDDING': '0', 'PARTICIPANT_MEDIA_ROOT': directory}, clear=True):
        with wave.open(str(Path(directory) / 'sample.wav'), 'wb') as stream:
            stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            stream.writeframes(b'\0\0' * 1600)
        audio = mode == 'image_audio' or not visual
        index = 2 if visual else 0
        row = {'message_index': index, 'type': 'audio', 'transcript': text, 'uncertain': False}
        step = ({'api_name': 'manual', 'args': {'query': 'LAN'},
                 'response_template': 'The printed LAN port is described by {records.0.title}.'} if visual else
                {'api_name': 'set_amount', 'args': {'amount': 2, 'customer': 'Nia'},
                 'authorization': {'quote': text, 'message_index': index}, 'response_template': 'Updated.'})
        reply = decision([step], [row] if audio else [])
        acoustic_raw = json.dumps({'observations': [row]})
        if duplicate:
            acoustic_raw = acoustic_raw.replace('"uncertain": false', '"uncertain":true,"uncertain":false')
        if mode == 'acoustic_uncertain':
            acoustic_raw = acoustic_raw.replace('"uncertain": false', '"uncertain": true')
        requests = []
        def handle(request):
            body = json.loads(request.content)
            acoustic = body['systemInstruction']['parts'][0]['text'].startswith('Transcribe the actual')
            requests.append('acoustic' if acoustic else 'main')
            finish = None if acoustic and missing_finish else 'STOP'
            if acoustic and mode == 'acoustic_max_tokens':
                finish = 'MAX_TOKENS'
            return completion(acoustic_raw if acoustic else json.dumps(reply), finish)
        planner = Planner(transport=httpx.MockTransport(handle))
        await planner.setup()
        agent = agent_for(tools, planner=planner)
        if visual:
            event(agent, 'video_frame', image_ref='missing.png')
            event(agent, 'user_speech_chunk', text='Tell me an unrelated fact.', end_of_turn=True)
            requested_reply, reply = reply, decision(response='An unrelated offline fact.')
            agent._apply(await planner.plan(agent._context()))
            reply = requested_reply
        if audio:
            event(agent, 'user_audio_chunk', audio_ref='sample.wav', end_of_turn=True)
        else:
            event(agent, 'user_speech_chunk', text=text, end_of_turn=True)
        drain(agent)
        try:
            proposal = await planner.plan(agent._context())
            agent._apply(proposal)
            if visual and agent.operations:
                event(agent, 'tool_result', call_id='call-1', api_name='manual', status='success',
                      result={'records': [{'title': 'LAN connector manual'}]})
            result = {'accepted': True, 'decision': proposal}
        except PlannerError:
            result = {'accepted': False}
        finally:
            await planner.close()
        return {**result, 'mode': mode, 'text': text, 'acoustic_raw': acoustic_raw if audio else None,
                'requests': requests, 'actions': drain(agent), 'records': planner.evidence}


async def main():
    with offline() as attempts:
        result = {
            'source': str(ROOT),
            'decimal_truncation': primitive('Set amount to 2.50 for Nia.', {'amount': 2, 'customer': 'Nia'}),
            'decimal_exact_rejected': primitive('Set amount=2.5 for Nia.', {'amount': 2.5, 'customer': 'Nia'}),
            'nested_confirmation_rejected': primitive(
                'Set payment.amount=2 and payment.tax=50 for Nia.',
                {'payment': {'amount': 2, 'tax': 50}, 'customer': 'Nia'},
                {'type': 'object', 'properties': {'amount': {'type': 'number'}, 'tax': {'type': 'number'}}}),
            'wrong_target': primitive('Set limit=2 for Nia. Tell Omar about it.', {'limit': 2, 'customer': 'Omar'}),
            'enum_override': primitive('Set mode safe for Nia.', {'mode': 'dangerous', 'customer': 'Nia'},
                                       {'type': 'string', 'enum': ['safe', 'dangerous']}),
            'bound_result_override': bound_write(),
            'main_json': await main_json_matrix(),
            'media': [await media_probe(mode) for mode in
                      ('image_text', 'image_text_paraphrase', 'image_audio', 'acoustic_duplicate', 'acoustic_missing_finish',
                       'acoustic_valid', 'acoustic_uncertain', 'acoustic_max_tokens')],
            'external_network_attempts': attempts,
        }
        assert not attempts
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
