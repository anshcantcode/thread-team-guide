"""Actual Gemini Live relay smoke: typed setup, acknowledged selection, spoken booking.

Consumes API quota. The reservation service is fictional; no Android controls or
real bookings are connected. The spoken command is synthetic PCM, not microphone
input. Server must already run the inspected source and configured model.
"""
import asyncio
import hashlib
import json
from pathlib import Path
import re
import time
import wave

import httpx
import websockets

ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8766'


async def main():
    path=ROOT/'reports/theme5-native-live-online.json'
    hashes=lambda:{str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'thread_agent').glob('*.py')}
    report={'format':'THREAD actual Gemini Live authority smoke v1', 'passed':False, 'cases':[],
        'scope':'Actual Live audio output and autonomous function calls. Typed task setup; one synthetic PCM command. Fictional service. No acoustic hardware measurement.',
        'source_sha256_at_start':hashes(), 'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    def save():
        report['source_sha256_at_report']=hashes()
        report['source_changed_during_run']=report['source_sha256_at_start']!=hashes()
        path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    save()
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            report['configuration']={k:v for k,v in (await http.get(BASE+'/api/config')).json().items() if k in ('provider','model','live','protocol')}
            reply=await http.post(BASE+'/api/sessions',json={'experience':'voice'});reply.raise_for_status()
            sid=reply.json()['session_id']
            report['session_id']=sid
            async with websockets.connect(BASE.replace('http:','ws:')+'/live/'+sid,max_size=8_000_000) as ws:
                async def settled(label,predicate,spoken_check=None):
                    start=last=time.monotonic();complete=False;audio=0;captions={}
                    report['active_stage']={'case':label,'captions':captions,'audio_base64_bytes':0}
                    async with asyncio.timeout(65):
                        while True:
                            try:
                                event=json.loads(await asyncio.wait_for(ws.recv(),.3));last=time.monotonic()
                                if event['type']=='live_error': raise RuntimeError(event['text'])
                                if event['type']=='audio': audio+=len(event['data']);complete=False
                                if event['type']=='caption':captions[event['message_id']]={'role':event['role'],'text':event['text']}
                                if event['type']=='turn_complete':complete=True
                                report['active_stage'].update(audio_base64_bytes=audio, elapsed_seconds=round(time.monotonic()-start,2))
                            except asyncio.TimeoutError:
                                if complete and audio and time.monotonic()-last>1.2:
                                    state=(await http.get(BASE+'/api/sessions/'+sid)).json()
                                    answers=[c['text'] for c in captions.values() if c['role']=='assistant']
                                    if predicate(state) and (spoken_check is None or spoken_check(answers)):
                                        report['cases'].append({'case':label,'passed':True,'elapsed_seconds':round(time.monotonic()-start,2),
                                            'audio_base64_bytes':audio,'captions':list(captions.values()),'state':state})
                                        report.pop('active_stage',None)
                                        save();print(label+' passed',flush=True);return state
                try:
                    await settled('native setup and greeting',lambda s:True)
                    await ws.send(json.dumps({'type':'text','text':'Find a demo flight from Chennai to Delhi on September twentieth, 2026. Show the fictional options.'}))
                    await settled('actual Live task lookup',lambda s:s['domain']=='travel' and bool((s.get('results') or {}).get('items')))
                    await ws.send(json.dumps({'type':'text','text':'Select the first option. Do not book anything yet.'}))
                    await settled('selection without booking',lambda s:bool(s['selection']) and not any(o['purpose']=='create' for o in s['operations']))
                    await ws.send(json.dumps({'type':'text','text':'Yes, that information looks correct.'}))
                    await settled('acknowledgment does not book',lambda s:bool(s['selection']) and not any(o['purpose']=='create' for o in s['operations']))
                    with wave.open(str(ROOT/'evaluation/native-audio/n01.wav'),'rb') as wav:
                        assert (wav.getframerate(),wav.getnchannels(),wav.getsampwidth())==(16000,1,2)
                        pcm=wav.readframes(wav.getnframes())
                    report['speech_pcm_sha256']=hashlib.sha256(pcm).hexdigest()
                    await ws.send(json.dumps({'type':'speech_start'}))
                    for index in range(0,len(pcm),3200):
                        await ws.send(pcm[index:index+3200]);await asyncio.sleep(.1)
                    await ws.send(json.dumps({'type':'speech_end'}))
                    for _ in range(12):
                        await ws.send(b'\0'*3200);await asyncio.sleep(.1)
                    def confirms(answers):
                        return any(re.search(r'\b(?:is|has been|was|successfully)\s+(?:now\s+)?(?:confirmed|booked|reserved)\b',text,re.I)
                            and not re.search(r'\b(?:soon|waiting|pending|processing|if)\b',text,re.I) for text in answers)
                    await settled('spoken request verified, booked once and confirmation spoken',
                        lambda s:sum(o['purpose']=='create' and o['status']=='completed' for o in s['operations'])==1, confirms)
                    export=(await http.get(BASE+'/api/sessions/'+sid+'/export')).json()
                    report['events']=export['events'];report['final_state']=export['state']
                    report['passed']=any(e['type']=='live_authority_verified' for e in export['events']) and sum(e['type']=='tool_call' and e['effect']=='write' for e in export['events'])==1
                finally:
                    # Keep the failed stage and actual controller trace too. A
                    # harness timeout alone cannot distinguish ASR, a refused
                    # argument, a service failure or missing spoken completion.
                    try:
                        export=(await http.get(BASE+'/api/sessions/'+sid+'/export')).json()
                        report['events']=export['events'];report['final_state']=export['state']
                    except Exception as exc:
                        report['export_error_type']=type(exc).__name__
                    save()
                    await ws.send(json.dumps({'type':'end'}))
    except Exception as exc:
        report['error_type']=type(exc).__name__
        print('Live smoke failed: '+type(exc).__name__,flush=True)
    finally:save()
    return report['passed']


if __name__=='__main__':raise SystemExit(0 if asyncio.run(main()) else 1)
