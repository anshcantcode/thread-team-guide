"""Evidence parsing, identity, freshness and appearance checks; no live network calls."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock

from thread_agent.online import completed_matches, player_appearance, parse_feed, football, resolve_entity, search_web, public_url
from thread_agent.capabilities import validate

NOW=datetime(2026,9,13,tzinfo=timezone.utc)


def event(eid='123', at='2026-09-09T16:45Z'):
    return {'id':eid,'date':at,'seasonType':{'name':'Champions League'},'competitions':[{
        'status':{'type':{'state':'post','completed':True,'name':'STATUS_FULL_TIME','shortDetail':'FT'}},
        'competitors':[{'id':'83','homeAway':'home','winner':True,'team':{'displayName':'Barcelona','logo':'https://a.espncdn.com/i/83.png'},'score':{'displayValue':'5'}},
                       {'id':'12','homeAway':'away','winner':False,'team':{'displayName':'Feyenoord'},'score':{'displayValue':'1'}}]}]}


def person(name, pid, team):
    return {'sport':'soccer','uid':'s:600~a:'+pid,'displayName':name,'subtitle':team,'link':{'web':'https://www.espn.com/soccer/player/_/id/'+pid}}


class OnlineEvidenceTests(unittest.IsolatedAsyncioTestCase):
    def test_completed_results_sort_and_dedupe(self):
        rows=completed_matches({'events':[event('1','2026-08-01T20:00Z'),event('2'),event('2')]},NOW)
        self.assertEqual([r['id'] for r in rows],['2','1'])
        self.assertEqual((rows[0]['home_score'],rows[0]['away_score']),(5,1))

    def test_scheduled_postponed_cancelled_and_future_events_are_not_results(self):
        for field,value in [('completed',False),('state','pre'),('name','STATUS_POSTPONED'),('name','STATUS_CANCELED'),('name','STATUS_ABANDONED')]:
            with self.subTest(field=field,value=value):
                row=event();row['competitions'][0]['status']['type'][field]=value
                self.assertEqual(completed_matches({'events':[row]},NOW),[])
        self.assertEqual(completed_matches({'events':[event(at='2026-10-01T12:00Z')]},NOW),[])

    def test_missing_scores_do_not_become_zero(self):
        row=event();row['competitions'][0]['competitors'][0]['score']={}
        self.assertEqual(completed_matches({'events':[row]},NOW),[])

    def test_competition_name_is_not_replaced_by_tournament_phase(self):
        row=event();row['seasonType']['name']='League Phase'
        row['season']={'displayName':'2026-27 UEFA Champions League'}
        row['league']={'name':'UEFA Champions League'}
        self.assertEqual(completed_matches({'events':[row]},NOW)[0]['competition'],'UEFA Champions League')
        del row['league']
        self.assertEqual(completed_matches({'events':[row]},NOW)[0]['competition'],'2026-27 UEFA Champions League')

    def test_penalties_are_preserved_separately_from_match_score(self):
        row=event();row['competitions'][0]['competitors'][0]['score']['shootoutScore']=4
        parsed=completed_matches({'events':[row]},NOW)[0]
        self.assertEqual(parsed['home_penalties'],4);self.assertEqual(parsed['home_score'],5)

    def test_bench_is_not_an_appearance(self):
        row={'athlete':{'id':'7'},'starter':False,'subbedIn':False,'stats':[{'name':'appearances','value':0}]}
        self.assertIsNone(player_appearance({'rosters':[{'roster':[row]}]},'7'))
        row['subbedIn']=True
        result=player_appearance({'rosters':[{'roster':[row]}]},'7')
        self.assertIsNone(result['goals']);self.assertIsNone(result['minutes'])

    def test_stats_belong_to_requested_player(self):
        rows=[{'athlete':{'id':pid},'starter':True,'stats':[{'name':'totalGoals','value':goals}]} for pid,goals in [('6',3),('7',0)]]
        result=player_appearance({'rosters':[{'roster':rows}]},'7')
        self.assertEqual(result['goals'],0);self.assertIsNone(result['assists'])
        self.assertIsNone(player_appearance({'rosters':[{'roster':rows}]},'8'))

    async def test_bruno_requires_disambiguation(self):
        get=AsyncMock(return_value={'results':[{'type':'player','contents':[person('Bruno Fernandes','124091','Manchester United'),person('Bruno Guimarães','218522','Arsenal')]}]})
        entity,choices=await resolve_entity({'query':'Bruno','entity_type':'player'},get)
        self.assertIsNone(entity);self.assertEqual(len(choices),2)
        entity,_=await resolve_entity({'query':'Bruno Fernandes','entity_type':'player','team':'Manchester United'},get)
        self.assertEqual(entity['record_id'],'124091')

    async def test_named_id_must_be_returned_for_this_query(self):
        get=AsyncMock(return_value={'results':[{'type':'player','contents':[person('Bruno Fernandes','7','Manchester United')]}]})
        entity,_=await resolve_entity({'query':'Bruno Fernandes','entity_type':'player','entity_id':'999'},get)
        self.assertIsNone(entity)

    async def test_football_end_to_end_selects_actual_appearances(self):
        events=[event(str(i),f'2026-09-0{i}T12:00Z') for i in range(1,7)]
        async def get(url,params):
            if '/search/' in url:return {'results':[{'type':'player','contents':[person('Bruno Fernandes','7','Barcelona')]}]}
            if '/athletes/' in url:return {'athlete':{'team':{'id':'83'}}}
            if '/schedule' in url:return {'season':{'year':2026},'team':{'displayName':'Barcelona','id':'83'},'events':events}
            return {'rosters':[{'roster':[{'athlete':{'id':'7'},'starter':params['event']!='6','stats':[{'name':'totalGoals','value':1},{'name':'goalAssists','value':0}]}]}]}
        result=await football({'query':'Bruno Fernandes','entity_type':'player','limit':5},get,NOW)
        item=result['items'][0]
        self.assertEqual([m['id'] for m in item['matches']],['5','4','3','2','1'])
        self.assertEqual(item['goals'],5);self.assertEqual(item['assists'],0)
        self.assertEqual(item['warnings'],[])

    async def test_short_coverage_is_explicit(self):
        async def get(url,params):
            if '/search/' in url:return {'results':[{'type':'team','contents':[{'sport':'soccer','uid':'s:600~t:83','displayName':'Barcelona','defaultLeagueSlug':'esp.1'}]}]}
            return {'season':{'year':2026},'team':{'displayName':'Barcelona'},'events':[event()]}
        result=await football({'query':'Barcelona','entity_type':'team','limit':5},get,NOW)
        self.assertEqual(len(result['items'][0]['matches']),1)
        self.assertIn('Only 1 verified',result['summary'])

    def test_search_keeps_publisher_dates_and_escapes_html(self):
        raw=b'<rss><channel><item><title>Title &amp; more</title><link>https://example.com/a</link><description>&lt;b&gt;Snippet&lt;/b&gt;</description><pubDate>Sun, 13 Sep 2026 08:00:00 GMT</pubDate><source>Publisher</source></item><item><title>Duplicate</title><link>https://example.com/a</link></item><item><title>Bad</title><link>javascript:alert(1)</link></item></channel></rss>'
        rows=parse_feed(raw,'test',8)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['detail'],'Snippet');self.assertEqual(rows[0]['provider'],'Publisher')
        self.assertTrue(rows[0]['published'].startswith('2026-09-13'))

    async def test_news_recency_is_in_provider_query(self):
        feed=AsyncMock(return_value=b'<rss><channel/></rss>')
        r=await search_web({'query':'Barcelona','mode':'news','recency':'week'},feed)
        self.assertEqual(feed.call_args.args[1]['q'],'Barcelona when:7d');self.assertEqual(r['items'],[])

    def test_links_reject_executable_and_credential_urls(self):
        for url in ['javascript:alert(1)','file:///secret','https://user:secret@example.com','https://[invalid']:
            self.assertEqual(public_url(url),'')

    def test_closed_search_schemas(self):
        for domain,args in [('sports',{'query':'Barcelona','entity_type':'team','limit':100}),('sports',{'query':'Bruno','entity_type':'player','entity_id':'../../secret'}),('web',{'query':'x','mode':'shell'}),('web',{'query':'x','url':'http://localhost'})]:
            with self.subTest(domain=domain,args=args),self.assertRaises(ValueError):validate(domain,args)
