"""Real Gemini Live evaluation through THREAD, separate from deterministic unit tests.

No canned interpretations. Every prompt goes through the native live connection.
Assertions inspect actual controller state, source provenance and operation outcomes.
Requires available Gemini Live quota. Reports failures without rewriting expectations.
"""
import argparse
import asyncio
import base64
from datetime import datetime, timezone
import json
import re
from pathlib import Path
import sys
import time

import httpx
import websockets

ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8766'


def case(name,prompt,**expect): return {'name':name,'prompt':prompt,'expect':expect}


GROUPS = {
 'numbers':[
  case('tax_and_split','Calculate 18500 plus 18 percent tax, then split the total between three people.',domain='calculate',value=7276.6666666667,absolute_tolerance=.005),
  case('tax_correction','Actually use 12 percent tax. Keep the original amount and three-way split.',domain='calculate',value=6906.6666666667,absolute_tolerance=.005),
  case('divisor_correction','Now split that same total between four people instead.',domain='calculate',value=5180),
  case('miles_to_km','Convert ten miles to kilometres.',domain='convert',value=16.09344),
  case('unit_direction_repair','No, five kilometres to miles instead.',domain='convert',value=3.1068559612),
  case('zero_denominator','Calculate 100 divided by zero.',domain='calculate',failed_tool=True),
 ],
 'documents':[
  case('packing_checklist','Make a useful packing checklist for a three-day rainy trip to Kyoto. Hand luggage only. Show it in the workspace.',domain='document',kind='checklist',contains=['rain']),
  case('checklist_correction','Revise that checklist for five days instead, and add my camera. Keep hand luggage only.',domain='document',kind='checklist',contains=['camera']),
  case('recipe_constraints','Make a vegetarian chickpea dinner recipe for two people, without nuts, with ingredients and steps in the workspace.',domain='document',kind='recipe',contains=['chickpea']),
  case('comparison_table','Compare SQLite and PostgreSQL for a small offline desktop app. Put a clear comparison table and recommendation in the workspace.',domain='document',kind='comparison',table=True),
  case('code_draft','Write a Python function that returns the median of a list and raises ValueError for an empty list. Show the code in the workspace; do not run it.',domain='document',kind='code',contains=['ValueError','def ']),
  case('email_draft','Draft a friendly email asking a colleague to move our review from Tuesday to Thursday. Do not send it. Put the draft in the workspace.',domain='document',kind='writing',contains=['Thursday'],no_creates=True),
 ],
 'practical':[
  case('leap_date','What date is 2028 February 28 plus two days? Calculate it.',domain='dates',value='2028-03-01'),
  case('world_clock','Convert October 8 2026 at 2 PM in Kolkata to New York time.',domain='clock',value='04:30'),
  case('timer_start','Set a ten-minute focus timer here.',domain='timer',slots={'seconds':600}),
  case('timer_pause','Pause the timer.',domain='timer',paused=True),
  case('timer_resume','Resume the timer.',domain='timer',paused=False),
  case('timer_cancel','Cancel the timer.',domain='timer',cancelled_timer=True),
 ],
 'notebook':[
  case('preview_note','Draft a note titled THREAD evaluation scratchpad. The exact body is: Pack the blue notebook and a USB cable. Show me the preview first.',domain='notes',contains=['blue notebook'],no_creates=True),
  case('ack_is_not_save','That wording looks good.',domain='notes',no_creates=True),
  case('explicit_save','Save that exact note to my THREAD notebook now.',domain='notes',saved=True),
  case('find_saved_note','Find my saved notes containing THREAD evaluation scratchpad.',domain='library',contains=['blue notebook'],provenance='saved'),
 ],
 'travel':[
  case('initial_flight','Show demo flights from Chennai to Delhi on October 8 2026 after 6 PM for two people.',domain='travel',slots={'origin':'Chennai','destination':'Delhi','date':'2026-10-08','after':'18:00','passengers':2},provenance='demo'),
  case('self_repair','Mumbai, sorry, Bengaluru instead of Delhi. Keep everything else.',domain='travel',slots={'origin':'Chennai','destination':'Bengaluru','date':'2026-10-08','after':'18:00','passengers':2}),
  case('negation','Not after nine. Before nine in the evening instead. Remove the after limit.',domain='travel',slots={'before':'21:00','destination':'Bengaluru'},absent=['after']),
  case('hypothetical_preserves','Would Mumbai be cheaper? Do not change my current search.',domain='travel',slots={'destination':'Bengaluru'},no_creates=True),
  case('status_not_booking','Have you booked anything yet?',domain='travel',no_creates=True),
  case('unknown_hotel_no_false_booking','Book a real hotel at Bengaluru airport. Use my account if needed.',no_creates=True,not_domain='rooms'),
 ],
 'sources':[
  case('actual_weather','Check the three-day weather forecast for Chennai in India.',domain='weather',slots={'days':3},provenance='live'),
  case('weather_city_correction','Actually check Tokyo, Japan instead. Keep three days.',domain='weather',slots={'city':'Tokyo','country_code':'JP','days':3},provenance='live'),
  case('exchange_rate','How much is 100 US dollars in Indian rupees using a current reference rate?',domain='currency',slots={'amount':100,'from_currency':'USD','to_currency':'INR'},provenance='live'),
  case('books_search','Find books by Ursula K Le Guin using Open Library.',domain='research',slots={'collection':'books'},provenance='live'),
  case('paper_search','Find papers on end-to-end spoken dialogue models using Crossref.',domain='research',slots={'collection':'papers'},provenance='live'),
  case('grounded_web','Use Google Search to find the current official Python release. Give me the release number and show the source.',web=True),
 ],
}


