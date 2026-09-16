"""Real Gemini voice + public internet smoke test, including an empty barge-in.
Receives generated audio; does not claim physical microphone/speaker measurements.
"""
import asyncio
import json
from pathlib import Path
import time

import httpx
import websockets

ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8766'


async def main():
    report={'passed':False,'cases':[],'scope':'Native voice audio received over the actual relay; real ESPN/search requests; simulated local false VAD event, no physical microphone test.'}
    path=ROOT/'reports'/'live-online-check.json'
    def save():path.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    save()
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            r=await http.post(BASE+'/api/sessions',json={'experience':'voice'});r.raise_for_status();sid=r.json()['session_id']
            report['session_id']=sid
            async with websockets.connect(BASE.replace('http:','ws:')+'/live/'+sid,max_size=8_000_000) as ws:
                async def settled(label, domain=None, predicate=None, spoken_check=None):
                    started=time.monotonic();last=time.monotonic();complete=False;audio=0;captions={};mid=None
                    async with asyncio.timeout(55):
                        while True:
                            try:
                                event=json.loads(await asyncio.wait_for(ws.recv(),.35));last=time.monotonic()
                                if event['type']=='live_error':raise RuntimeError(event['text'])
                                if event['type']=='audio':audio+=len(event['data']);mid=event['message_id'];complete=False
                                if event['type']=='caption':captions[event['message_id']]={'role':event['role'],'text':event['text']}
                                if event['type']=='turn_complete':complete=True
                            except asyncio.TimeoutError:
                                if complete and audio and time.monotonic()-last>1.4:
                                    state=(await http.get(BASE+'/api/sessions/'+sid)).json()
                                    running=any(op['purpose']=='lookup' and op['status']=='running' and not op.get('obsolete') for op in state['operations'])
                                    spoken=' '.join(c['text'] for c in captions.values() if c['role']=='assistant').casefold()
                                    if not running and (not domain or state['domain']==domain) and (not predicate or predicate(state)) and (not spoken_check or spoken_check(spoken,state)):
                                        row={'case':label,'passed':True,'elapsed_seconds':round(time.monotonic()-started,2),'audio_base64_bytes':audio,'captions':list(captions.values()),'result':state.get('results')}
                                        report['cases'].append(row);save();print(label,'passed',flush=True);return mid,state
                def mentions_opponent(spoken,state):
                    item=state['results']['items'][0]
                    return any((m['away'] if m['home']==item['team'] else m['home']).split()[0].casefold() in spoken for m in item['matches'][:2])
                await settled('native greeting')
                await ws.send(json.dumps({'type':'text','text':"Show me Barca's five most recent games. Use live results and tell me the latest opponent and score."}))
                mid,state=await settled('Barcelona live results','sports',lambda s: len((s.get('results') or {}).get('items',[{}])[0].get('matches',[]))==5,mentions_opponent)
                await ws.send(json.dumps({'type':'playback','message_id':mid,'status':'paused','played_ms':400}))
                await ws.send(json.dumps({'type':'speech_start','message_id':mid}))
                await ws.send(json.dumps({'type':'speech_end'}))
                await asyncio.sleep(1.35)
                await ws.send(json.dumps({'type':'resume_after_noise','message_id':mid}))
                async with asyncio.timeout(10):
                    while True:
                        e=json.loads(await ws.recv())
                        if e['type']=='resume_after_noise':
                            assert e['message_id']==mid and not e['continue_needed'],e
                            report['cases'].append({'case':'empty local interruption resumes completed PCM','passed':True,'event':e});save();break
                        if e['type']=='resume_denied':raise AssertionError(e)
                await ws.send(json.dumps({'type':'playback','message_id':mid,'status':'resumed','played_ms':400}))
                await ws.send(json.dumps({'type':'playback','message_id':mid,'status':'played','played_ms':1000}))
                await ws.send(json.dumps({'type':'text','text':"Show me Bruno's last five games."}))
                await settled('ambiguous Bruno clarification',spoken_check=lambda text,s: 'bruno' in text and any(x in text for x in ('which','fernandes','guimar')))
                await ws.send(json.dumps({'type':'text','text':"Bruno Fernandes at Manchester United. Show his five most recent appearances, with goals and assists. Tell me his latest opponent and score."}))
                await settled('Bruno Fernandes live appearances','sports',lambda s: (s.get('results') or {}).get('items',[{}])[0].get('entity_type')=='player' and len(s['results']['items'][0].get('matches',[]))==5,mentions_opponent)
                await ws.send(json.dumps({'type':'text','text':'Search this week\'s Barcelona football news online and show the source links.'}))
                await settled('dated online news','web',lambda s: bool((s.get('results') or {}).get('items')))
                await ws.send(json.dumps({'type':'end'}))
            export=(await http.get(BASE+'/api/sessions/'+sid+'/export')).json()
            (ROOT/'reports'/'live-online-session.json').write_text(json.dumps(export,indent=2,ensure_ascii=False),encoding='utf-8')
            report['passed']=True
    except Exception as exc:
        report['error']=type(exc).__name__+': '+str(exc)[:400]
        raise
    finally:save()

if __name__=='__main__':asyncio.run(main())
