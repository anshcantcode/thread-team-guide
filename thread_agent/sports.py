"""Sport-aware records. Identities come from providers, never a list of demo athletes.

Unsupported coverage stays explicit and falls back to source discovery. Public ESPN
feeds are an unofficial adapter; Formula 1 race evidence comes from Jolpica.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import math
import re

import httpx

from .online import badge, clean, completed_matches, football, normalized, public_url, resolve_entity, search_web


TEAM_SPORTS = {'basketball', 'baseball', 'football', 'hockey'}
LABELS = {'soccer':'Football', 'football':'American football', 'basketball':'Basketball',
          'baseball':'Baseball', 'hockey':'Ice hockey', 'tennis':'Tennis', 'racing':'Motor racing',
          'cricket':'Cricket', 'golf':'Golf', 'mma':'MMA', 'rugby':'Rugby'}
FEATURED = {'basketball':['points','totalRebounds','assists'],
            'baseball':['hits','homeRuns','RBIs'],
            'football':['passingYards','passingTouchdowns','rushingYards'],
            'hockey':['goals','assists','points']}


def past(value, now):
    try:
        instant=datetime.fromisoformat(value.replace('Z','+00:00'))
        return instant.tzinfo is not None and instant <= now
    except (TypeError, ValueError): return False


def slug(value):
    if not isinstance(value,str) or not re.fullmatch(r'[a-z0-9]+(?:[-.][a-z0-9]+)*',value):
        raise ValueError('The sports provider returned an invalid competition identifier.')
    return value


def web_link(links):
    return next((public_url(x.get('href')) for x in links if public_url(x.get('href')) and 'desktop' in x.get('rel',[])), '')


def parse_gamelog(data, now):
    """Join athlete stat rows to their own dated events, not a team's schedule."""
    names=data.get('names',[]); labels=data.get('displayNames',data.get('labels',names))
    events=data.get('events',{}); found={}
    for season in data.get('seasonTypes',[]):
        for category in season.get('categories',[]):
            for entry in category.get('events',[]):
                eid=str(entry.get('eventId','')); event=events.get(eid,{})
                values=entry.get('stats',[])
                if not past(event.get('gameDate',''),now) or event.get('gameResult') not in ('W','L','T','D'): continue
                if not values or not any(re.search(r'\d',str(v)) for v in values): continue
                if any(str(v).upper() in ('DNP','DND','INACTIVE') for v in values): continue
                stats=[{'key':n,'label':clean(labels[i] if i<len(labels) else n,80),'value':clean(values[i],40)} for i,n in enumerate(names) if i<len(values)]
                team=event.get('team',{}); opponent=event.get('opponent',{})
                home=str(event.get('homeTeamId'))==str(team.get('id'))
                own=event.get('homeTeamScore' if home else 'awayTeamScore')
                other=event.get('awayTeamScore' if home else 'homeTeamScore')
                if own is None or other is None: continue
                found[eid]={'id':eid,'date':event['gameDate'],'title':opponent.get('displayName',opponent.get('abbreviation','Opponent')),
                    'subtitle':f"{team.get('abbreviation','')} · {'Home' if home else 'Away'} · {event.get('leagueShortName','')}",
                    'score':f'{own} – {other}','result':event['gameResult'],'stats':stats,'logo':badge(opponent),
                    'competition':event.get('leagueName',''),'url':web_link(event.get('links',[])), 'season':season.get('displayName','')}
    return sorted(found.values(),key=lambda r:r['date'],reverse=True)


def highlights(records, sport):
    """No season-total/last-five mixing, or summing percentages and ratios."""
    if sport=='tennis' and records and all(r.get('result') in ('W','L') for r in records):
        return [{'label':'Wins','value':str(sum(r['result']=='W' for r in records))},
                {'label':'Losses','value':str(sum(r['result']=='L' for r in records))}, {'label':'Matches','value':str(len(records))}]
    if sport=='racing' and records:
        positions=[int(r['score'][1:]) if re.fullmatch(r'P[0-9]+',r.get('score','')) else None for r in records]
        result=[{'label':'Wins','value':str(positions.count(1))},{'label':'Podiums','value':str(sum(p is not None and 1<=p<=3 for p in positions))}]
        try:
            points=[float(next(s['value'] for s in r['stats'] if s['key']=='points')) for r in records]
            if all(math.isfinite(p) for p in points):result.append({'label':'Points','value':f'{sum(points):g}'})
        except (StopIteration,ValueError,TypeError,KeyError):pass
        return result
    result=[]
    for key in FEATURED.get(sport,[]):
        stats=[next((v for v in row['stats'] if v['key']==key),None) for row in records]
        if not stats or any(s is None for s in stats): continue
        try: values=[float(s['value']) for s in stats]
        except (TypeError,ValueError): continue
        if not all(math.isfinite(v) for v in values):continue
        if sport=='basketball': value=f'{sum(values)/len(values):.1f}'; label=stats[0]['label']+' / game'
        else: value=f'{sum(values):g}'; label=stats[0]['label']
        result.append({'label':label,'value':value})
    return result


