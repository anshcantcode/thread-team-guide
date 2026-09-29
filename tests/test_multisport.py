import unittest
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from thread_agent.online import resolve_entity
from thread_agent.sports import parse_gamelog, parse_tennis, parse_races, highlights, recent_sports, enrich_identity, past, slug

NOW=datetime(2026,9,13,tzinfo=timezone.utc)


def game_log():
    return {'names':['points','totalRebounds','assists'],'displayNames':['Points','Rebounds','Assists'],
        'events':{'1':{'gameDate':'2026-05-12T02:30Z','homeTeamId':'13','awayTeamId':'25','homeTeamScore':'110','awayTeamScore':'115',
            'gameResult':'L','team':{'id':'13','abbreviation':'LAL'},'opponent':{'displayName':'Thunder'},'leagueShortName':'NBA',
            'links':[{'rel':['desktop'],'href':'https://www.espn.com/nba/game/_/gameId/1'}]}},
        'seasonTypes':[{'displayName':'2025–26 Postseason','categories':[{'events':[{'eventId':'1','stats':['24','12','3']}]}]}]}


def tennis_board():
    return {'events':[{'name':'US Open','groupings':[{'grouping':{'slug':'mens-singles'},'competitions':[{
        'id':'123','date':'2026-09-01T12:00Z','status':{'type':{'completed':True,'state':'post','name':'STATUS_FINAL'}},
        'competitors':[{'id':'7','athlete':{'displayName':'Player One'},'winner':True,'linescores':[{'value':6},{'value':7}]},
                       {'id':'8','athlete':{'displayName':'Player Two'},'winner':False,'linescores':[{'value':3},{'value':6}]}]}]}]}]}


