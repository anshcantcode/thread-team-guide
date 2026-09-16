import unittest
from datetime import datetime, timezone
from thread_agent.capabilities import execute, safe_execute

class WorldClocksTests(unittest.IsolatedAsyncioTestCase):
    async def test_requested_cities_share_one_instant_and_survive_dst(self):
        args={'locations':[{'label':'Manchester','zone':'Europe/London'},{'label':'Barcelona','zone':'Europe/Madrid'}]}
        for instant, expected in [('2026-01-15T12:00:00+00:00',['12:00','13:00']),('2026-07-15T12:00:00+00:00',['13:00','14:00']),('2026-03-29T00:59:00+00:00',['00:59','01:59']),('2026-03-29T01:01:00+00:00',['02:01','03:01']),('2026-10-25T01:01:00+00:00',['01:01','02:01'])]:
            with self.subTest(instant=instant):
                result=await execute('world_clocks',args,now=datetime.fromisoformat(instant))
                self.assertEqual([i['value'] for i in result['items']],expected)
                self.assertEqual(result['provenance'],'computed')
                self.assertEqual([i['zone'] for i in result['items']],['Europe/London','Europe/Madrid'])
    async def test_four_cities_fractional_offsets_and_date_rollover(self):
        zones=['Pacific/Honolulu','Asia/Kolkata','Asia/Kathmandu','Pacific/Kiritimati']
        result=await execute('world_clocks',{'locations':[{'label':z,'zone':z} for z in zones]},now=datetime(2026,1,15,12,tzinfo=timezone.utc))
        self.assertEqual([i['value'] for i in result['items']],['02:00','17:30','17:45','02:00'])
        self.assertEqual(result['items'][-1]['date'],'2026-01-16')
        self.assertEqual(len({i['id'] for i in result['items']}),4)
    async def test_invalid_zone_rejects_whole_clock_group(self):
        for zone in ['Manchester','Europe/Barca','../../etc/passwd','/usr/share/zoneinfo/UTC','America/Not_A_Place']:
            with self.subTest(zone=zone):
                result=await safe_execute('world_clocks',{'locations':[{'label':'Valid','zone':'Europe/London'},{'label':'Invalid','zone':zone}]})
                self.assertEqual(result['status'],'failed');self.assertFalse(result.get('items'))
    async def test_closed_bounded_location_schema(self):
        valid={'label':'Tokyo','zone':'Asia/Tokyo'}
        for locations in [[],[valid]*5,[valid,valid],[{'label':'','zone':'UTC'}],[{'label':'City','zone':None}],[{**valid,'time':'invented'}]]:
            with self.subTest(locations=locations):
                result=await safe_execute('world_clocks',{'locations':locations});self.assertEqual(result['status'],'failed')
    async def test_refresh_preserves_locations_without_calling_an_ai(self):
        from fastapi.testclient import TestClient
        from thread_agent.server import app
        with TestClient(app) as client:
            result=client.post('/api/widgets/refresh',json={'modules':[{'id':'clocks','domain':'world_clocks','arguments':{'locations':[{'label':'Manchester','zone':'Europe/London'}]}}]}).json()['results'][0]
        self.assertEqual(result['id'],'clocks');self.assertEqual(result['items'][0]['zone'],'Europe/London')
        self.assertEqual(result['status'],'completed')
if __name__=='__main__':unittest.main()