async def athlete_log(entity, args, get, now):
    sport, league=slug(entity['sport']),slug(entity['defaultLeagueSlug'])
    url=f"https://site.web.api.espn.com/apis/common/v3/sports/{sport}/{league}/athletes/{entity['record_id']}/gamelog"
    data=await get(url,{})
    records=parse_gamelog(data,now)
    season_filter=next((f for f in data.get('filters',[]) if f.get('name')=='season'),{})
    if len(records)<args.get('limit',5):
        previous=next((o['value'] for o in season_filter.get('options',[]) if str(o['value'])!=str(season_filter.get('value'))),None)
        if previous is not None:
            older=await get(url,{'season':str(previous)})
            merged={r['id']:r for r in records}
            for row in parse_gamelog(older,now):merged.setdefault(row['id'],row)
            records=sorted(merged.values(),key=lambda r:r['date'],reverse=True)
    records=records[:args.get('limit',5)]
    seasons=', '.join(dict.fromkeys(r['season'] for r in records))
    return records, highlights(records,sport), 'Provider athlete game log'+(f' · {seasons}' if seasons else ''), 'ESPN'


async def team_log(entity, args, get, now):
    sport, league=slug(entity['sport']),slug(entity['defaultLeagueSlug'])
    url=f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams/{entity['record_id']}/schedule"
    data=await get(url,{})
    events=completed_matches(data,now)
    if len(events)<args.get('limit',5):
        older=await get(url,{'season':int(data.get('season',{}).get('year',now.year))-1})
        events=completed_matches({'events':data.get('events',[])+older.get('events',[])},now)
    records=[]
    for e in events[:args.get('limit',5)]:
        home=e['home_id']==entity['record_id']; own=e['home_score'] if home else e['away_score']; other=e['away_score'] if home else e['home_score']
        records.append({'id':e['id'],'date':e['date'],'title':e['away'] if home else e['home'], 'subtitle':e['competition'],
            'score':f'{own} – {other}','result':'W' if own>other else 'L' if own<other else 'D','stats':[],
            'url':f"https://www.espn.com/{league}/game/_/gameId/{e['id']}", 'logo':e['away_logo'] if home else e['home_logo']})
    return records, [], 'Completed team matches · current and, if needed, previous provider season', 'ESPN'


def parse_tennis(data, athlete_id, league, now):
    found={}; wanted='mens-singles' if league=='atp' else 'womens-singles'
    for event in data.get('events',[]):
        for group in event.get('groupings',[]):
            if group.get('grouping',{}).get('slug')!=wanted: continue
            for comp in group.get('competitions',[]):
                status=comp.get('status',{}).get('type',{})
                if not status.get('completed') or status.get('state')!='post' or not past(comp.get('date',''),now): continue
                if any(w in status.get('name','') for w in ('CANCEL','POSTPON','WALKOVER','ABANDON')): continue
                players=comp.get('competitors',[])
                own=next((p for p in players if str(p.get('id'))==athlete_id),None)
                other=next((p for p in players if str(p.get('id'))!=athlete_id),None)
                if not own or not other or len(players)!=2: continue
                scores=[]
                for left,right in zip(own.get('linescores',[]),other.get('linescores',[])):
                    if all(isinstance(v,(int,float)) and math.isfinite(v) for v in (left.get('value'),right.get('value'))):
                        scores.append(f"{left['value']:g}–{right['value']:g}")
                if not scores: continue
                eid=str(comp['id'])
                found[eid]={'id':eid,'date':comp['date'],'title':other.get('athlete',{}).get('displayName','Opponent'),
                    'subtitle':event.get('name','Tournament'),'score':'  '.join(scores),'result':'W' if own.get('winner') else 'L',
                    'stats':[],'status':status.get('shortDetail',''),'url':web_link(comp.get('links',[])) or web_link(event.get('links',[]))}
    return sorted(found.values(),key=lambda r:r['date'],reverse=True)


