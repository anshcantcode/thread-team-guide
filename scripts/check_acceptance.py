"""Actual model acceptance run; uses configured API quota and synthetic media.

Expected answers stay outside model context. Initial task state is explicit test
setup, not a claim that a previous conversation succeeded. No real effects occur.
"""
import argparse
import asyncio
import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from thread_agent.adapter import parse_event
from thread_agent.engine import Session
from thread_agent.fixtures import PACKS
from thread_agent.planner import ModelPlanner, settings
from thread_agent.protocol import Interpretation, InputEvent, Manifest


def plan(domain, **slots):
    return Interpretation(intent='revise', domain=domain, changes=[
        {'slot': k, 'value': v if isinstance(v, str) else json.dumps(v)} for k, v in slots.items()])


async def settle(s):
    await s.inputs.join()
    while s.tasks:
        await asyncio.gather(*list(s.tasks), return_exceptions=False)


async def run_case(planner, case, date, manifests):
    s = Session(planner, evaluation=True, manifests=manifests, date=date)
    s.sandbox.config.update(read_delay=.01, write_delay=.02, prepare_delay=.04, timeout=.15)
    original_read = s.sandbox.read
    async def mock_read(domain, args):
        if case.get('lookup_result') is not None and domain == case.get('lookup_domain', domain):
            return deepcopy(case['lookup_result'])
        if domain == 'aurora':
            return {'status': 'completed', 'items': [{'id': 'LAB-A', 'title': 'North Ridge research lab'}],
                    'source': 'Aurora internal synthetic inventory', 'summary': 'One fictional field-lab slot is available.'}
        return await original_read(domain, args)
    s.sandbox.read = mock_read
    try:
        initial = case.get('initial', '')
        if case.get('initial_state'):
            declared = case['initial_state']
            s.apply(plan(declared['domain'], **declared['slots']), InputEvent(id='setup', type='text'))
        elif 'travel' in initial:
            s.apply(plan('travel', origin='Chennai', destination='Delhi', date='2026-09-15', after='18:00'), InputEvent(id='setup', type='text'))
        elif initial == 'rooms':
            s.apply(plan('rooms', date='2026-09-17', after='14:00', people=8, duration_minutes=60, projector=True), InputEvent(id='setup', type='text'))
        elif initial == 'device_power':
            s.apply(plan('device', model='THREAD R1', indicator='power', symptom='blinking amber'), InputEvent(id='setup', type='text'))
        await settle(s)
        if 'select_index' in case.get('initial_state', {}):
            index = case['initial_state']['select_index']
            s.apply(Interpretation(intent='select', selection=s.results['items'][index]['id']), InputEvent(id='setup-select', type='text'))
        if initial in ('selected_travel', 'created_travel'):
            s.apply(Interpretation(intent='select', selection=s.results['items'][0]['id']), InputEvent(id='setup-select', type='text'))
        if initial == 'created_travel':
            s.apply(Interpretation(intent='commit'), InputEvent(id='setup-authorize', type='text'))
            await settle(s)
        before = len(s.trace)
        before_effects = len(s.sandbox.creations)
        event = {'id': case['id'], 'type': 'text' if case['mode'] == 'text' else case['mode'], 'text': case.get('text', '')}
        media_hash = None
        if case['mode'] == 'frame':
            content = (ROOT/case['image']).read_bytes()
            event['data'] = {'mime': 'image/png', 'base64': base64.b64encode(content).decode()}
        elif case['mode'] == 'audio':
            if case.get('silence'):
                buffer = io.BytesIO()
                with wave.open(buffer, 'wb') as wav:
                    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
                    wav.writeframes(b'\0'*64000)
                content = buffer.getvalue()
            else:
                content = (ROOT/case.get('audio', f'evaluation/audio/{case["id"]}.wav')).read_bytes()
            event['data'] = {'mime': 'audio/wav', 'base64': base64.b64encode(content).decode()}
        if 'data' in event: media_hash = hashlib.sha256(content).hexdigest()
        local_silence = False
        if case['mode'] == 'audio':
            from thread_agent.media import digital_silence
            local_silence = digital_silence(event['data'])
        started_ms = (s.clock.now()-s.start_time)*1000
        await s.accept(parse_event(event))
        timed_out = False
        try:
            await asyncio.wait_for(settle(s), 60)
        except asyncio.TimeoutError:
            timed_out = True
        trace = s.trace[before:]
        expected = case['expect']
        new_writes = len(s.sandbox.creations)-before_effects
        checks = {'expected_effect_count': new_writes == expected['writes'],
                  'expected_cancellation_calls': sum(e['type'] == 'tool_call' and s.operations.get(e.get('call_id'), {}).get('purpose') == 'cancel' for e in trace) == expected.get('cancellations', 0),
                  'no_provider_or_input_error': not timed_out and not any(e['type'] in ('provider_error', 'input_error') for e in trace)}
        for slot, value in expected.get('slots', {}).items():
            checks['slot:'+slot] = s.slots.get(slot) == value
        for slot in expected.get('absent', []): checks['absent:'+slot] = slot not in s.slots
        for slot in expected.get('not_true', []): checks['not_true:'+slot] = s.slots.get(slot) is not True
        for key in ('domain', 'paused', 'speech_muted'):
            if key in expected: checks[key] = getattr(s, key) == expected[key]
        if 'lookup_calls' in expected:
            checks['lookup_calls'] = len([e for e in trace if e['type'] == 'tool_call' and e['effect'] == 'read']) == expected['lookup_calls']
        if 'comparison_slots' in expected:
            checks['comparison_requested'] = any(op.get('comparison') and all(op['arguments'].get(key) == value for key, value in expected['comparison_slots'].items()) for op in s.operations.values())
        if 'evidence_page' in expected:
            checks['manual_locator'] = bool(s.results) and s.results.get('evidence', {}).get('page') == expected['evidence_page']
        intent = next((e['intent'] for e in trace if e['type'] == 'intent_interpreted'), None)
        if 'intents' in expected:
            checks['intent'] = bool(intent) and intent['intent'] in expected['intents']
        if 'action_status' in expected:
            checks['action_status'] = any(o['purpose'] == 'create' and o['status'] == expected['action_status'] for o in s.operations.values())
        if case['mode'] == 'audio':
            checks['audio_transcript_present'] = bool(intent) and bool(intent.get('transcript', '').strip())
        def first_timing(predicate):
            event = next((e for e in trace if predicate(e)), None)
            return round(event['at_ms']-started_ms, 2) if event else None
        return {'id': case['id'], 'mode': case['mode'], 'passed': all(checks.values()), 'checks': checks,
            'provider_unavailable': any(e['type'] == 'provider_error' and any(word in e['text'].lower() for word in ('quota', 'rate limit', 'could not reach', 'api key', 'model is unavailable')) for e in trace),
            'input': case.get('text') or case.get('speech') or '[synthetic silence]', 'initial': initial,
            'media_sha256': media_hash, 'intent': intent, 'new_effects': new_writes, 'state': s.summary(),
            'digital_silence_handled_locally': local_silence,
            'responses': [e['text'] for e in trace if e['type'] in ('speak', 'clarify', 'final')],
            'timing_ms': {'progress_ack': first_timing(lambda e: e['type'] == 'speak' and e.get('stage') == 'processing'),
                          'interpreted': first_timing(lambda e: e['type'] == 'intent_interpreted'),
                          'first_substantive_action': first_timing(lambda e: e['type'] in ('speak', 'clarify', 'final') and e.get('stage') != 'processing' and e.get('speak'))},
            'trace': trace}
    finally:
        await s.close()


