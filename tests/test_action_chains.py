import asyncio
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from jsonschema import Draft202012Validator

from thread_agent.engine import Session
from thread_agent.live import LiveConversation
from thread_agent.phone import phone_schemas
from thread_agent.watches import parse_rss


class ActionChainTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.session = Session(None)
        self.live = LiveConversation(self.session, None, android=True)
        self.sent = []
        self.reply_status = 'handed_off'
        async def reply(kind, **event):
            self.sent.append(event)
            self.live.phone.result({'request_id': event['request_id'], 'result': {'status': self.reply_status, 'detail': 'Draft handed off. You send it.'}})
        self.live.client = AsyncMock(side_effect=reply)
        self.news = parse_rss((Path(__file__).parent / 'fixtures/watches/news-next.xml').read_bytes())

    async def asyncTearDown(self): await self.session.close()

    async def request(self, words, action, args):
        self.live.begin_input_turn(words); self.live.client_input_id = f'local-{self.live.input_epoch}'
        return await self.live.handle_tool({'id': f'call-{self.live.input_epoch}', 'name': 'phone_' + action,
            'args': {**args, 'user_request': words, 'base_revision': self.session.revision, 'input_token': self.live.input_token}})

    def news_chain(self):
        # Deliberately fictional recipient; all native effects are mocked.
        read = 'Find the latest on City council'
        draft = 'send it to +12025550123 on WhatsApp'
        return read + ' and ' + draft, {'steps': [
            {'action': 'latest_news', 'arguments': {'topic': 'City council'}, 'user_request': read},
            {'action': 'compose_whatsapp', 'arguments': {'number': '+12025550123', 'use_latest_news': True}, 'user_request': draft}]}

    async def test_youtube_compound_is_one_encoded_search_not_just_an_app_launch(self):
        words = 'Open YouTube and search for Manchester City 115 charges.'
        result = await self.request(words, 'media_search', {'provider': 'youtube', 'query': 'Manchester City 115 charges'})
        self.assertEqual(result['status'], 'handed_off')
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]['action'], 'media_search')
        self.assertEqual(self.sent[0]['arguments']['query'], 'Manchester City 115 charges')
        self.assertEqual(self.sent[0]['client_input_id'], 'local-1')
        self.assertFalse((await self.request(words, 'open_app', {'query': 'YouTube'}))['ok'])
        self.assertFalse((await self.request(words, 'media_search', {'provider': 'youtube', 'query': 'unrequested news'}))['ok'])
        self.assertEqual(len(self.sent), 1)

    async def test_actual_live_socket_checks_parent_chain_withdrawal_under_send_lock(self):
        self.live.browser = SimpleNamespace(send_json=AsyncMock())
        self.live.client = LiveConversation.client.__get__(self.live)
        await self.live.browser_lock.acquire()
        args = {'steps': [{'action': 'set_volume', 'user_request': 'Set media volume to 30 percent', 'arguments': {'percent': 30}},
                          {'action': 'open_app', 'user_request': 'open YouTube', 'arguments': {'query': 'YouTube'}}]}
        task = asyncio.create_task(self.request('Set media volume to 30 percent and then open YouTube', 'run_chain', args))
        await asyncio.sleep(0)
        self.live.withdrawn_calls.add('call-1')
        self.live.browser_lock.release()
        result = await task
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual([step['status'] for step in result['steps']], ['cancelled', 'not_submitted'])
        self.live.browser.send_json.assert_not_awaited()

    async def test_news_draft_contains_exact_returned_headline_source_link_and_per_step_receipts(self):
        words, args = self.news_chain()
        with patch('thread_agent.phone.fetch_news', AsyncMock(return_value=self.news)):
            result = await self.request(words, 'run_chain', args)
        self.assertEqual(result['status'], 'handed_off')
        self.assertEqual([s['status'] for s in result['steps']], ['completed', 'handed_off'])
        self.assertEqual(self.sent[0]['action'], 'compose_whatsapp')
        first = self.news[0]
        self.assertEqual(self.sent[0]['arguments'], {'number': '12025550123', 'body': f"{first['title']}\n{first['source']}\n{first['link']}"})
        self.assertTrue(any(e['type'] == 'smart_action_progress' for e in self.session.trace))

    async def test_new_input_or_stop_while_reading_prevents_draft_and_preserves_read_receipt(self):
        for interrupt in ('new-input', 'stop', 'withdraw'):
            with self.subTest(interrupt=interrupt):
                words, args = self.news_chain()
                async def fetch(topic):
                    if interrupt == 'new-input': self.live.begin_input_turn('Actually, use a different topic.')
                    elif interrupt == 'stop': self.session.interrupt_epoch += 1
                    else: self.live.withdrawn_calls.add(f'call-{self.live.input_epoch}')
                    return self.news
                with patch('thread_agent.phone.fetch_news', fetch): result = await self.request(words, 'run_chain', args)
                self.assertEqual(result['status'], 'partial')
                self.assertEqual([s['status'] for s in result['steps']], ['completed', 'cancelled'])
                self.assertFalse(self.sent)

    async def test_failed_read_and_unconfirmed_handoff_never_become_sent(self):
        words, args = self.news_chain()
        with patch('thread_agent.phone.fetch_news', AsyncMock(return_value=[])):
            result = await self.request(words, 'run_chain', args)
        self.assertEqual([s['status'] for s in result['steps']], ['failed', 'not_submitted'])
        self.assertFalse(self.sent)
        self.reply_status = 'unknown'
        with patch('thread_agent.phone.fetch_news', AsyncMock(return_value=self.news)):
            result = await self.request(words, 'run_chain', args)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['steps'][1]['status'], 'unknown')
        self.assertEqual(len(self.sent), 1)

    async def test_redelivery_never_repeats_a_chain(self):
        words, args = self.news_chain()
        with patch('thread_agent.phone.fetch_news', AsyncMock(return_value=self.news)) as fetch:
            result = await self.request(words, 'run_chain', args)
            repeated = await self.live.handle_tool({'id': 'call-1', 'name': 'phone_run_chain', 'args': {}})
        self.assertEqual(repeated, result)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(fetch.await_count, 1)

    async def test_whole_plan_is_validated_before_first_step(self):
        words, args = self.news_chain()
        invalids = []
        bad = deepcopy(args); bad['steps'][1]['arguments']['number'] = '+12025550199'; invalids.append(bad)
        bad = deepcopy(args); bad['steps'][1]['arguments']['body'] = 'invented news'; invalids.append(bad)
        bad = deepcopy(args); bad['steps'][0]['arguments']['topic'] = 'invented topic'; invalids.append(bad)
        bad = deepcopy(args); bad['steps'][1]['action'] = 'dial'; invalids.append(bad)
        with patch('thread_agent.phone.fetch_news', AsyncMock(return_value=self.news)) as fetch:
            for bad in invalids:
                with self.subTest(bad=bad): self.assertFalse((await self.request(words, 'run_chain', bad))['ok'])
            self.assertFalse((await self.request('My friend said ' + words, 'run_chain', args))['ok'])
            self.assertFalse((await self.request(words + ', but do not do it yet.', 'run_chain', args))['ok'])
        self.assertEqual(fetch.await_count, 0)
        self.assertFalse(self.sent)

    async def test_volume_then_open_app_keeps_two_honest_receipts(self):
        args = {'steps': [{'action': 'set_volume', 'user_request': 'Set media volume to 30 percent', 'arguments': {'percent': 30}},
                          {'action': 'open_app', 'user_request': 'open YouTube', 'arguments': {'query': 'YouTube'}}]}
        result = await self.request('Set media volume to 30 percent and then open YouTube', 'run_chain', args)
        self.assertEqual(len(result['steps']), 2)
        self.assertEqual([event['action'] for event in self.sent], ['set_volume', 'open_app'])

    async def test_connection_loss_keeps_confirmed_steps_and_marks_inflight_effect_unknown(self):
        pending = asyncio.Event()
        async def reply(kind, **event):
            if event['action'] == 'set_volume':
                self.live.phone.result({'request_id': event['request_id'], 'result': {'status': 'completed', 'detail': 'Media volume read back at 30 percent.'}})
            else:
                pending.set()
                await asyncio.Event().wait()
        self.live.client.side_effect = reply
        args = {'steps': [{'action': 'set_volume', 'user_request': 'Set media volume to 30 percent', 'arguments': {'percent': 30}},
                          {'action': 'open_app', 'user_request': 'open YouTube', 'arguments': {'query': 'YouTube'}}]}
        task = asyncio.create_task(self.request('Set media volume to 30 percent and then open YouTube', 'run_chain', args))
        await asyncio.wait_for(pending.wait(), 1)
        self.live.closing = True
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        card = self.session.workspace['phone:phone-call-1']['items'][0]
        self.assertEqual(card['status'], 'partial')
        self.assertEqual([step['status'] for step in card['steps']], ['completed', 'unknown'])

    async def test_new_actions_have_closed_schemas_and_bound_destinations(self):
        for tool in phone_schemas(): Draft202012Validator.check_schema(tool['parametersJsonSchema'])
        samples = [
            ('Open https://example.com/story in Chrome', 'open_url', {'url': 'https://example.com/story'}),
            ('Search Play Store for Signal', 'play_store_search', {'query': 'Signal'}),
            ('Show walking directions to Central Station', 'directions', {'destination': 'Central Station', 'travel_mode': 'walking'}),
            ('Share meeting at five to WhatsApp', 'share_text', {'body': 'meeting at five', 'app': 'WhatsApp'}),
            ('Open the camera', 'open_camera', {}),
            ('Draft a WhatsApp message to +12025550123 saying meeting at five', 'compose_whatsapp', {'number': '+12025550123', 'body': 'meeting at five'}),
        ]
        for words, action, args in samples:
            with self.subTest(action=action): self.assertTrue((await self.request(words, action, args))['ok'])
        self.assertFalse((await self.request('Open https://example.com/story in Chrome', 'open_url', {'url': 'javascript:alert(1)'}))['ok'])
        self.assertFalse((await self.request('Show walking directions to Central Station', 'directions', {'destination': 'Central Station', 'travel_mode': 'driving'}))['ok'])


if __name__ == '__main__': unittest.main()
