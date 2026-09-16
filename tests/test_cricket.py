from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock, patch

from thread_agent.cricket import parse_innings, cricket_log

NOW=datetime(2026,9,13,tzinfo=timezone.utc)
URL='https://www.cricbuzz.com/profiles/12/example-player/all-matches/batting'


def page(rows, name='Example Player', bowling=False):
    headers=['Wickets' if bowling else 'Score','OPPN.','Format','Venue','Date',*(['Economy','Overs','Maidens'] if bowling else ['SR','4s','6s'])]
    return '<h1>'+name+'</h1><table><tr>'+''.join('<th>'+h+'</th>' for h in headers)+'</tr>'+''.join('<tr>'+''.join('<td>'+str(c)+'</td>' for c in row)+'</tr>' for row in rows)+'</table>'


class CricketParsingTests(unittest.TestCase):
    def test_player_identity_must_match_the_actual_page(self):
        with self.assertRaises(ValueError):parse_innings(page([],name='Different Person'),'Example Player',NOW,URL)

    def test_batting_preserves_not_out_and_zero(self):
        rows=[['A series'],['75*(42)','ENG','ODI','London','19 Jul 26','178.5','9','3'],['0(1)','ENG','ODI','London','16 Jul 26','0','0','0']]
        records=parse_innings(page(rows),'Example Player',NOW,URL)
        self.assertEqual(records[0]['score'],'75*(42)');self.assertTrue(records[0]['not_out'])
        self.assertEqual(records[1]['stats'][0]['value'],'0');self.assertFalse(records[1]['not_out'])

    def test_did_not_bat_and_future_rows_are_excluded(self):
        rows=[['DNB','ENG','ODI','London','19 Jul 26','—','—','—'],['50(40)','ENG','ODI','London','19 Dec 26','125','4','1']]
        self.assertEqual(parse_innings(page(rows),'Example Player',NOW,URL),[])

    def test_format_filter_does_not_mix_odi_and_t20(self):
        rows=[['50(40)','ENG','ODI','London','19 Jul 26','125','4','1'],['30(20)','GT','T20','Mumbai','18 Jul 26','150','2','1']]
        records=parse_innings(page(rows),'Example Player',NOW,URL,match_format='ODI')
        self.assertEqual(len(records),1);self.assertEqual(records[0]['format'],'ODI')

    def test_two_test_innings_are_not_collapsed_into_one_match(self):
        row=['0(1)','ENG','Test','London','19 Jul 26','0','0','0']
        records=parse_innings(page([row,row]),'Example Player',NOW,URL)
        self.assertEqual(len(records),2);self.assertNotEqual(records[0]['id'],records[1]['id'])

    def test_bowling_retains_figures_and_cricket_overs(self):
        records=parse_innings(page([['2-35','ENG','ODI','London','19 Jul 26','3.8','9.1','0']],bowling=True),'Example Player',NOW,URL,skill='bowling')
        self.assertEqual(records[0]['score'],'2-35')
        self.assertEqual(next(s['value'] for s in records[0]['stats'] if s['key']=='overs'),'9.1')

    def test_unrelated_tables_are_not_statistics(self):
        self.assertEqual(parse_innings('<h1>Example Player</h1><table><tr><td>Click here</td></tr></table>','Example Player',NOW,URL),[])


class CricketSourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_cricket_card_links_to_the_statistics_provider(self):
        from thread_agent.sports import recent_sports
        entity={'sport':'cricket','displayName':'Example Player','record_id':'12','link':{'web':'https://www.espncricinfo.com/ci/content/player/12.html'}}
        record={'id':'one','date':'2026-07-19','url':URL,'score':'75*(42)','stats':[]}
        with patch('thread_agent.sports.resolve_entity',new=AsyncMock(return_value=(entity,[]))),patch('thread_agent.cricket.cricket_log',new=AsyncMock(return_value=([record],[],'Verified innings','Cricbuzz'))):
            result=await recent_sports({'query':'Example Player','entity_type':'player','limit':1},AsyncMock(),NOW)
        self.assertEqual(result['items'][0]['url'],URL)
        self.assertEqual(result['source'],'Cricbuzz')

    async def test_dynamic_profile_discovery_and_weighted_metrics(self):
        rows=[['75*(42)','ENG','ODI','London','19 Jul 26','178.5','9','3'],['25(20)','ENG','ODI','London','16 Jul 26','125','2','1']]
        source={'items':[{'title':'Example Player Profile','url':URL}]}
        with patch('thread_agent.cricket.search_web',new=AsyncMock(return_value=source)),patch('thread_agent.cricket.fetch_feed',new=AsyncMock(return_value=page(rows).encode())):
            records,metrics,scope,provider=await cricket_log({'displayName':'Example Player'},{'limit':5},None,NOW)
        self.assertEqual(provider,'Cricbuzz');self.assertEqual(len(records),2)
        self.assertEqual(metrics[0]['value'],'100');self.assertEqual(metrics[1]['value'],'100.0')
        self.assertEqual(metrics[2]['value'],'161.3');self.assertIn('first page only',scope)

    async def test_untrusted_search_link_cannot_choose_a_network_host(self):
        source={'items':[{'title':'Example Player Profile','url':'https://attacker.invalid/profiles/12/example-player'}]}
        with patch('thread_agent.cricket.search_web',new=AsyncMock(return_value=source)),patch('thread_agent.cricket.fetch_feed',new=AsyncMock()) as fetch:
            with self.assertRaises(ValueError):await cricket_log({'displayName':'Example Player'},{'limit':5},None,NOW)
        fetch.assert_not_awaited()