async def main(ids, interval, corpus_path, output=None):
    corpus_path = Path(corpus_path).resolve()
    corpus = json.loads(corpus_path.read_text(encoding='utf-8'))
    manifests = deepcopy(PACKS)
    for path in corpus.get('manifest_files', ['evaluation/aurora-manifest.json']):
        extra = Manifest.model_validate_json((ROOT/path).read_text()).check()
        manifests[extra.id] = extra
    planner = ModelPlanner()
    source_hashes = {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'thread_agent').glob('*.py')}
    report = {'format': 'THREAD actual-model acceptance v1', 'official_evaluation': False,
        'created_utc': datetime.now(timezone.utc).isoformat(), 'provider': settings()['provider'], 'model': settings()['model'],
        'corpus_sha256': hashlib.sha256(corpus_path.read_bytes()).hexdigest(), 'source_sha256_at_start': source_hashes,
        'corpus_file': str(corpus_path.relative_to(ROOT)).replace('\\', '/'),
        'expected_case_count': sum(not ids or case['id'] in ids for case in corpus['cases']), 'completed': False,
        'manifest_sha256': {path: hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in corpus.get('manifest_files', ['evaluation/aurora-manifest.json'])},
        'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'corpus_scope': corpus.get('scope', 'Authored development cases, not Samsung scenarios.'),
        'limitations': ['Author-supplied synthetic media; no accent/population or microphone benchmark. Inspect the recorded fixture paths and hashes.',
                       'Test preconditions are declared state; they are not earlier model successes.',
                       'Semantic expectations are checked automatically; responses are retained for independent qualitative review.',
                       'This is the headless model path, not the native Gemini Live model.'], 'cases': []}
    model_slug = ''.join(c for c in settings()['model'] if c.isalnum() or c in '.-_')
    destination = Path(output).resolve() if output else ROOT/'reports'/('theme5-acceptance-'+model_slug+'-'+('subset' if ids else 'full')+'.json')
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        for case in corpus['cases']:
            if ids and case['id'] not in ids: continue
            result = await run_case(planner, case, corpus['date'], manifests)
            report['cases'].append(result)
            report['completed'] = len(report['cases']) == report['expected_case_count']
            report['passed'] = report['completed'] and all(c['passed'] for c in report['cases'])
            report['source_sha256_at_report'] = {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'thread_agent').glob('*.py')}
            report['source_changed_during_run'] = source_hashes != report['source_sha256_at_report']
            destination.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding='utf-8')
            print(json.dumps({'id': result['id'], 'passed': result['passed'], 'failed_checks': [k for k, v in result['checks'].items() if not v], 'timing_ms': result['timing_ms']}), flush=True)
            if result['provider_unavailable']:
                report['interrupted_by_provider'] = True
                report['unexecuted_cases'] = [c['id'] for c in corpus['cases'] if (not ids or c['id'] in ids) and c['id'] not in {r['id'] for r in report['cases']}]
                destination.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding='utf-8')
                print('Provider unavailable. Stopping this run; unexecuted cases are not passes.', flush=True)
                break
            await asyncio.sleep(interval)
    finally:
        await planner.close()
    print(f'{sum(c["passed"] for c in report["cases"])}/{len(report["cases"])} passed: {destination}', flush=True)
    return report['passed']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ids', default='', help='Optional comma-separated subset; never replaces the full run report.')
    parser.add_argument('--interval', type=float, default=10, help='Seconds between API calls to respect quota.')
    parser.add_argument('--corpus', type=Path, default=ROOT/'evaluation/corpus.json', help='Frozen development or independent corpus file.')
    parser.add_argument('--output', type=Path, help='Explicit evidence destination; use a new name for an independent first run.')
    args = parser.parse_args()
    raise SystemExit(0 if asyncio.run(main(set(filter(None, args.ids.split(','))), args.interval, args.corpus, args.output)) else 1)