async def tennis_log(entity,args,get,now):
    league=entity.get('defaultLeagueSlug')
    if league not in ('atp','wta'): raise ValueError('No singles tour was supplied by the tennis provider.')
    start=(now-timedelta(days=90)).strftime('%Y%m%d'); end=now.strftime('%Y%m%d')
    data=await get(f'https://site.api.espn.com/apis/site/v2/sports/tennis/{league}/scoreboard',{'dates':f'{start}-{end}','limit':1000})
    records=parse_tennis(data,entity['record_id'],league,now)[:args.get('limit',5)]
    return records, [], f'{league.upper()} singles · completed matches in the last 90 days · doubles excluded', 'ESPN'


def parse_races(data, driver_id, now):
    rows=[]
    for race in data.get('MRData',{}).get('RaceTable',{}).get('Races',[]):
        date=race.get('date','')+'T'+race.get('time','00:00:00Z')
        if not past(date,now): continue
        result=next((r for r in race.get('Results',[]) if r.get('Driver',{}).get('driverId')==driver_id),None)
        if not result: continue
        stats=[{'key':key,'label':label,'value':str(result[key])} for key,label in [('grid','Grid'),('points','Points'),('laps','Laps')] if result.get(key) is not None]
        rows.append({'id':f"{race['season']}-{race['round']}",'date':date,'title':race.get('raceName','Grand Prix'),
            'subtitle':result.get('Constructor',{}).get('name',''),'score':('P'+str(result['positionText'])) if str(result.get('positionText','')).isdigit() else str(result.get('positionText','—')),
            'status':result.get('status',''),'result':'','stats':stats,
            'url':f"https://api.jolpi.ca/ergast/f1/{race['season']}/{race['round']}/results/"})
    return sorted(rows,key=lambda r:r['date'],reverse=True)


async def f1_log(entity,args,get,now):
    data=await get(f'https://api.jolpi.ca/ergast/f1/{now.year}/drivers/',{'limit':100})
    drivers=data.get('MRData',{}).get('DriverTable',{}).get('Drivers',[])
    driver=next((d for d in drivers if normalized(d['givenName']+' '+d['familyName'])==normalized(entity['displayName'])),None)
    if not driver:return [],[],'Formula 1 · no matching driver in the current-season directory','Jolpica'
    driver_id=driver['driverId']
    if not re.fullmatch(r'[a-z0-9_]+',driver_id):raise ValueError('Invalid Formula 1 driver identifier.')
    async def season(year):
        data=await get(f'https://api.jolpi.ca/ergast/f1/{year}/drivers/{driver_id}/results/',{'limit':100})
        return parse_races(data,driver_id,now)
    records=await season(now.year)
    if len(records)<args.get('limit',5):records+=await season(now.year-1)
    return records[:args.get('limit',5)],[],f'Formula 1 Grands Prix · {now.year} and previous season if needed · sprints excluded','Jolpica'


async def discover_other_sports(args, item=None, reason='Structured match records are not available from the connected sources.'):
    query=' '.join(filter(None,[args['query'],args.get('sport',''),f"last {args.get('limit',5)} results"]))
    try: sources=await search_web({'query':query,'mode':'web','limit':5})
    except (httpx.HTTPError,ValueError,TimeoutError):sources={'items':[],'source':'Online search unavailable'}
    if item:
        item.update(records=[],metrics=[],coverage=reason,coverage_status='unavailable')
    return {'status':'completed','source':sources['source'],'provenance':'live','retrieved_at':datetime.now(timezone.utc).isoformat(),
        'items':([item] if item else [])+sources['items'],'coverage':reason,'coverage_status':'unavailable',
        'summary':reason+' Show the source links. These are search excerpts, NOT verified recent appearances. Do not invent scores, rankings, totals, or a five-game list.',
        'note':'No matching records or online sources were returned. Try the full name and sport.'}


