"""Exercise the real native voice service through THREAD's local WebSocket relay.

Uses synthetic speech paced in real time, then corrections over the same live call.
Requires the configured Gemini project to have available Live API quota.
"""
import asyncio
import base64
import json
from pathlib import Path
import time
import wave

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:8766'


def save_report(report):
    (ROOT / 'reports' / 'native-voice-check.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


async def main():
    report = {'format': 'THREAD native voice check v2', 'synthetic_speech': True, 'turns': [], 'passed':False}
    save_report(report)
    async with httpx.AsyncClient(timeout=15) as http:
        created = await http.post(BASE + '/api/sessions', json={'experience': 'voice'})
        created.raise_for_status()
        sid = created.json()['session_id']
        async with websockets.connect(BASE.replace('http:', 'ws:') + '/live/' + sid, max_size=8_000_000) as ws:
            initial = json.loads(await asyncio.wait_for(ws.recv(), 25))
            print('Native relay:', initial, flush=True)
            if initial['type'] != 'live_ready': raise RuntimeError('Native relay setup failed')
            report['model'] = initial['model']

            async def receive_turn(label, started=None, audio_end=None):
                received = {'label': label, 'captions': {}, 'first_audio_ms': None, 'interruptions': 0}
                pcm = bytearray()
                async with asyncio.timeout(30):
                    while True:
                        event = json.loads(await ws.recv())
                        if event['type'] == 'live_error': raise RuntimeError(event['text'])
                        if event['type'] == 'caption': received['captions'][event['message_id']] = {'role': event['role'], 'text': event['text']}
                        if event['type'] == 'audio':
                            if received['first_audio_ms'] is None and started:
                                received['first_audio_ms'] = round((time.perf_counter() - started) * 1000)
                                if audio_end and audio_end[0]: received['after_last_input_packet_ms'] = round((time.perf_counter() - audio_end[0]) * 1000)
                            pcm.extend(base64.b64decode(event['data']))
                        if event['type'] == 'interrupted':
                            received['interruptions'] += 1
                            # Discard a cancelled generation, including any queued audio from the prior request.
                            pcm.clear(); received['first_audio_ms'] = None
                            received['captions'] = {k:v for k,v in received['captions'].items() if v['role']=='user'}
                        if event['type'] == 'turn_complete' and pcm: break
                received['audio_seconds'] = round(len(pcm) / 48000, 2)
                received['captions'] = list(received['captions'].values())
                state = (await http.get(BASE + '/api/sessions/' + sid)).json()
                received['task'] = {k: state[k] for k in ('revision','domain','slots','selection','metrics')}
                report['turns'].append(received)
                save_report(report)
                print(json.dumps(received,ensure_ascii=True),flush=True)
                if label == 'spoken_request':
                    with wave.open(str(ROOT / 'reports' / 'native-voice-full-path.wav'), 'wb') as w:
                        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
                return received

            await receive_turn('greeting')
            with wave.open(str(ROOT / 'reports' / 'synthetic-request.wav'), 'rb') as wav:
                pcm = wav.readframes(wav.getnframes()); rate = wav.getframerate()
            assert rate == 16000
            ended = [None]
            async def stream_speech():
                await ws.send(json.dumps({'type': 'speech_start'}))
                start = time.perf_counter()
                for offset in range(0, len(pcm), 1024):
                    await ws.send(pcm[offset:offset+1024])
                    await asyncio.sleep(max(0, start + (offset+1024)/32000 - time.perf_counter()))
                ended[0] = time.perf_counter()
                await ws.send(json.dumps({'type': 'speech_end'}))
                for _ in range(45):
                    await ws.send(bytes(1024)); await asyncio.sleep(.032)
            started = time.perf_counter()
            sender = asyncio.create_task(stream_speech())
            await receive_turn('spoken_request', started, ended)
            await sender
            # The backend can publish results in a subsequent spoken response.
            await asyncio.sleep(.5)
            state = (await http.get(BASE + '/api/sessions/' + sid)).json()
            assert state['slots'].get('destination') == 'Mumbai', state['slots']
            for label, text in [('correction', 'Actually, change the destination to Delhi, on the eighth of October. Keep Chennai as the origin.'),
                                ('hotel', 'When I get there, can you book me a hotel near the airport?')]:
                await ws.send(json.dumps({'type':'text','text':text}))
                reply = await receive_turn(label,time.perf_counter())
                assert reply['audio_seconds'] > 0
                if label == 'hotel':
                    spoken = ' '.join(c['text'] for c in reply['captions'] if c['role']=='assistant').lower()
                    assert 'hotel' in spoken and any(t in spoken for t in ("can't",'cannot','unable',"don't have",'not able','not available')), spoken
                await asyncio.sleep(.6)
            state = (await http.get(BASE + '/api/sessions/' + sid)).json()
            assert state['domain'] == 'travel', state['domain']
            assert state['slots']['destination'] == 'Delhi', state['slots']
            assert state['slots']['date'].endswith('-10-08'), state['slots']
            assert state['slots'].get('after') == '21:00', 'The unchanged departure-time restriction was lost.'
            assert state['metrics']['submitted_creates'] == 0
            await ws.send(json.dumps({'type':'end'}))
        export = (await http.get(BASE + '/api/sessions/' + sid + '/export')).json()
        (ROOT / 'reports' / 'native-voice-session.json').write_text(json.dumps(export,indent=2,ensure_ascii=False),encoding='utf-8')
    report['passed'] = True
    report['limits'] = 'Real service with synthetic speech; output chunks received by Python, not physical microphone or speaker measurements. Text corrections test semantic continuity over the same voice connection.'
    save_report(report)


if __name__ == '__main__': asyncio.run(main())