def assess(state, expected):
    errors=[]
    def require(ok,reason):
        if not ok: errors.append(reason)
    if 'domain' in expected: require(state['domain']==expected['domain'],f"domain {state['domain']!r}, expected {expected['domain']!r}")
    if 'not_domain' in expected: require(state['domain']!=expected['not_domain'],'used the wrong task domain')
    for k,v in expected.get('slots',{}).items(): require(state['slots'].get(k)==v,f'slot {k}: {state["slots"].get(k)!r}, expected {v!r}')
    for k in expected.get('absent',[]): require(k not in state['slots'],f'{k} should have been removed')
    result=state.get('results') or {};items=result.get('items',[]);item=items[0] if items else {}
    if 'value' in expected:
        actual=item.get('value');target=expected['value']
        try: ok=abs(float(actual)-target)<=max(expected.get('absolute_tolerance',1e-7),abs(target)*1e-9) if isinstance(target,(int,float)) else actual==target
        except (ValueError,TypeError): ok=False
        require(ok,f'value {actual!r}, expected {target!r}')
    if expected.get('kind'): require(state['slots'].get('kind')==expected['kind'],f'document kind should be {expected["kind"]}')
    if expected.get('table'): require(bool(item.get('document',{}).get('rows')),'comparison table missing')
    for phrase in expected.get('contains',[]): require(phrase.lower() in json.dumps(items,ensure_ascii=False).lower(),f'result missing {phrase!r}')
    if 'provenance' in expected: require(result.get('provenance')==expected['provenance'],'source provenance absent or wrong')
    if 'paused' in expected: require(state['paused']==expected['paused'],'wrong pause state')
    if expected.get('cancelled_timer'): require(item.get('cancelled') is True,'timer was not cancelled')
    if expected.get('no_creates'): require(state['metrics']['submitted_creates']==0,'unexpected write submission')
    if expected.get('saved'): require(any(o['domain']=='notes' and o['purpose']=='create' and o['status']=='completed' for o in state['operations']),'no confirmed note save')
    if expected.get('failed_tool'): require(any(o['domain']==state['domain'] and o['status']=='failed' for o in state['operations']),'invalid calculation should fail')
    if expected.get('web'): require(any(r['domain']=='web' and r.get('items') for r in state.get('workspace',[])),'no native grounding source metadata')
    return errors