async def enrich_identity(entity,item,get):
    """Optional publisher identity fields; missing fields never become guessed jersey numbers or flags."""
    try:
        sport=slug(entity['sport']);league='icc' if sport=='cricket' else slug(entity.get('defaultLeagueSlug',''))
        async with asyncio.timeout(3): data=await get(f"https://site.web.api.espn.com/apis/common/v3/sports/{sport}/{league}/athletes/{entity['record_id']}",{})
        athlete=data.get('athlete') if isinstance(data,dict) else None
        if not isinstance(athlete,dict):return
        team=athlete.get('team') or {};position=athlete.get('position') or {};flag=athlete.get('flag') or {}
        if isinstance(team,dict):
            if team.get('displayName'):item['team']=clean(team['displayName'],100)
            logos=team.get('logos') or []
            if isinstance(logos,list):
                mark=next((public_url(logo.get('href')) for logo in logos if isinstance(logo,dict) and public_url(logo.get('href'))),'')
                if mark:item['logo']=mark
        if isinstance(position,dict):item['position']=clean(position.get('displayName') or position.get('name') or '',80)
        if athlete.get('jersey'):item['jersey']=clean(athlete['jersey'],12)
        if isinstance(flag,dict):item.update(flag=public_url(flag.get('href')),country=clean(flag.get('alt',''),60))
        headshot=athlete.get('headshot') or {}
        if isinstance(headshot,dict) and public_url(headshot.get('href')):item['portrait']=public_url(headshot['href'])
        item['identity_source']='ESPN player profile'
    except (httpx.HTTPError,ValueError,TimeoutError,KeyError,TypeError,IndexError):pass


async def recent_sports(args,get,now=None):
    now=now or datetime.now(timezone.utc)
    entity,choices=await resolve_entity(args,get,all_sports=True)
    if entity is None:
        if not choices:return await discover_other_sports(args)
        return {'status':'completed','source':'ESPN identity search','provenance':'live','items':choices,
                'needs_clarification':True,'retrieved_at':now.isoformat(),'summary':'Ask which returned team or athlete the user means. Do not choose from a first name alone.'}
    sport=entity.get('sport','')
    if sport=='soccer':return await football(args,get,now,entity=entity)
    item={'id':f"{sport}-{entity['record_id']}",'kind':'sports_profile','title':entity['displayName'],
        'sport':sport,'sport_label':LABELS.get(sport,sport.title()),'entity_type':args['entity_type'],
        'team':entity.get('subtitle',''),'league':entity.get('description',''),
        'portrait':public_url(entity.get('image',{}).get('default')) if args['entity_type']=='player' else '',
        'logo':public_url(entity.get('image',{}).get('default')) if args['entity_type']=='team' else '',
        'url':public_url(entity.get('link',{}).get('web')),'requested_count':args.get('limit',5)}
    try:
        if sport in TEAM_SPORTS:
            result=await (athlete_log if args['entity_type']=='player' else team_log)(entity,args,get,now)
        elif sport=='tennis' and args['entity_type']=='player':result=await tennis_log(entity,args,get,now)
        elif sport=='racing' and entity.get('defaultLeagueSlug')=='f1' and args['entity_type']=='player':result=await f1_log(entity,args,get,now)
        elif sport=='cricket' and args['entity_type']=='player':
            from .cricket import cricket_log
            result=await cricket_log(entity,args,get,now)
        else:return await discover_other_sports(args,item)
        records,metrics,coverage,source=result
    except (httpx.HTTPError,ValueError,TimeoutError,KeyError,TypeError,IndexError):
        return await discover_other_sports(args,item,'The statistics source is currently unavailable. No match records were invented.')
    count=len(records); complete=count>=args.get('limit',5)
    if not count:return await discover_other_sports(args,item,'No completed records were returned in the connected source coverage.')
    if source=='Cricbuzz':item['url']=public_url(records[0].get('url'))
    if not metrics:metrics=highlights(records,sport)
    if args['entity_type']=='player':await enrich_identity(entity,item,get)
    if sport=='racing' and not item.get('team'):item['team']=records[0].get('subtitle','')
    item.update(records=records,metrics=metrics,coverage=coverage,coverage_status='available' if complete else 'partial',
                latest_record_at=records[0]['date'])
    if not complete:item['coverage']+=f' · only {count} records available'
    return {'status':'completed','source':source,'provenance':'live','retrieved_at':now.isoformat(),'items':[item],
        'summary':f"{entity['displayName']}: {count} dated {LABELS.get(sport,sport)} records. {item['coverage']}. Latest returned date: {records[0]['date']}. Use only the returned rows and sport-specific statistics. Distinguish these dates from today's retrieval date."}