class SportParsingTests(unittest.TestCase):
    def test_game_log_joins_stats_to_athlete_event(self):
        row=parse_gamelog(game_log(),NOW)[0]
        self.assertEqual(row['score'],'110 – 115')
        self.assertEqual(row['title'],'Thunder')
        self.assertEqual(row['stats'][0],{'key':'points','label':'Points','value':'24'})

    def test_away_score_is_from_athlete_team_perspective(self):
        d=game_log();d['events']['1']['team']['id']='25'
        self.assertEqual(parse_gamelog(d,NOW)[0]['score'],'115 – 110')

    def test_dnp_is_not_a_recorded_appearance(self):
        for values in (['DNP'],['—','—'],[]):
            d=game_log();d['seasonTypes'][0]['categories'][0]['events'][0]['stats']=values
            self.assertEqual(parse_gamelog(d,NOW),[])

    def test_zero_is_distinct_from_dnp(self):
        d=game_log();d['seasonTypes'][0]['categories'][0]['events'][0]['stats']=['0','0','0']
        self.assertEqual(parse_gamelog(d,NOW)[0]['stats'][0]['value'],'0')

    def test_future_schedule_cannot_become_a_recent_result(self):
        d=game_log();d['events']['1']['gameDate']='2027-01-01T12:00Z'
        self.assertEqual(parse_gamelog(d,NOW),[])

    def test_missing_score_is_not_zero(self):
        d=game_log();del d['events']['1']['homeTeamScore']
        self.assertEqual(parse_gamelog(d,NOW),[])

    def test_duplicate_season_categories_do_not_duplicate_games(self):
        d=game_log();d['seasonTypes'].append(deepcopy(d['seasonTypes'][0]))
        self.assertEqual(len(parse_gamelog(d,NOW)),1)

    def test_basketball_averages_are_only_over_selected_records(self):
        rows=parse_gamelog(game_log(),NOW)
        other=deepcopy(rows[0]);other['stats'][0]['value']='20';rows.append(other)
        metric=highlights(rows,'basketball')[0]
        self.assertEqual(metric,{'label':'Points / game','value':'22.0'})

    def test_missing_or_nonfinite_stats_do_not_produce_totals(self):
        rows=parse_gamelog(game_log(),NOW)
        rows[0]['stats'][0]['value']='NaN'
        self.assertNotIn('Points / game',[m['label'] for m in highlights(rows,'basketball')])

    def test_passing_and_rushing_yards_are_not_mixed(self):
        rows=[{'stats':[{'key':'passingYards','label':'Passing yards','value':'250'},{'key':'rushingYards','label':'Rushing yards','value':'30'}]}]
        self.assertEqual(highlights(rows,'football'),[{'label':'Passing yards','value':'250'},{'label':'Rushing yards','value':'30'}])

    def test_tennis_preserves_individual_set_scores(self):
        row=parse_tennis(tennis_board(),'7','atp',NOW)[0]
        self.assertEqual(row['score'],'6–3  7–6');self.assertEqual(row['result'],'W')
        self.assertEqual(row['title'],'Player Two')

    def test_tennis_summary_uses_only_the_selected_completed_matches(self):
        records=[{'result':r} for r in ['W','L','W','W','L']]
        self.assertEqual(highlights(records,'tennis'),[{'label':'Wins','value':'3'},{'label':'Losses','value':'2'},{'label':'Matches','value':'5'}])
        self.assertEqual(highlights(records+[{'result':''}],'tennis'),[])

    def test_race_summary_counts_finishes_and_excludes_missing_points(self):
        records=[{'score':p,'stats':[{'key':'points','value':v}]} for p,v in [('P1','25'),('P3','15'),('R','0'),('P4','12')]]
        self.assertEqual(highlights(records,'racing'),[{'label':'Wins','value':'1'},{'label':'Podiums','value':'2'},{'label':'Points','value':'52'}])
        for value in ('NaN','unavailable'):
            records[-1]['stats'][0]['value']=value
            self.assertEqual(len(highlights(records,'racing')),2)
        records[-1]['stats']=[]
        self.assertEqual(len(highlights(records,'racing')),2)

    def test_tennis_does_not_confuse_athletes_or_singles_and_doubles(self):
        self.assertEqual(parse_tennis(tennis_board(),'999','atp',NOW),[])
        d=tennis_board();d['events'][0]['groupings'][0]['grouping']['slug']='mens-doubles'
        self.assertEqual(parse_tennis(d,'7','atp',NOW),[])

    def test_womens_tennis_uses_its_own_group(self):
        d=tennis_board();d['events'][0]['groupings'][0]['grouping']['slug']='womens-singles'
        self.assertEqual(len(parse_tennis(d,'7','wta',NOW)),1)
        self.assertEqual(parse_tennis(d,'7','atp',NOW),[])

    def test_unfinished_and_walkover_tennis_are_excluded(self):
        for update in ({'completed':False},{'name':'STATUS_WALKOVER'},{'state':'in'}):
            d=tennis_board();d['events'][0]['groupings'][0]['competitions'][0]['status']['type'].update(update)
            self.assertEqual(parse_tennis(d,'7','atp',NOW),[])

    def test_formula_one_record_belongs_to_driver(self):
        d={'MRData':{'RaceTable':{'Races':[{'season':'2026','round':'4','date':'2026-04-01','raceName':'Example GP',
            'Results':[{'Driver':{'driverId':'driver_one'},'positionText':'R','grid':'5','points':'0','status':'Engine'}]}]}}}
        row=parse_races(d,'driver_one',NOW)[0]
        self.assertEqual(row['score'],'R');self.assertEqual(row['stats'][1]['value'],'0')
        self.assertEqual(parse_races(d,'driver_two',NOW),[])

    def test_provider_path_segments_are_validated(self):
        for value in ('../nba','nba/teams','nba?key=secret','http://other','..'):
            with self.assertRaises(ValueError):slug(value)
        self.assertEqual(slug('women-college-basketball'),'women-college-basketball')

    def test_naive_dates_do_not_silently_assume_timezone(self):
        self.assertFalse(past('2026-01-01',NOW));self.assertFalse(past('bad date',NOW))


class SportRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_profile_identity_uses_only_supplied_publisher_fields(self):
        item={'title':'Example Player','logo':'https://a.espncdn.com/existing.png'}
        entity={'sport':'basketball','defaultLeagueSlug':'wnba','record_id':'123'}
        get=AsyncMock(return_value={'athlete':{'team':{'displayName':'Example Club','logos':[None,{'href':'https://a.espncdn.com/club.png'}]},'position':{'displayName':'Center'},'jersey':'22','flag':{'href':'javascript:bad'},'birthPlace':{'country':'Example Country'}}})
        await enrich_identity(entity,item,get)
        self.assertEqual((item['team'],item['position'],item['jersey']),('Example Club','Center','22'))
        self.assertEqual(item['logo'],'https://a.espncdn.com/club.png')
        self.assertEqual(item['country'],'');self.assertEqual(item['flag'],'')
        self.assertNotIn('portrait',item)

    async def test_optional_identity_failure_preserves_the_result(self):
        item={'records':[{'score':'3 – 0'}],'portrait':'https://a.espncdn.com/player.png'}
        original=deepcopy(item)
        get=AsyncMock(side_effect=TimeoutError())
        await enrich_identity({'sport':'tennis','defaultLeagueSlug':'atp','record_id':'123'},item,get)
        self.assertEqual(item,original)

    async def test_spoken_name_without_apostrophe_uses_verified_surname_candidate(self):
        get=AsyncMock(side_effect=[{'results':[]},{'results':[{'type':'player','contents':[
            {'sport':'basketball','displayName':"A'ja Wilson",'uid':'s:40~a:1','defaultLeagueSlug':'wnba'},
            {'sport':'football','displayName':'Russell Wilson','uid':'s:20~a:2','defaultLeagueSlug':'nfl'}]}]}])
        entity,choices=await resolve_entity({'query':'Aja Wilson','entity_type':'player','sport':'basketball'},get,all_sports=True)
        self.assertEqual(entity['record_id'],'1');self.assertEqual(len(choices),1)
        self.assertEqual(get.await_args.args[1]['query'],'Wilson')

    async def test_identity_search_supports_multiple_sports_and_women(self):
        rows=[{'sport':sport,'displayName':name,'uid':'s:40~a:'+pid,'defaultLeagueSlug':league} for sport,name,pid,league in
              [('basketball','Aja Wilson','1','wnba'),('cricket','Aja Wilson','2','all')]]
        get=AsyncMock(return_value={'results':[{'type':'player','contents':rows}]})
        entity,choices=await resolve_entity({'query':'Aja Wilson','entity_type':'player','sport':'basketball'},get,all_sports=True)
        self.assertEqual(entity['record_id'],'1');self.assertEqual(entity['defaultLeagueSlug'],'wnba')
        self.assertEqual(choices[0]['sport'],'basketball')

    async def test_first_name_never_picks_a_sport_or_identity_automatically(self):
        get=AsyncMock(return_value={'results':[{'type':'player','contents':[{'sport':'basketball','displayName':'Jordan Clarkson','uid':'s:40~a:1','defaultLeagueSlug':'nba'}]}]})
        entity,choices=await resolve_entity({'query':'Jordan','entity_type':'player'},get,all_sports=True)
        self.assertIsNone(entity);self.assertEqual(len(choices),1)

    async def test_unknown_coverage_uses_sources_not_fictional_stats(self):
        get=AsyncMock(return_value={'results':[{'type':'player','contents':[{'sport':'archery','displayName':'Test Archer','uid':'s:200~a:123'}]}]})
        with patch('thread_agent.sports.search_web',new=AsyncMock(return_value={'source':'Test search','items':[]})):
            result=await recent_sports({'query':'Test Archer','entity_type':'player','sport':'archery','limit':5},get,NOW)
        self.assertEqual(result['coverage_status'],'unavailable')
        self.assertEqual(result['items'][0]['records'],[])
        self.assertIn('NOT verified',result['summary'])

    async def test_no_identity_still_attempts_web_discovery(self):
        get=AsyncMock(return_value={'results':[]})
        with patch('thread_agent.sports.search_web',new=AsyncMock(return_value={'source':'Test search','items':[]})) as search:
            result=await recent_sports({'query':'An unfamiliar athlete','entity_type':'player','sport':'archery','limit':5},get,NOW)
        search.assert_awaited_once();self.assertEqual(result['items'],[])
        self.assertEqual(result['coverage_status'],'unavailable')
