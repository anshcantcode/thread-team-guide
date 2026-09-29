"""Exact user requests through real Gemini Live and real public tools; native acknowledgement simulated.
The resulting configurations are subsequently exercised by Android's real AppWidgetHost tests.
"""
import asyncio, json, time, sys
from pathlib import Path
import httpx, websockets
BASE='http://127.0.0.1:8766'
ROOT=Path(__file__).resolve().parents[1]
COMPOSE='--two-locations' in sys.argv
async def main():
    report={'passed':False,'input':'typed natural language, actual Gemini Live','device_acknowledgement':'simulated preview only; separate device widget tests verify rendering and taps','cases':[]}
    def save(): (ROOT/('reports/widget-composition-contract.json' if COMPOSE else 'reports/widget-request-contract.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        async with httpx.AsyncClient(timeout=45) as http:
            sid=(await http.post(BASE+'/api/sessions',json={'experience':'voice'})).json()['session_id'];report['session_id']=sid
            async with websockets.connect(BASE.replace('http','ws')+'/live/'+sid+'?client=android',max_size=8000000) as ws:
                async def receive(widget=False):
                    captions={}; actions=[]; complete=False; last=time.monotonic()
                    async with asyncio.timeout(110):
                        while True:
                            try:
                                event=json.loads(await asyncio.wait_for(ws.recv(),.5));last=time.monotonic()
                                if event['type']=='live_error': raise RuntimeError(event['text'])
                                if event['type']=='caption':captions[event['message_id']]={'role':event['role'],'text':event['text']}
                                if event['type']=='device_action':
                                    actions.append(event)
                                    await ws.send(json.dumps({'type':'device_result','request_id':event['request_id'],'result':{'status':'prepared','detail':'SIMULATED acknowledgement: the native widget preview is prepared, user still needs to pin.'}}))
                                if event['type']=='turn_complete':complete=True
                                if event['type']=='audio':complete=False
                            except asyncio.TimeoutError:
                                if complete and time.monotonic()-last>1.5:
                                    state=(await http.get(BASE+'/api/sessions/'+sid)).json()
                                    if any(o['status']=='running' and not o.get('obsolete') for o in state['operations']):continue
                                    if not widget or actions:return {'captions':list(captions.values()),'actions':actions}
                await receive()
                cases=[
                    ('world-clocks','Make a widget that shows the time in Manchester and Barca.','world_clocks'),
                    ('barcelona-matches',"Make a widget that shows Barca's last 5 games.",'sports'),
                    ('packing-checklist','Make a packing checklist widget for a weekend trip with passport, charger and medication.','document')]
                if COMPOSE: cases=[('two-weather-locations','Make one widget showing the current weather in both Chennai, India and Tokyo, Japan.','weather')]
                for label,prompt,domain in cases:
                    await ws.send(json.dumps({'type':'text','text':prompt}))
                    row={'case':label,'request':prompt};report['cases'].append(row);save()
                    row.update(await receive(True))
                    action=next(a for a in row['actions'] if a['action']=='create_widget')
                    config=action['arguments'];results=config['results'];assert all(r['domain']==domain for r in results), results
                    if COMPOSE: assert len(results)==2 and {r['items'][0]['title'] for r in results}=={'Chennai','Tokyo'}
                    else: assert len(results)==1
                    result=results[0];items=result['items']
                    if domain=='world_clocks':assert {i['zone'] for i in items}=={'Europe/London','Europe/Madrid'} and len(items)==2
                    if domain=='sports':assert len(items[0].get('matches',items[0].get('records',[])))==5 and result['provenance']=='live'
                    if domain=='document':assert items[0]['document']['kind']=='checklist' and result['provenance']=='draft'
                    (ROOT/f'reports/widget-{label}-config.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
                    row['passed']=True;save();print(label,'PASS',flush=True)
                await ws.send(json.dumps({'type':'end'}));report['passed']=True
    except Exception as exc:report['error']=f'{type(exc).__name__}: {str(exc)[:500]}';raise
    finally:save()
if __name__=='__main__':asyncio.run(main())
