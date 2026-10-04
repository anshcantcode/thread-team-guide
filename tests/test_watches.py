import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from thread_agent.action_chains import authorize_watch
from thread_agent.engine import Session
from thread_agent.live import LiveConversation
from thread_agent.phone import watch_schemas
from thread_agent.watches import WatchStore, cadence, news_url, parse_rss

FIXTURES = Path(__file__).parent / 'fixtures' / 'watches'


class RssTests(unittest.TestCase):
    def test_saved_fixture_parses_sources_dates_and_deduplicates_in_source_order(self):
        rows = parse_rss((FIXTURES / 'news.xml').read_bytes())
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['source'], 'Example Journal')
        self.assertEqual(rows[1]['title'], 'Committee releases a timetable & review notes')
        self.assertEqual(rows[0]['published_at'], 1791030600000)
        self.assertEqual(len(rows[0]['id']), 64)
        self.assertTrue(all(row['link'].startswith('https://') for row in rows))

    def test_rejects_non_rss_entities_and_oversized_input_without_fetching(self):
        for xml in (b'<html/>', b'<!DOCTYPE rss [<!ENTITY a SYSTEM "file:///secret">]><rss><channel/></rss>', '<!DOCTYPE rss><rss><channel/></rss>'.encode('utf-16'), b'x' * 512001):
            with self.subTest(xml=xml[:50]), self.assertRaises(ValueError): parse_rss(xml)

    def test_missing_source_or_bad_date_is_not_invented(self):
        rows = parse_rss('<rss><channel><item><title>Headline</title><link>https://example.com/x</link><pubDate>unknown</pubDate></item></channel></rss>')
        self.assertEqual(rows[0]['source'], 'Source not supplied')
        self.assertIsNone(rows[0]['published_at'])

    def test_query_is_encoded_and_has_indian_edition(self):
        url = urlparse(news_url('City & council? review'))
        self.assertEqual(url.hostname, 'news.google.com')
        self.assertEqual(parse_qs(url.query), {'q': ['City & council? review'], 'hl': ['en-IN'], 'gl': ['IN'], 'ceid': ['IN:en']})


class WatchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = 1791030000000
        self.initial = parse_rss((FIXTURES / 'news.xml').read_bytes())
        self.next = parse_rss((FIXTURES / 'news-next.xml').read_bytes())
        self.fetch = AsyncMock(return_value=self.initial)
        self.store = WatchStore(Path(self.temp.name) / 'watches.json', fetch=self.fetch, clock=lambda: self.now)
        self.row = self.store.create({'topic': 'City council', 'every_hours': 2})
        self.ref = {'id': self.row['id']}

    async def asyncTearDown(self):
        await self.store.close()
        self.temp.cleanup()

    async def test_baseline_then_only_new_reports_survive_restart_and_repeat_checks(self):
        baseline = await self.store.check(self.ref)
        self.assertEqual(baseline['new_items'], [])
        self.assertIn('Baseline', baseline['detail'])
        self.now += 7200000
        self.fetch.return_value = self.next
        update = await self.store.check(self.ref)
        self.assertEqual([i['source'] for i in update['new_items']], ['Example Wire'])
        restarted = WatchStore(self.store.path, fetch=self.fetch, clock=lambda: self.now)
        self.assertEqual((await restarted.check(self.ref))['detail'], 'No new updates.')
        self.assertEqual(len(restarted.list()[0]['items']), 3)
        self.assertNotIn('seen', restarted.list()[0])
        self.assertEqual(restarted.list()[0]['next_check'], self.now + 7200000)

    async def test_scheduler_runs_only_due_and_resumes_after_host_restart(self):
        await self.store.run_due()
        await self.store.run_due()
        self.assertEqual(self.fetch.await_count, 1)
        self.now += 7200000
        restarted = WatchStore(self.store.path, fetch=self.fetch, clock=lambda: self.now)
        await restarted.run_due()
        self.assertEqual(self.fetch.await_count, 2)

    async def test_failed_fetch_keeps_baseline_history_and_cadence(self):
        await self.store.check(self.ref)
        previous = deepcopy(self.row['items'])
        self.fetch.side_effect = ValueError('provider detail not displayed')
        failed = await self.store.check(self.ref)
        self.assertEqual(failed['status'], 'failed')
        self.assertEqual(failed['new_items'], [])
        self.assertEqual(self.row['items'], previous)
        self.assertNotIn('provider detail', json.dumps(self.store.list()))
        self.assertEqual(self.row['history'][0]['status'], 'failed')

    async def test_stop_during_fetch_cannot_publish_new_reports(self):
        await self.store.check(self.ref)
        async def fetch(topic):
            self.store.stop(self.ref)
            return self.next
        self.store.fetch = fetch
        result = await self.store.check(self.ref)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(len(self.store.list()[0]['items']), 2)

    async def test_manual_and_scheduled_checks_coalesce(self):
        gate = asyncio.Event()
        async def fetch(topic): await gate.wait(); return self.initial
        self.fetch.side_effect = fetch
        first = asyncio.create_task(self.store.check(self.ref))
        second = asyncio.create_task(self.store.check(self.ref))
        await asyncio.sleep(0)
        gate.set()
        await asyncio.gather(first, second)
        self.assertEqual(self.fetch.await_count, 1)
        self.assertEqual(len(self.row['history']), 1)

    async def test_restart_same_millisecond_rejects_the_old_fetch_generation(self):
        async def fetch(topic):
            self.store.stop(self.ref)
            self.store.create({'topic': 'City council', 'every_hours': 2})
            return self.initial
        self.store.fetch = fetch
        self.assertEqual((await self.store.check(self.ref))['status'], 'cancelled')
        self.assertFalse(self.row['baseline'])

    async def test_tool_summaries_stay_bounded_when_history_is_full(self):
        self.row['history'] = [{'detail': 'x' * 500}] * 100
        self.row['items'] = self.initial * 50
        result = await self.store.execute('list_watches', {})
        self.assertNotIn('items', result['watches'][0])
        self.assertNotIn('history', result['watches'][0])
        self.assertLess(len(json.dumps(result)), 24000)

    async def test_stop_after_and_ambiguous_targets(self):
        second = self.store.create({'topic': 'Rain reports', 'every_minutes': 15, 'stop_after': 20})
        with self.assertRaises(ValueError): self.store.stop({})
        self.now += 1200000
        self.assertFalse(self.store.list()[1]['active'])
        self.assertEqual(self.store.stop({})['id'], self.row['id'])
        self.assertIsNone(second['next_check'])

    async def test_duplicate_create_is_idempotent_and_different_schedule_is_not_silent(self):
        self.assertEqual(self.store.create({'topic': 'city council', 'every_minutes': 120})['id'], self.row['id'])
        with self.assertRaises(ValueError): self.store.create({'topic': 'City council', 'every_minutes': 15})
        self.assertEqual(len(self.store.list()), 1)

    async def test_corrupt_store_is_not_overwritten(self):
        self.store.path.write_text('{broken', encoding='utf-8')
        with self.assertRaises(ValueError): WatchStore(self.store.path)
        self.assertEqual(self.store.path.read_text(), '{broken')


class WatchRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_declarations_and_android_device_receipt_share_existing_path(self):
        session = Session(None)
        try:
            for android in (True, False):
                live = LiveConversation(session, None, android=android)
                names = {t['name'] for t in live.configuration()['setup']['tools'][0]['functionDeclarations']}
                self.assertTrue({'create_watch', 'list_watches', 'stop_watch', 'check_watch_now'} <= names)
            live = LiveConversation(session, None, android=True)
            words = "Every 2 hours, give me updates on Manchester City's 115 charges."
            live.begin_input_turn(words); live.client_input_id = 'local-turn'
            sent = []
            async def reply(kind, **event):
                sent.append((kind, event))
                live.phone.result({'request_id': event['request_id'], 'result': {'status': 'completed', 'detail': 'Watch saved and scheduled.'}})
            live.client = AsyncMock(side_effect=reply)
            result = await live.handle_tool({'id': 'watch-test', 'name': 'create_watch', 'args': {'topic': 'Manchester City 115 charges', 'every_hours': 2, 'base_revision': session.revision, 'input_token': live.input_token, 'user_request': words}})
            self.assertTrue(result['ok'])
            self.assertEqual(sent[0][0], 'device_action')
            self.assertEqual(sent[0][1]['action'], 'create_watch')
            self.assertEqual(sent[0][1]['client_input_id'], 'local-turn')
        finally: await session.close()

    async def test_browser_watch_executes_on_host_without_a_phone_or_model_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WatchStore(Path(tmp) / 'watches.json')
            session = Session(None); live = LiveConversation(session, None)
            words = 'Watch City council every two hours for one day.'
            live.begin_input_turn(words)
            try:
                with patch('thread_agent.phone.host_watches', return_value=store):
                    result = await live.handle_tool({'id': 'host-watch', 'name': 'create_watch', 'args': {'topic': 'City council', 'every_minutes': 120, 'stop_after': 1440, 'base_revision': 0, 'input_token': live.input_token, 'user_request': words}})
                self.assertTrue(result['ok'])
                self.assertEqual(len(store.list()), 1)
            finally: await session.close()

    def test_schema_and_authority_reject_changed_cadence_or_topic(self):
        for tool in watch_schemas(): Draft202012Validator.check_schema(tool['parametersJsonSchema'])
        for args in ({'every_minutes': 14}, {'every_hours': 0.1}, {'every_hours': True}, {'every_minutes': 20, 'every_hours': 2}):
            with self.subTest(args=args), self.assertRaises(ValueError): cadence(args)
        for words, args in [('Watch City council every 2 hours.', {'topic': 'City council', 'every_hours': 3}),
                            ('Watch City council every 2 hours.', {'topic': 'Other topic', 'every_hours': 2}),
                            ('My friend said watch City council every 2 hours.', {'topic': 'City council', 'every_hours': 2})]:
            with self.subTest(words=words, args=args), self.assertRaises(ValueError): authorize_watch('create_watch', args, words)


class WatchEndpointTests(unittest.TestCase):
    def test_same_origin_crud_and_check_are_persisted_and_android_cannot_double_schedule(self):
        from thread_agent.server import app
        with tempfile.TemporaryDirectory() as tmp:
            fetch = AsyncMock(return_value=parse_rss((FIXTURES / 'news.xml').read_bytes()))
            store = WatchStore(Path(tmp) / 'watches.json', fetch=fetch)
            with patch('thread_agent.server.host_watches', return_value=store), TestClient(app) as client:
                self.assertEqual(client.post('/api/watches', json={'topic': 'Test', 'every_minutes': 1}).status_code, 400)
                self.assertEqual(client.post('/api/watches', json={'topic': 'Test', 'every_minutes': 15}, headers={'Origin': 'https://example.com'}).status_code, 403)
                created = client.post('/api/watches', json={'topic': 'Test', 'every_hours': 2}).json()
                ident = created['watch']['id']
                self.assertEqual(client.post(f'/api/watches/{ident}/check').json()['new_items'], [])
                self.assertEqual(len(client.get('/api/watches').json()['watches'][0]['items']), 2)
                self.assertEqual(client.delete(f'/api/watches/{ident}').json()['status'], 'completed')
                self.assertFalse(client.get('/api/watches').json()['watches'][0]['active'])
                with patch.dict(os.environ, THREAD_EMBEDDED='android', THREAD_LOCAL_TOKEN='fixture-token'):
                    self.assertEqual(client.get('/api/watches').status_code, 401)
                    self.assertEqual(client.get('/api/watches', headers={'X-Thread-Local': 'fixture-token'}).status_code, 409)


if __name__ == '__main__': unittest.main()
