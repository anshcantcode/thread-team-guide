"""Public web discovery and football evidence, independent of Gemini grounding quota.

ESPN's public website feeds are an unofficial adapter, not a contracted sports API.
Only constant provider hosts are fetched. Provider URLs/HTML never become instructions.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html import unescape
import re
import unicodedata
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import httpx


def clean(value, limit=600):
    return unescape(re.sub('<[^>]*>', ' ', str(value or ''))).strip()[:limit]


def public_url(value):
    try:
        u = urlparse(str(value))
        return str(value) if u.scheme in ('https', 'http') and u.hostname and not u.username and not u.password else ''
    except ValueError:
        return ''


async def fetch_feed(url, params):
    async with httpx.AsyncClient(timeout=12, follow_redirects=False, headers={'User-Agent':'THREAD/0.4 (local voice prototype)'}) as client:
        async with client.stream('GET', url, params=params) as response:
            response.raise_for_status()
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > 2_000_000: raise ValueError('Search response exceeded the size limit.')
    return bytes(raw)


def parse_feed(raw, provider, limit):
    root = ET.fromstring(raw)
    items, seen = [], set()
    for row in root.findall('./channel/item'):
        url = public_url(row.findtext('link', ''))
        title = clean(row.findtext('title'), 250)
        if not url or not title or url in seen: continue
        seen.add(url)
        published = ''
        try: published = parsedate_to_datetime(row.findtext('pubDate', '')).isoformat()
        except (ValueError, TypeError, OverflowError): pass
        source = row.find('source')
        items.append({'id':sha256(url.encode()).hexdigest()[:16], 'kind':'source', 'title':title,
                      'url':url, 'detail':clean(row.findtext('description')), 'published':published,
                      'provider':clean(source.text if source is not None else urlparse(url).hostname),
                      'discovered_via':provider})
        if len(items) >= limit: break
    return items


async def search_web(args, feed=fetch_feed):
    news = args.get('mode', 'web') == 'news'
    provider = 'Google News RSS' if news else 'Bing RSS'
    query = args['query']
    if news:
        days = {'day':1, 'week':7, 'month':30}.get(args.get('recency'))
        raw = await feed('https://news.google.com/rss/search', {'q':query + (f' when:{days}d' if days else ''), 'hl':'en-GB','gl':'GB','ceid':'GB:en'})
    else:
        raw = await feed('https://www.bing.com/search', {'q':query, 'format':'rss'})
    try: items = parse_feed(raw, provider, args.get('limit', 5))
    except ET.ParseError: raise ValueError('The search service returned an unreadable response. No search results were invented.')
    return {'status':'completed','source':provider,'provenance':'live','items':items,
            'retrieved_at':datetime.now(timezone.utc).isoformat(),
            'summary':f'{len(items)} live search results for {query}. Search snippets are discovery evidence, not full-page verification. Check publication dates before describing anything as recent.',
            'note':'No matching online results. Try a more specific name or a different query.',
            'coverage':'News uses publisher timestamps. Web result freshness is unknown when no publication date is supplied.'}


def normalized(value):
    return re.sub(r'[^a-z0-9]+', ' ', unicodedata.normalize('NFKD', str(value)).encode('ascii','ignore').decode().lower()).strip()


def numeric_id(value):
    value = str(value)
    if not re.fullmatch(r'\d{1,12}', value): raise ValueError('The sports source returned an invalid record ID.')
    return value


def badge(team):
    return public_url(team.get('logo') or next((x.get('href') for x in team.get('logos',[]) if x.get('href')), ''))


async def resolve_entity(args, get, *, all_sports=False):
    kind = args.get('entity_type', 'team')
    query = {'barca':'Barcelona', 'fc barcelona':'Barcelona', 'man utd':'Manchester United'}.get(normalized(args['query']), args['query'])
    data = await get('https://site.web.api.espn.com/apis/search/v2', {'query':query, 'limit':8})
    rows = [r for group in data.get('results',[]) if group.get('type') == ('player' if kind=='player' else 'team')
            for r in group.get('contents',[]) if all_sports or r.get('sport') == 'soccer']
    # Spoken names often omit an apostrophe or a separator. If the full-name
    # search found nothing, retrieve surname candidates; still compare identities.
    if not rows and kind=='player' and len(query.split())>=2:
        fallback=await get('https://site.web.api.espn.com/apis/search/v2', {'query':query.split()[-1], 'limit':20})
        rows=[r for group in fallback.get('results',[]) if group.get('type')=='player' for r in group.get('contents',[])
              if (all_sports or r.get('sport')=='soccer') and normalized(r.get('displayName','')).replace(' ','')==normalized(query).replace(' ','')]
    if args.get('sport'):
        sport = {'american football':'football','american-football':'football','f1':'racing','formula 1':'racing','ice hockey':'hockey'}.get(args['sport'].lower(), args['sport'].lower())
        rows = [r for r in rows if r.get('sport') == sport]
    if args.get('team'):
        named = normalized(args['team'])
        rows = [r for r in rows if named in normalized(r.get('subtitle','')) or named in normalized(r.get('displayName',''))]
    if args.get('competition'):
        rows = [r for r in rows if args['competition']==r.get('defaultLeagueSlug') or normalized(args['competition']) in normalized(r.get('subtitle',''))]
    if args.get('entity_id'):
        rows = [r for r in rows if r.get('uid','').split(':')[-1] == args['entity_id']]
    exact = [r for r in rows if normalized(r.get('displayName','')).replace(' ','') == normalized(query).replace(' ','')]
    # The standard Barcelona name denotes the men's first team; explicitly retain
    # its competition on the card. Other same-name teams/players require context.
    if normalized(query)=='barcelona' and not args.get('competition') and not args.get('entity_id'):
        exact = [r for r in exact if r.get('defaultLeagueSlug')=='esp.1']
    matches = exact or rows
    choices = [{'id':numeric_id(r['uid'].split(':')[-1]), 'kind':'sports_choice','title':r['displayName'],
                'detail':' · '.join(filter(None,[r.get('subtitle',''),r.get('description','')])), 'url':public_url(r.get('link',{}).get('web')),
                'sport':r.get('sport',''),
                'logo':public_url(r.get('image',{}).get('default')), 'entity_type':kind} for r in matches[:6]]
    # A single first name is ambiguous even if the search service returns one hit.
    if len(matches)!=1 or (kind=='player' and len(normalized(query).split())<2 and not args.get('entity_id')):
        return None, choices
    return {**matches[0], 'record_id':numeric_id(matches[0]['uid'].split(':')[-1])}, choices


def completed_matches(data, now):
    found = {}
    for event in data.get('events',[]):
        comp = next(iter(event.get('competitions', [])), {})
        status = comp.get('status',{}).get('type',{})
        try: instant = datetime.fromisoformat(event['date'].replace('Z','+00:00'))
        except (KeyError, ValueError): continue
        # Postponements/cancellations and future events must never become scores.
        if not status.get('completed') or status.get('state')!='post' or instant>now: continue
        if status.get('name') in ('STATUS_CANCELED','STATUS_POSTPONED','STATUS_ABANDONED'): continue
        competitors = {r.get('homeAway'):r for r in comp.get('competitors',[])}
        if set(competitors)!= {'home','away'}: continue
        home, away = competitors['home'], competitors['away']
        def score(row):
            s = row.get('score')
            return str(s.get('displayValue','')) if isinstance(s,dict) else str(s if s is not None else '')
        hs, aws = score(home), score(away)
        if not hs.isdigit() or not aws.isdigit(): continue
        eid = numeric_id(event['id'])
        found[eid] = {'id':eid,'date':event['date'], 'competition':event.get('league',{}).get('name') or event.get('season',{}).get('displayName') or event.get('seasonType',{}).get('name',''),
            'home':home['team'].get('displayName','Home'), 'away':away['team'].get('displayName','Away'),
            'home_id':str(home['id']), 'away_id':str(away['id']), 'home_logo':badge(home['team']), 'away_logo':badge(away['team']),
            'home_score':int(hs), 'away_score':int(aws), 'status':status.get('shortDetail','FT'),
            'home_winner':home.get('winner'), 'away_winner':away.get('winner'),
            'home_penalties':home.get('score',{}).get('shootoutScore') if isinstance(home.get('score'),dict) else None,
            'away_penalties':away.get('score',{}).get('shootoutScore') if isinstance(away.get('score'),dict) else None,
            'url':f'https://www.espn.com/soccer/match/_/gameId/{eid}'}
    return sorted(found.values(), key=lambda row:row['date'], reverse=True)


def player_appearance(summary, player_id):
    for team in summary.get('rosters',[]):
        for row in team.get('roster',[]):
            if str(row.get('athlete',{}).get('id'))!=player_id: continue
            stats = {s['name']:s.get('value') for s in row.get('stats',[]) if s.get('name')}
            # Being on the bench is not an appearance. Missing data stays missing.
            played = stats.get('appearances', 0)>0 or row.get('starter') is True or row.get('subbedIn') is True
            if not played: return None
            return {label:stats.get(key) for label,key in [('goals','totalGoals'),('assists','goalAssists'),('shots','totalShots'),('minutes','minutesPlayed')]}
    return None


async def football(args, get, now=None, *, entity=None):
    now = now or datetime.now(timezone.utc)
    if entity is None: entity, choices = await resolve_entity(args, get)
    base = {'status':'completed','source':'ESPN · public match records','provenance':'live','retrieved_at':now.isoformat()}
    if not entity:
        return {**base,'items':choices,'needs_clarification':True,
                'summary':'Ask which of the returned teams/players the user means. Do not select a player just from their first name.',
                'note':'No matching football record was found. Try the full team or player name.'}
    player = args.get('entity_type')=='player'
    record_id = entity['record_id']
    if player:
        profile = (await get(f'https://site.web.api.espn.com/apis/common/v3/sports/soccer/all/athletes/{record_id}', {}))['athlete']
        team = profile['team']; team_id = numeric_id(team['id'])
    else:
        team_id = record_id
    schedule_url = f'https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{team_id}/schedule'
    schedule = await get(schedule_url, {})
    team = schedule.get('team', {})
    events = completed_matches(schedule, now)
    limit = args.get('limit',5)
    if len(events) < limit:
        year = schedule.get('season',{}).get('year',now.year)
        older = await get(schedule_url, {'season':int(year)-1})
        events = completed_matches({'events':schedule.get('events',[])+older.get('events',[])}, now)
    warnings = []
    if player:
        matches = []
        # Bounded concurrency, up to 16 completed club fixtures; no roster scraping
        # outside the named player's current team and no inferred appearances.
        for offset in range(0, min(len(events),16), 4):
            batch = events[offset:offset+4]
            responses = await asyncio.gather(*(get('https://site.api.espn.com/apis/site/v2/sports/soccer/all/summary', {'event':e['id']}) for e in batch), return_exceptions=True)
            for event, response in zip(batch, responses):
                if isinstance(response,Exception): warnings.append(f'Match {event["id"]}: player record unavailable.'); continue
                stats = player_appearance(response, record_id)
                if stats is not None: matches.append({**event, **stats})
            if len(matches)>=limit: break
        events = matches
    events = events[:limit]
    for event in events:
        own = event['home_score'] if event['home_id']==team_id else event['away_score']
        other = event['away_score'] if event['home_id']==team_id else event['home_score']
        winner = event['home_winner'] if event['home_id']==team_id else event['away_winner']
        event['result'] = ('W' if winner else 'L') if 'Pens' in event['status'] and winner is not None else 'W' if own>other else 'L' if own<other else 'D'
    scope = f'{team.get("displayName", "Current club")} · all returned club competitions, including friendlies'
    if len(events)<limit: warnings.append(f'Only {len(events)} verified records were available in the bounded current-club search; do not claim {limit}.')
    if warnings: scope += ' · incomplete coverage'
    item = {'id':'football-'+record_id,'kind':'sports','title':entity['displayName'], 'entity_type':'player' if player else 'team',
            'sport':'soccer', 'portrait':public_url(entity.get('image',{}).get('default')) if player else '',
            'team':team.get('displayName',''), 'logo':badge(team), 'matches':events, 'scope':scope,
            'requested_count':limit,'warnings':warnings,'url':public_url(entity.get('link',{}).get('web')),
            'goals':sum(e['goals'] for e in events) if player and events and all(e.get('goals') is not None for e in events) else None,
            'assists':sum(e['assists'] for e in events) if player and events and all(e.get('assists') is not None for e in events) else None}
    return {**base,'items':[item],'summary':f'{entity["displayName"]}: {len(events)} most recent verified '+('appearances' if player else 'completed matches')+f'. Scope: {scope}. Use exact dates, scores and only the returned player statistics. '+ ' '.join(warnings)}
