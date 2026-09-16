"""Real Gemini Live planning; simulated device outcomes, explicitly not a phone hardware test."""
import asyncio
import json
from pathlib import Path
import time

import httpx
import websockets

BASE = 'http://127.0.0.1:8766'
REPORT = Path(__file__).resolve().parents[1] / 'reports' / 'android-voice-contract.json'


async def main():
    report = {'passed': False, 'scope': 'Actual Gemini Live relay and public weather. Device executor outcomes are simulated; no physical phone action occurs in this script.', 'cases': []}
    def save(): REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    try:
        async with httpx.AsyncClient(timeout=45) as http:
            reply = await http.post(BASE + '/api/sessions', json={'experience': 'voice'}); reply.raise_for_status()
            sid = reply.json()['session_id']; report['session_id'] = sid
            async with websockets.connect(BASE.replace('http', 'ws') + '/live/' + sid + '?client=android', max_size=8_000_000) as ws:
                async def settle(label, expected=None):
                    audio, last, complete, captions, actions = 0, time.monotonic(), False, {}, []
                    async with asyncio.timeout(70):
                        while True:
                            try:
                                event = json.loads(await asyncio.wait_for(ws.recv(), .5)); last = time.monotonic()
                                if event['type'] == 'live_error': raise RuntimeError(event['text'])
                                if event['type'] == 'audio': audio += len(event['data']); complete = False
                                if event['type'] == 'caption': captions[event['message_id']] = {'role': event['role'], 'text': event['text']}
                                if event['type'] == 'device_action':
                                    actions.append(event)
                                    await ws.send(json.dumps({'type': 'device_result', 'request_id': event['request_id'], 'result': {'status': 'prepared' if event['action'] == 'create_widget' else 'handed_off', 'detail': 'SIMULATED device executor: widget preview prepared.' if event['action'] == 'create_widget' else 'SIMULATED device executor: Clock received the request.'}}))
                                if event['type'] == 'turn_complete': complete = True
                            except asyncio.TimeoutError:
                                if complete and audio and time.monotonic() - last > 1.5:
                                    state = (await http.get(BASE + '/api/sessions/' + sid)).json()
                                    if any(o['status'] == 'running' and not o.get('obsolete') for o in state['operations']): continue
                                    if expected and not any(a['action'] == expected for a in actions): continue
                                    row = {'case': label, 'audio_base64_bytes': audio, 'captions': list(captions.values()), 'device_requests': actions, 'passed': True}
                                    report['cases'].append(row); save(); print(label, 'passed', flush=True); return row
                await settle('Android tool configuration accepted with native audio greeting')
                await ws.send(json.dumps({'type': 'text', 'text': 'Set an alarm for five.'}))
                ambiguous = await settle('Ambiguous five requires clarification')
                assert not ambiguous['device_requests'], 'Ambiguous alarm was sent to the device'
                spoken = ' '.join(c['text'] for c in ambiguous['captions'] if c['role'] == 'assistant').lower()
                assert any(word in spoken for word in ('am', 'pm', 'morning', 'evening')), spoken
                await ws.send(json.dumps({'type': 'text', 'text': 'Five PM. Label it THREAD contract check.'}))
                alarm = await settle('Resolved 5 PM generates correct native Clock request', 'set_alarm')
                assert alarm['device_requests'][0]['arguments']['hour'] == 17
                assert alarm['device_requests'][0]['arguments']['minute'] == 0
                await ws.send(json.dumps({'type': 'text', 'text': 'Get the current weather for Tokyo, Japan and make it a home-screen widget called Tokyo today.'}))
                widget = await settle('Weather widget uses a real source result', 'create_widget')
                results = widget['device_requests'][-1]['arguments']['results']
                assert results[0]['domain'] == 'weather' and results[0]['provenance'] == 'live'
                await ws.send(json.dumps({'type': 'end'}))
            report['passed'] = True
    except Exception as exc:
        report['error'] = type(exc).__name__ + ': ' + str(exc)[:400]
        raise
    finally: save()


if __name__ == '__main__': asyncio.run(main())
