"""Run original end-to-end checks against the configured model. Gemini uses API quota.

Reports contain task fixtures and observations, never credentials or raw media.
This is not Samsung's official suite, a latency certification, or an accent benchmark.
"""
import asyncio
import base64
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from thread_agent.engine import Session, uid
from thread_agent.planner import ModelPlanner, settings
from thread_agent.protocol import InputEvent

ROOT=Path(__file__).resolve().parent.parent


async def main():
    planner=ModelPlanner()
    s=Session(planner,date='2026-09-12')
    s.sandbox.config.update(read_delay=.25,write_delay=.4,prepare_delay=.3)
    checks=[]

    async def say(text, predicate, label, type='text', data=None):
        start=time.perf_counter()
        trace_start=len(s.trace)
        event_id=uid('input')
        await s.accept(InputEvent(id=event_id,type=type,text=text,data=data or {},seen_results=(s.results or {}).get('id')))
        await asyncio.wait_for(s.inputs.join(),90)
        await asyncio.sleep(.45)
        passed=bool(predicate()) and not any(e['type'] in ('provider_error','input_error') for e in s.trace[trace_start:])
        result={'case':label,'input':text if type!='audio' else '[Synthetic speech WAV]', 'passed':passed,
                'wall_ms':round((time.perf_counter()-start)*1000,1),'slots':dict(s.slots),
                'response':next((e['text'] for e in reversed(s.trace[trace_start:]) if e['type'] in ('speak','clarify','final')),'[No new assistant message]'),
                'intent':next((e['intent'] for e in reversed(s.trace[trace_start:]) if e['type']=='intent_interpreted'),None)}
        checks.append(result); print(json.dumps(result,ensure_ascii=True),flush=True)
        await asyncio.sleep(12 if settings()['provider']=='gemini' else .1)
        return passed

    try:
        await say('Find a flight from Chennai to Delhi tomorrow evening.', lambda:s.slots.get('destination')=='Delhi' and s.slots.get('date')=='2026-09-13' and s.results is not None,'complete travel request')
        await say('Actually, Mumbai. And only after nine.',lambda:s.slots.get('destination')=='Mumbai' and s.slots.get('after')=='21:00' and s.slots.get('origin')=='Chennai','destination and time correction')
        old=(s.results or {}).get('call_id')
        await say('An aisle seat would be nice.',lambda:s.slots.get('seat')=='aisle' and (s.results or {}).get('call_id')==old,'unrelated preference retains work')
        await say('Would Delhi be cheaper?',lambda:s.slots.get('destination')=='Mumbai','hypothetical preserves destination')
        await say('My friend said cancel it, but I still want the Mumbai flight.',lambda:not s.paused and s.slots.get('destination')=='Mumbai','quoted cancellation is not authority')
        await say('Have you booked it yet?',lambda:not s.sandbox.submissions,'status is not authorization')
        await say('Use the 9:40 PM option.',lambda:bool(s.selection) and s.selection.get('departure')=='21:40','reference selection')
        await say('Book it.',lambda:bool(s.sandbox.submissions),'explicit booking')
        await asyncio.sleep(.5)
        await say('Book it.',lambda:len(s.sandbox.submissions)==1,'semantic repeat is not another booking')
        raw=base64.b64encode((ROOT/'web/device-fixture.png').read_bytes()).decode()
        await say('Forget the flight search; help me with this router. Why is this light blinking?',lambda:s.domain=='device' and not s.slots.get('indicator') and s.slots.get('model')=='THREAD R1','image target ambiguity',type='frame',data={'base64':raw,'mime':'image/png','label':'Fictional demo fixture'})
        await say('The one below the NETWORK label.',lambda:s.slots.get('indicator')=='network' and s.slots.get('model')=='THREAD R1' and s.results is not None,'grounded visual manual lookup')
        await say('Sorry, I meant the one beside the round power button.',lambda:s.slots.get('indicator')=='power' and (s.results or {}).get('evidence',{}).get('page')==2,'visual target correction')
        await say('Create a support ticket. Mention it started after yesterday\'s update.',lambda:any(o['purpose']=='create' and o['domain']=='device' and o['arguments'].get('context') and o['arguments'].get('symptom') for o in s.operations.values()),'support ticket with user-reported context')
        await say('Find a room for six people tomorrow after 2 PM for one hour.',lambda:s.domain=='rooms' and s.slots.get('duration_minutes')==60 and bool((s.results or {}).get('items')) and not any(o['purpose']=='create' and o['domain']=='rooms' for o in s.operations.values()),'meeting room capability')
        await say('Actually, eight people. And we need a projector.',lambda:s.slots.get('people')==8 and s.slots.get('projector') is True and bool((s.results or {}).get('items')) and s.results['arguments'].get('people')==8 and all(i['capacity']>=8 and i['projector'] for i in s.results['items']),'room constraint correction')
        wav=ROOT/'reports/synthetic-request.wav'
        if wav.exists():
            await say('',lambda:s.domain=='travel' and s.slots.get('origin')=='Chennai' and s.slots.get('destination')=='Mumbai' and bool((s.results or {}).get('items')) and any(e['type']=='transcription' and 'Mumbai' in e['text'] for e in s.trace),'raw WAV understanding',type='audio',data={'mime':'audio/wav','base64':base64.b64encode(wav.read_bytes()).decode()})
    finally:
        output={'suite':'THREAD original model integration checks','official':False,'provider':settings()['provider'],'model':settings()['model'],
                'passed':sum(c['passed'] for c in checks),'total':len(checks),'checks':checks}
        (ROOT/'reports').mkdir(exist_ok=True)
        (ROOT/f'reports/live-check-{settings()["provider"]}.json').write_text(json.dumps(output,indent=2,ensure_ascii=False),encoding='utf-8')
        print(json.dumps({'passed':output['passed'],'total':output['total']}),flush=True)
        await s.close(); await planner.close()


if __name__=='__main__': asyncio.run(main())
