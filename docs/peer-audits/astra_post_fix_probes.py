"""Read-only, offline counterexamples against a supplied THREAD checkout."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(ROOT))
from participant.agent import ParticipantAgent
from participant.planner import Planner, PlannerError
from scripts.verify_samsung_submission import offline_environment
import httpx


def event(agent, kind, **payload):
    agent._handle({'event_type': kind, 'payload': payload})


def drain(agent):
    return [agent.out_queue.get_nowait() for _ in range(agent.out_queue.qsize())]


def agent_for(tools, text):
    agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
    agent._start_plan = lambda: None
    event(agent, 'tool_manifest', tools=tools)
    event(agent, 'user_speech_chunk', text=text, end_of_turn=True)
    drain(agent)
    return agent


def primitive_probe(text, name, field, value, quote, kind):
    tool = {'kind': 'state_modifying', 'description': f'Set {field} for a customer.',
            'args': {field: {'type': kind, 'required': True}, 'customer': {'type': 'string'}}}
    agent = agent_for({name: tool}, text)
    step = {'api_name': name, 'args': {field: value, 'customer': 'Nia'},
            'response_template': 'The setting was updated.',
            'authorization': {'quote': quote, 'message_index': 0}}
    Planner._validate({'intent': 'set', 'slots': {}, 'observations': [], 'tool_calls': [step],
                       'clarification': None, 'response': None}, [], agent.tools)
    agent._dispatch(step)
    return {'text': text, 'proposal': step, 'actions': drain(agent)}


async def late_result_probe():
    text = 'Create a note called hello. Then create a note called extra.'
    tool = {'kind': 'state_modifying', 'description': 'Create a note.',
            'args': {'text': {'type': 'string'}}}
    agent = agent_for({'create_note': tool}, text)
    step = {'api_name': 'create_note', 'args': {'text': 'hello'},
            'response_template': '',
            'authorization': {'quote': 'Create a note called hello.'},
            'after_result': {'api_name': 'create_note', 'args': {'text': 'extra'},
                             'response_template': 'The extra note was created.',
                             'authorization': {'quote': 'create a note called extra.'}}}
    assert agent._dispatch(step)
    first = drain(agent)
    agent.operations['call-1']['deadline'] = time.monotonic() - 1
    agent._ready = True
    await agent.in_queue.put({'event_type': 'tool_result', 'payload': {
        'call_id': 'call-1', 'api_name': 'create_note', 'status': 'success',
        'result': {'status': 'success', 'receipt_id': 'LATE'}}})
    task = asyncio.create_task(agent.run())
    await asyncio.sleep(.02)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    return {'initial': first, 'late_actions': drain(agent),
            'operations': list(agent.operations.values())}


def stale_read_probe():
    tool = {'kind': 'read_only', 'description': 'Fetch temperature records.',
            'args': {'location': {'type': 'string'}}}
    agent = agent_for({'read_records': tool}, 'Fetch results for Seattle.')
    agent.state = {'intent': 'read', 'slots': {'location': 'Seattle'}}
    step = {'api_name': 'read_records', 'args': {'location': 'Seattle'},
            'response_template': 'Temperature {temperature}.'}
    agent._dispatch(step)
    event(agent, 'tool_result', call_id='call-1', api_name='read_records', status='success',
          result={'temperature': 18})
    drain(agent)
    text = 'Fetch updated results for Seattle and sort those results by temperature.'
    event(agent, 'user_speech_chunk', text=text, end_of_turn=True)
    drain(agent)
    agent._dispatch(deepcopy(step))
    return {'text': text, 'actions': drain(agent), 'tool_results': agent.tool_results,
            'revision': agent.revision, 'operations': list(agent.operations.values())}


def multi_value_confirmation_probe():
    tool = {'kind': 'state_modifying', 'description': 'Set limits.',
            'args': {'limit': {'type': 'integer', 'required': True},
                     'threshold': {'type': 'integer', 'required': True},
                     'customer': {'type': 'string'}}}
    text = 'Set limit 2 and threshold 50 for Nia.'
    agent = agent_for({'set_limits': tool}, text)
    actions = []
    for quote in (text, 'Yes, set limit 2 and threshold 50 for Nia.'):
        if quote != text:
            event(agent, 'user_speech_chunk', text=quote, end_of_turn=True)
            drain(agent)
        agent._dispatch({'api_name': 'set_limits',
                         'response_template': 'The limits were updated.',
                         'args': {'limit': 2, 'threshold': 50, 'customer': 'Nia'},
                         'authorization': {'quote': quote}})
        actions.extend(drain(agent))
    return actions


async def visual_probe():
    tools = {'manual': {'kind': 'read_only', 'args': {'query': {'type': 'string'}}}}
    step = {'api_name': 'manual', 'args': {'query': 'LAN'},
            'response_template': 'The printed LAN port is described by {records.0.title}.'}
    reply = {'intent': 'manual', 'slots': {}, 'tool_calls': [step], 'observations': [],
             'clarification': None, 'response': None}
    outputs = {}
    with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {
            'THREAD_API_KEY': 'offline-only', 'PARTICIPANT_MEDIA_ROOT': root,
            'PARTICIPANT_PREWARM': '0', 'PARTICIPANT_IMAGE_EMBEDDING': '0'}, clear=True):
        def handle(request):
            return httpx.Response(200, json={'candidates': [{'finishReason': 'STOP',
                'content': {'parts': [{'text': json.dumps(reply)}]}}]})
        planner = Planner(transport=httpx.MockTransport(handle))
        await planner.setup()
        try:
            agent = agent_for(tools, 'What is the port in this picture?')
            agent.messages.insert(0, {'message_index': 0, 'revision': 1,
                'event_type': 'video_frame', 'payload': {'image_ref': 'missing.png'}})
            agent.messages[1]['message_index'] = 1
            agent._latest_frame = 0
            try:
                planned = await planner.plan(agent._context())
            except PlannerError:
                outputs['missing_without_basis'] = 'rejected'
            else:
                agent._apply(planned)
                event(agent, 'tool_result', call_id='call-1', api_name='manual', status='success',
                      result={'records': [{'title': 'LAN connector manual'}]})
                outputs['missing_without_basis'] = drain(agent)
            step['result_evidence'] = {'path': 'records.0.title', 'contains': 'LAN',
                                       'target_basis': 'printed_text'}
            try:
                await planner.plan(agent._context())
                outputs['explicit_printed_text'] = 'accepted'
            except PlannerError:
                outputs['explicit_printed_text'] = 'rejected'
        finally:
            await planner.close()
    return outputs


def replay_matrix():
    text = 'Create a note called hello.'
    tool = {'kind': 'state_modifying', 'description': 'Create a note.',
            'args': {'text': {'type': 'string'}}}
    step = {'api_name': 'create_note', 'args': {'text': 'hello'},
            'response_template': 'The note was created.',
            'authorization': {'quote': text}}
    rows = []
    for unresolved in ('pending', 'unknown', 'cancel_requested'):
        for encoding in ('interruption', 'wordless_then_text', 'wordless_then_audio',
                         'wordless_then_split', 'new_text', 'new_audio'):
            agent = agent_for({'create_note': tool}, text)
            agent._dispatch(deepcopy(step))
            first = agent.operations['call-1']
            if unresolved == 'unknown':
                event(agent, 'tool_result', call_id='call-1', api_name='create_note', status='error',
                      result={'error': 'timeout'})
            elif unresolved == 'cancel_requested':
                event(agent, 'interruption')
            if encoding == 'interruption':
                event(agent, 'interruption', text=text)
            else:
                if encoding.startswith('wordless'):
                    event(agent, 'interruption')
                if encoding.endswith('audio'):
                    index = len(agent.messages)
                    event(agent, 'user_audio_chunk', audio_ref='offline-recording', end_of_turn=True)
                    agent.observations[index] = {'type': 'audio', 'transcript': text, 'uncertain': False}
                elif encoding.endswith('split'):
                    event(agent, 'user_speech_chunk', text='Create a note ', end_of_turn=False)
                    event(agent, 'user_speech_chunk', text='called hello.', end_of_turn=True)
                else:
                    event(agent, 'user_speech_chunk', text=text, end_of_turn=True)
            agent._dispatch(deepcopy(step))
            count = len([a for a in drain(agent) if a['action'] == 'tool_call'])
            assert count == 1
            rows.append({'starting_status': unresolved, 'encoding': encoding,
                         'final_status': first['status'], 'submitted_effects': count})
    return rows


async def duplicate_key_probe():
    output = ('{"intent":"read","slots":{},"observations":[],"clarification":"Stop and ask",'
              '"tool_calls":[],"clarification":null,"tool_calls":[{"api_name":"read_record",'
              '"args":{"name":"sample"},"response_template":"{name}"}],"response":null}')
    def handle(request):
        return httpx.Response(200, json={'candidates': [{'finishReason': 'STOP',
            'content': {'parts': [{'text': output}]}}]})
    with patch.dict(os.environ, {'THREAD_API_KEY': 'offline-only', 'PARTICIPANT_PREWARM': '0',
                                 'PARTICIPANT_IMAGE_EMBEDDING': '0'}, clear=True):
        planner = Planner(transport=httpx.MockTransport(handle))
        await planner.setup()
        try:
            agent = agent_for({'read_record': {'kind': 'read_only',
                'args': {'name': {'type': 'string'}}}}, 'Read sample.')
            try:
                planned = await planner.plan(agent._context())
            except PlannerError:
                return {'raw': output, 'decision': 'rejected', 'actions': drain(agent)}
            agent._apply(planned)
            return {'raw': output, 'decision': 'accepted', 'actions': drain(agent)}
        finally:
            await planner.close()


async def main():
    with offline_environment() as attempts:
        result = {
            'numeric_quote_slice': primitive_probe('Set limit 2 and threshold 50 for Nia.',
                'set_threshold', 'threshold', 2, 'Set limit 2', 'integer'),
            'boolean_quote_slice': primitive_probe('Set alerts true and backup false for Nia.',
                'set_backup', 'backup', True, 'Set alerts true', 'boolean'),
            'late_success_queued_past_deadline': await late_result_probe(),
            'fresh_read_with_sort': stale_read_probe(),
            'multi_value_confirmation': multi_value_confirmation_probe(),
            'unavailable_frame': await visual_probe(),
            'unresolved_replay_matrix': replay_matrix(),
            'duplicate_complete_json': await duplicate_key_probe(),
            'external_network_attempts': attempts,
        }
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