async def run_group(group,cases,http,report):
    creation=await http.post(BASE+'/api/sessions',json={'experience':'voice'});creation.raise_for_status();sid=creation.json()['session_id']
    async with websockets.connect(BASE.replace('http:','ws:')+'/live/'+sid,max_size=8_000_000) as ws:
        initial=json.loads(await asyncio.wait_for(ws.recv(),30))
        if initial['type']!='live_ready': raise RuntimeError(initial.get('text','Live setup failed'))
        report['model']=initial['model']
        # Consume greeting; it must never authorize a task.
        async with asyncio.timeout(30):
            while json.loads(await ws.recv()).get('type')!='turn_complete': pass
        seen_audio_ids=set()
        for c in cases:
            if c['expect'].get('web') and not initial.get('google_search_enabled'):
                report.setdefault('blocked_cases',[]).append({'group':group,**c,'reason':'Google Search grounding quota is unavailable for this key. Native voice and independent tools remain available.'})
                write_report(report)
                continue
            start=time.monotonic();record={'group':group,**c,'captions':{},'audio_bytes':0,'first_audio_ms':None}
            earlier_ids=set(seen_audio_ids)
            await ws.send(json.dumps({'type':'text','text':c['prompt']}))
            complete=False;last_complete=None
            while time.monotonic()-start<50:
                try:
                    event=json.loads(await asyncio.wait_for(ws.recv(),.4))
                    if event['type']=='live_error': raise RuntimeError(event['text'])
                    if event['type']=='audio':
                        seen_audio_ids.add(event['message_id'])
                        if event['message_id'] in earlier_ids: continue
                        # A backend notice can start another generation after an
                        # earlier turn-complete. Wait for this generation's boundary.
                        complete=False;last_complete=None
                        record['audio_bytes']+=len(base64.b64decode(event['data']))
                        if record['first_audio_ms'] is None: record['first_audio_ms']=round((time.monotonic()-start)*1000)
                    if event['type']=='caption' and event['role']=='assistant' and event['message_id'] not in earlier_ids: record['captions'][event['message_id']]=event['text']
                    if event['type']=='interrupted': complete=False;last_complete=None
                    if event['type']=='turn_complete': complete=True;last_complete=time.monotonic()
                except asyncio.TimeoutError: pass
                if complete and record['audio_bytes'] and last_complete and time.monotonic()-last_complete>1.6:
                    state=(await http.get(BASE+'/api/sessions/'+sid)).json()
                    pending=any(o['purpose']=='lookup' and o['status']=='running' and not o['obsolete'] for o in state['operations'])
                    writes_pending=any(o['purpose']=='create' and o['status'] in ('prepared','submitted') for o in state['operations'])
                    if not pending and not writes_pending: break
            state=(await http.get(BASE+'/api/sessions/'+sid)).json()
            record['errors']=assess(state,c['expect'])
            spoken=' '.join(record['captions'].values())
            if re.search(r'\b(?:update_task|publish_document|get_weather)\s*[({]|\bbase_revision\s*[:=]',spoken):
                record['errors'].append('native response exposed internal function syntax; voice quality needs review')
            if not record['audio_bytes']: record['errors'].append('no native audio response received')
            record['passed']=not record['errors'];record['elapsed_ms']=round((time.monotonic()-start)*1000)
            record['state']={k:state[k] for k in ['domain','slots','results','paused','metrics']}
            record['captions']=list(record['captions'].values())
            report['cases'].append(record)
            write_report(report)
            print(json.dumps({'case':c['name'],'passed':record['passed'],'errors':record['errors'],'audio_ms':record['first_audio_ms'],'spoken':' '.join(record['captions'])[:240]},ensure_ascii=True),flush=True)
        await ws.send(json.dumps({'type':'end'}))
    export=(await http.get(BASE+'/api/sessions/'+sid+'/export')).json()
    (ROOT/'reports'/f'native-workspace-{group}-session.json').write_text(json.dumps(export,ensure_ascii=False,indent=2),encoding='utf-8')
    # Archive only the explicitly named scratch note produced by this evaluation.
    if group=='notebook':
        sys.path.insert(0,str(ROOT))
        from thread_agent.capabilities import Notebook
        store=Notebook()
        for op in export['state']['operations']:
            if op['domain']=='notes' and op['purpose']=='create' and op['arguments'].get('title')=='THREAD evaluation scratchpad': store.cancel(op['id'])


def write_report(report):
    report['passed_count']=sum(c['passed'] for c in report['cases']);report['executed_count']=len(report['cases'])
    report['passed']=bool(report['cases']) and all(c['passed'] for c in report['cases']) and not report.get('errors')
    report['all_planned_executed']=report['executed_count']==report['planned_count']
    (ROOT/'reports'/'native-workspace-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')


async def main():
    parser=argparse.ArgumentParser();parser.add_argument('--groups',nargs='*',default=list(GROUPS));args=parser.parse_args()
    report={'format':'THREAD native workspace evaluation v1','started':datetime.now(timezone.utc).isoformat(),
            'scope':'Typed natural-language requests over the actual native voice relay, with real generated audio. Not a physical-microphone or hidden-test evaluation.',
            'selected_groups':args.groups,'planned_count':sum(len(GROUPS[g]) for g in args.groups),'cases':[],'errors':[]}
    async with httpx.AsyncClient(timeout=35) as http:
        for group in args.groups:
            try: await run_group(group,GROUPS[group],http,report)
            except Exception as exc:
                report['errors'].append({'group':group,'error':type(exc).__name__,'detail':str(exc)[:250]})
                print('Group stopped:',group,type(exc).__name__,flush=True)
                write_report(report)
                if isinstance(exc,RuntimeError): break
    write_report(report)
    print(f"Native evaluation: {report['passed_count']}/{report['executed_count']} passed; {len(report['errors'])} group errors",flush=True)
    return 0 if report['passed'] and report['executed_count']==report['planned_count'] else 1


if __name__=='__main__': raise SystemExit(asyncio.run(main()))
