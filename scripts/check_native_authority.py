"""Real-model transcription through the native owned-PCM authority path.

Injects a delayed booking caption and requested commit for every case. Expected
words never enter the transcriber. All service effects are fictional. This tests
the authority boundary with actual ASR, not the Live model's choice of function.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from thread_agent.engine import Session
from thread_agent.fixtures import TRAVEL, lookup
from thread_agent.live import LiveConversation
from thread_agent.planner import ModelPlanner, settings
from thread_agent.protocol import InputEvent, Interpretation


class Client:
    def __init__(self): self.packets = asyncio.Queue()
    async def receive(self): return await self.packets.get()
    async def send_json(self, packet): pass


async def case_run(planner, case):
    if case.get('silence'):
        pcm = b'\0'*64000
    else:
        with wave.open(str(ROOT/'evaluation/native-audio'/f'{case["id"]}.wav'), 'rb') as wav:
            assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 16000)
            pcm = wav.readframes(wav.getnframes())
    s = Session(planner, external=True, evaluation=True, manifests={'travel': TRAVEL})
    s.sandbox.config.update(prepare_delay=.02, timeout=10)
    live = LiveConversation(s, Client())
    async def outgoing(packet): pass
    live.send = outgoing
    try:
        s.apply(Interpretation(intent='revise', domain='travel', changes=[{'slot': k, 'value': v} for k,v in {
            'origin':'Chennai', 'destination':'Delhi', 'date':'2026-09-15'}.items()]), InputEvent(id='setup',type='text'))
        read = next(iter(s.operations.values()))
        s.handle_result(read['id'], {'status':'completed', **lookup('travel',read['arguments'])}, 'lookup')
        s.apply(Interpretation(intent='select', selection=s.results['items'][0]['id']), InputEvent(id='select',type='text'))
        live.begin_input_turn('Book the selected flight.')
        for payload in [{'type':'speech_start'}, *[pcm[i:i+3200] for i in range(0,len(pcm),3200)], {'type':'speech_end'}, {'type':'end'}]:
            await live.browser.packets.put({'type':'websocket.receive', **({'bytes':payload} if isinstance(payload,bytes) else {'text':json.dumps(payload)})})
        await live.receive_browser()
        async def provider():
            yield json.dumps({'serverContent': {'inputTranscription': {'text':'Book the selected flight.'}}})
        live.upstream = provider()
        await live.receive_provider()
        started = time.perf_counter()
        result = await live.handle_tool({'id':case['id'], 'name':'update_task', 'args':{'intent':'commit', 'domain':'travel',
            'base_revision':s.revision, 'results_id':s.results['id'], 'input_token':live.input_token}})
        elapsed = round((time.perf_counter()-started)*1000,2)
        await asyncio.sleep(.06)
        writes = sum(e['type']=='tool_call' and e['effect']=='write' for e in s.trace)
        checks = {'expected_writes': writes==case['writes'], 'expected_decision':result['ok']==bool(case['writes']),
                  'owned_transcription_present': bool(live.current_user_words(verified=True)) == (not case.get('silence',False)),
                  'exact_owned_pcm': bytes(live.turn_pcm) == pcm}
        return {'id':case['id'], 'passed':all(checks.values()), 'checks':checks, 'expected_input':case.get('speech','[digital silence]'),
            'transcript':live.current_user_words(verified=True), 'pcm_sha256':hashlib.sha256(pcm).hexdigest(),
            'pcm_bytes':len(pcm), 'verification_ms':elapsed, 'writes':writes, 'result':result, 'trace':s.trace}
    finally:
        if live.authority_task:
            live.authority_task.cancel()
            await asyncio.gather(live.authority_task, return_exceptions=True)
        await s.close()


async def main(interval):
    corpus = ROOT/'evaluation/native-audio.json'
    source = lambda: {str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'thread_agent').glob('*.py')}
    report = {'format':'THREAD native owned-audio authority v1', 'official_evaluation':False, 'model':settings()['model'],
        'limitations':['Synthetic English TTS, no human microphone or accent benchmark.',
            'Actual transcription model; function calls and packet order are controlled adversarial inputs.',
            'No actual phone actions or real bookings; no acoustic latency measurement.'],
        'source_sha256_at_start':source(), 'corpus_sha256':hashlib.sha256(corpus.read_bytes()).hexdigest(),
        'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'cases':[], 'completed':False}
    planner = ModelPlanner()
    destination = ROOT/'reports/theme5-native-authority-actual-model.json'
    try:
        cases = json.loads(corpus.read_text())['cases']
        for case in cases:
            row = await case_run(planner, case)
            report['cases'].append(row)
            report['completed'] = len(report['cases']) == len(cases)
            report['passed'] = report['completed'] and all(r['passed'] for r in report['cases'])
            report['source_sha256_at_report'] = source()
            report['source_changed_during_run'] = report['source_sha256_at_start'] != source()
            destination.write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps({k:v for k,v in row.items() if k not in ('trace','result')}),flush=True)
            if not report['completed']: await asyncio.sleep(interval)
    finally: await planner.close()
    return report['passed']


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interval',type=float,default=12)
    raise SystemExit(0 if asyncio.run(main(parser.parse_args().interval)) else 1)
