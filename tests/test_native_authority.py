"""Owned speech-interval evidence, independent of provider caption arrival order."""
import asyncio
from copy import deepcopy
import json
import unittest
from unittest.mock import AsyncMock, patch

from thread_agent.engine import Session
from thread_agent.fixtures import TRAVEL, lookup
from thread_agent.live import LiveConversation
from thread_agent.protocol import Interpretation, InputEvent


class Client:
    def __init__(self): self.packets = asyncio.Queue(); self.output = []
    async def receive(self): return await self.packets.get()
    async def send_json(self, packet): self.output.append(packet)


class NativeAuthorityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.planner = type('Planner', (), {})()
        self.planner.transcribe_pcm = AsyncMock(return_value='Book the selected flight.')
        self.s = Session(self.planner, external=True, evaluation=True, manifests={'travel': TRAVEL})
        self.s.sandbox.config.update(prepare_delay=.02, timeout=10)
        self.s.apply(Interpretation(intent='revise', domain='travel', changes=[{'slot': key, 'value': value} for key, value in {
            'origin': 'Chennai', 'destination': 'Delhi', 'date': '2026-09-15'}.items()]), InputEvent(id='setup', type='text'))
        read = next(iter(self.s.operations.values()))
        self.s.handle_result(read['id'], {'status': 'completed', **lookup('travel', read['arguments'])}, 'lookup')
        self.s.apply(Interpretation(intent='select', selection=self.s.results['items'][0]['id']), InputEvent(id='select', type='text'))
        self.client = Client()
        self.live = LiveConversation(self.s, self.client)
        self.live.send = AsyncMock()

    async def asyncTearDown(self):
        if self.live.authority_task:
            self.live.authority_task.cancel()
            await asyncio.gather(self.live.authority_task, return_exceptions=True)
        await self.s.close()

    async def audio_turn(self, pcm):
        chunks = [pcm[i:i+3200] for i in range(0, len(pcm), 3200)]
        for packet in [{'type': 'speech_start'}, *chunks, {'type': 'speech_end'}, {'type': 'end'}]:
            await self.client.packets.put({'type': 'websocket.receive', **({'bytes': packet} if isinstance(packet, bytes) else {'text': json.dumps(packet)})})
        await self.live.receive_browser()

    def call(self, ident='write', token=None):
        return {'id': ident, 'name': 'update_task', 'args': {'intent': 'commit', 'domain': 'travel', 'base_revision': self.s.revision,
            'results_id': self.s.results['id'], 'input_token': token or self.live.input_token}}

    def submitted(self):
        return [event for event in self.s.trace if event['type'] == 'tool_call' and event['effect'] == 'write']

    async def test_late_old_caption_is_never_audio_authority_even_with_current_token(self):
        self.live.begin_input_turn('Book the selected flight.')
        old_token = self.live.input_token
        self.planner.transcribe_pcm.return_value = 'Yes, that information looks correct.'
        current_pcm = b'\x02\x00'*4000
        await self.audio_turn(current_pcm)
        async def packets():
            yield json.dumps({'serverContent': {'inputTranscription': {'text': 'Book the selected flight.'}, 'interrupted': True}})
            yield json.dumps({'serverContent': {'turnComplete': True}})
        self.live.upstream = packets()
        await self.live.receive_provider()
        self.assertFalse((await self.live.handle_tool(self.call('stale-token', old_token)))['ok'])
        self.assertFalse((await self.live.handle_tool(self.call('current-token-bad-intent')))['ok'])
        await asyncio.sleep(.05)
        self.assertFalse(self.submitted())
        self.planner.transcribe_pcm.assert_awaited_once_with(current_pcm)

    async def test_positive_current_clip_can_authorize_without_a_streaming_caption(self):
        pcm = b'\x04\x00'*5000
        await self.audio_turn(pcm)
        self.assertFalse(self.live.current_user_words(verified=True))
        result = await self.live.handle_tool(self.call())
        self.assertTrue(result['ok'], result)
        await asyncio.sleep(.05)
        self.assertEqual(len(self.submitted()), 1)
        self.planner.transcribe_pcm.assert_awaited_once_with(pcm)

    async def test_typed_barge_in_survives_provider_interruption_acknowledgment(self):
        self.live.last_audio_id = 'prior-audio'
        self.live.response_started = True
        self.s.transcript.append({'id': 'prior-audio', 'role': 'assistant', 'text': 'Review this option.'})
        for data in [{'type': 'text', 'text': 'Book the selected flight.', 'client_input_id': 'typed-local'}, {'type': 'end'}]:
            await self.client.packets.put({'type': 'websocket.receive', 'text': json.dumps(data)})
        await self.live.receive_browser()
        token = self.live.input_token
        async def packets(): yield json.dumps({'serverContent': {'interrupted': True}})
        self.live.upstream = packets()
        await self.live.receive_provider()
        self.assertEqual(self.live.input_token, token)
        self.assertEqual(self.live.current_user_words(verified=True), 'Book the selected flight.')
        self.assertTrue((await self.live.handle_tool(self.call()))['ok'])
        await asyncio.sleep(.05)
        self.assertEqual(len(self.submitted()), 1)
        self.planner.transcribe_pcm.assert_not_awaited()

    async def test_unowned_provider_interruption_still_retires_old_authority(self):
        self.live.begin_input_turn('Book the selected flight.')
        token = self.live.input_token
        self.live.last_audio_id = 'prior-audio'; self.live.response_started = True
        async def packets(): yield json.dumps({'serverContent': {'interrupted': True}})
        self.live.upstream = packets()
        await self.live.receive_provider()
        self.assertNotEqual(self.live.input_token, token)
        self.assertFalse(self.live.current_user_words(verified=True))
        self.assertFalse((await self.live.handle_tool(self.call()))['ok'])
        self.assertFalse(self.submitted())

    async def test_typed_request_owns_interruption_after_late_first_audio(self):
        for data in [{'type': 'text', 'text': 'Book the selected flight.', 'client_input_id': 'typed-late-audio'}, {'type': 'end'}]:
            await self.client.packets.put({'type': 'websocket.receive', 'text': json.dumps(data)})
        await self.live.receive_browser()
        token = self.live.input_token
        async def packets():
            yield json.dumps({'serverContent': {'modelTurn': {'parts': [{'inlineData': {'data': 'AAA=', 'mimeType': 'audio/pcm;rate=24000'}}]}}})
            yield json.dumps({'serverContent': {'interrupted': True}})
        self.live.upstream = packets()
        await self.live.receive_provider()
        self.assertEqual(self.live.input_token, token)
        self.assertEqual(self.live.current_user_words(verified=True), 'Book the selected flight.')
        self.assertTrue((await self.live.handle_tool(self.call()))['ok'])
        await asyncio.sleep(.05)
        self.assertEqual(len(self.submitted()), 1)
        self.planner.transcribe_pcm.assert_not_awaited()

    async def test_typed_interruption_ownership_ends_with_provider_turn(self):
        for data in [{'type': 'text', 'text': 'Book the selected flight.'}, {'type': 'end'}]:
            await self.client.packets.put({'type': 'websocket.receive', 'text': json.dumps(data)})
        await self.live.receive_browser()
        token = self.live.input_token
        async def packets():
            yield json.dumps({'serverContent': {'turnComplete': True}})
            yield json.dumps({'serverContent': {'modelTurn': {'parts': [{'inlineData': {'data': 'AAA=', 'mimeType': 'audio/pcm;rate=24000'}}]}}})
            yield json.dumps({'serverContent': {'interrupted': True}})
        self.live.upstream = packets()
        await self.live.receive_provider()
        self.assertNotEqual(self.live.input_token, token)
        self.assertFalse(self.live.current_user_words(verified=True))
        self.assertFalse((await self.live.handle_tool(self.call()))['ok'])
        self.assertFalse(self.submitted())

    async def test_consumed_typed_barge_cannot_own_interruption_of_another_reply(self):
        for data in [{'type': 'text', 'text': 'Book the selected flight.'}, {'type': 'end'}]:
            await self.client.packets.put({'type': 'websocket.receive', 'text': json.dumps(data)})
        await self.live.receive_browser()
        token = self.live.input_token
        async def packets():
            for _ in range(2):
                yield json.dumps({'serverContent': {'modelTurn': {'parts': [{'inlineData': {'data': 'AAA=', 'mimeType': 'audio/pcm;rate=24000'}}]}}})
                yield json.dumps({'serverContent': {'interrupted': True}})
        self.live.upstream = packets()
        await self.live.receive_provider()
        self.assertNotEqual(self.live.input_token, token)
        self.assertFalse(self.live.current_user_words(verified=True))
        self.assertFalse((await self.live.handle_tool(self.call()))['ok'])
        self.assertFalse(self.submitted())

    async def test_repeated_acknowledgment_for_the_same_audio_keeps_typed_request(self):
        for data in [{'type': 'text', 'text': 'Book the selected flight.'}, {'type': 'end'}]:
            await self.client.packets.put({'type': 'websocket.receive', 'text': json.dumps(data)})
        await self.live.receive_browser()
        token = self.live.input_token
        async def packets():
            yield json.dumps({'serverContent': {'modelTurn': {'parts': [{'inlineData': {'data': 'AAA=', 'mimeType': 'audio/pcm;rate=24000'}}]}}})
            yield json.dumps({'serverContent': {'interrupted': True}})
            yield json.dumps({'serverContent': {'interrupted': True}})
        self.live.upstream = packets()
        await self.live.receive_provider()
        self.assertEqual(self.live.input_token, token)
        self.assertTrue((await self.live.handle_tool(self.call()))['ok'])
        await asyncio.sleep(.05)
        self.assertEqual(len(self.submitted()), 1)

    async def test_new_speech_rebinds_wordless_barge_to_the_current_reply(self):
        async def provider(*contents):
            async def packets():
                for content in contents: yield json.dumps({'serverContent': content})
            self.live.upstream = packets()
            await self.live.receive_provider()
        audio = {'modelTurn': {'parts': [{'inlineData': {'data': 'AAA=', 'mimeType': 'audio/pcm;rate=24000'}}]}}
        await provider(audio)
        await self.audio_turn(b'\x00\x00' * 4000)
        await provider({'interrupted': True}, {'turnComplete': True})
        self.assertIsNotNone(self.live.barge)
        await provider(audio)
        current_pcm = b'\x04\x00' * 5000
        await self.audio_turn(current_pcm)
        token = self.live.input_token
        await provider({'interrupted': True}, {'turnComplete': True})
        self.assertEqual(self.live.input_token, token)
        self.assertEqual(bytes(self.live.turn_pcm), current_pcm)
        self.assertTrue((await self.live.handle_tool(self.call()))['ok'])
        await asyncio.sleep(.05)
        self.assertEqual(len(self.submitted()), 1)
        self.planner.transcribe_pcm.assert_awaited_once_with(current_pcm)

    async def test_earlier_interval_pcm_is_not_reused_for_a_new_request(self):
        await self.audio_turn(b'\x01\x00'*4000)
        await self.audio_turn(b'\x02\x00'*4000)
        await self.live.verify_current_audio()
        self.planner.transcribe_pcm.assert_awaited_once_with(b'\x02\x00'*4000)

    async def test_new_turn_cancels_inflight_verification_without_sending_a_write(self):
        started = asyncio.Event()
        async def transcribe(pcm):
            started.set()
            await asyncio.Event().wait()
        self.planner.transcribe_pcm.side_effect = transcribe
        await self.audio_turn(b'\x03\x00'*4000)
        action = asyncio.create_task(self.live.handle_tool(self.call()))
        await started.wait()
        self.live.begin_input_turn('Stop.')
        result = await asyncio.wait_for(action, .5)
        self.assertFalse(result['ok'])
        self.assertFalse(self.submitted())

    async def test_typed_command_is_direct_authority_and_does_not_call_audio_model(self):
        self.live.begin_input_turn('Book the selected flight.')
        result = await self.live.handle_tool(self.call())
        self.assertTrue(result['ok'], result)
        self.planner.transcribe_pcm.assert_not_called()

    async def test_wrong_result_reference_can_be_repaired_without_new_permission(self):
        self.live.begin_input_turn('Book the selected flight.')
        wrong = self.call('wrong-result-reference')
        wrong['args']['results_id'] = self.s.selection['id']
        refused = await self.live.handle_tool(wrong)
        self.assertFalse(refused['ok'])
        self.assertIn('Wrong results_id', refused['error'])
        self.assertEqual(refused['state']['results_id'], self.s.results['id'])
        self.assertIsNone(self.live.action_token_used)
        self.assertFalse(self.submitted())
        repaired = self.call('repaired-result-reference')
        repaired['args']['results_id'] = refused['state']['results_id']
        self.assertTrue((await self.live.handle_tool(repaired))['ok'])
        await asyncio.sleep(.05)
        self.assertEqual(len(self.submitted()), 1)

    async def test_repairing_result_reference_does_not_authorize_acknowledgment(self):
        self.live.begin_input_turn('Yes, that information looks correct.')
        wrong = self.call('ack-wrong-result')
        wrong['args']['results_id'] = self.s.selection['id']
        refused = await self.live.handle_tool(wrong)
        repaired = self.call('ack-repaired-result')
        repaired['args']['results_id'] = refused['state']['results_id']
        self.assertFalse((await self.live.handle_tool(repaired))['ok'])
        await asyncio.sleep(.05)
        self.assertFalse(self.submitted())

    async def test_new_local_speech_retires_prepared_authority_before_any_caption_arrives(self):
        self.s.sandbox.config['prepare_delay'] = .06
        self.live.begin_input_turn('Book the selected flight.')
        self.assertTrue((await self.live.handle_tool(self.call('earlier-write')))['ok'])
        prepared = next(op for op in self.s.operations.values() if op['purpose'] == 'create')
        self.assertEqual(prepared['status'], 'prepared')
        await self.audio_turn(b'\x03\x00'*5000)
        self.assertEqual(prepared['status'], 'not_submitted')
        await self.live.caption('user', 'Book the selected flight.')
        async def packets():
            yield json.dumps({'serverContent': {'turnComplete': True}})
        self.live.upstream = packets()
        await self.live.receive_provider()
        await asyncio.sleep(.08)
        self.assertFalse(self.submitted())

    async def test_fresh_explicit_request_after_retirement_can_submit_exactly_once(self):
        self.s.sandbox.config['prepare_delay'] = .06
        self.live.begin_input_turn('Book the selected flight.')
        self.assertTrue((await self.live.handle_tool(self.call('earlier-write')))['ok'])
        await self.audio_turn(b'\x03\x00'*5000)
        self.assertTrue((await self.live.handle_tool(self.call('fresh-write')))['ok'])
        await asyncio.sleep(.09)
        self.assertEqual(len(self.submitted()), 1)

    async def test_cancellation_swallowing_transcriber_cannot_restore_old_authority(self):
        started = asyncio.Event()
        async def transcribe(pcm):
            started.set()
            try: await asyncio.Event().wait()
            except asyncio.CancelledError: return 'Book the selected flight.'
        self.planner.transcribe_pcm.side_effect = transcribe
        await self.audio_turn(b'\x03\x00'*4000)
        action = asyncio.create_task(self.live.handle_tool(self.call()))
        await started.wait()
        self.live.begin_input_turn('Stop.')
        self.assertFalse((await asyncio.wait_for(action, .5))['ok'])
        self.assertFalse(self.submitted())

    async def test_missing_or_overlong_audio_does_not_fall_back_to_provider_caption(self):
        await self.audio_turn(b'\x01\x00'*400)
        await self.live.caption('user', 'Book the selected flight.')
        self.assertFalse((await self.live.handle_tool(self.call()))['ok'])
        self.live.audio_overflow = True
        self.assertFalse((await self.live.handle_tool(self.call('overflow')))['ok'])
        self.assertFalse(self.submitted())
        self.planner.transcribe_pcm.assert_not_called()

    async def test_one_spoken_additional_action_is_not_two_grants(self):
        self.live.begin_input_turn('Book the selected flight.')
        self.assertTrue((await self.live.handle_tool(self.call('first')))['ok'])
        await asyncio.sleep(.04)
        before = len(self.submitted())
        self.planner.transcribe_pcm.return_value = 'Book another separate flight.'
        await self.audio_turn(b'\x02\x00'*4000)
        call = self.call('additional'); call['args']['intent'] = 'additional_action'
        self.assertTrue((await self.live.handle_tool(call))['ok'])
        call = deepcopy(call); call['id'] = 'provider-retry'
        self.assertFalse((await self.live.handle_tool(call))['ok'])
        await asyncio.sleep(.04)
        self.assertEqual(len(self.submitted())-before, 1)

    async def test_selection_change_cannot_reuse_permission_for_retired_preparation(self):
        self.s.sandbox.config['prepare_delay'] = .1
        await self.audio_turn(b'\x02\x00'*4000)
        self.assertTrue((await self.live.handle_tool(self.call('prepare-a')))['ok'])
        await self.s.control({'action':'select','option_id':self.s.results['items'][1]['id'],'results_id':self.s.results['id']})
        self.assertFalse((await self.live.handle_tool(self.call('reuse-for-b')))['ok'])
        await asyncio.sleep(.13)
        self.assertFalse(self.submitted())

    async def test_action_call_cannot_add_unreviewed_soft_fields(self):
        self.live.begin_input_turn('Book the selected flight.')
        call = self.call('invented-detail')
        call['args']['changes'] = [{'slot':'seat','value':'aisle'}]
        self.assertFalse((await self.live.handle_tool(call))['ok'])
        self.assertNotIn('seat', self.s.slots)
        self.assertFalse(self.submitted())

    async def test_provider_withdrawal_while_asr_runs_prevents_dispatch(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def transcribe(pcm):
            started.set(); await release.wait(); return 'Book the selected flight.'
        self.planner.transcribe_pcm.side_effect = transcribe
        await self.audio_turn(b'\x02\x00'*4000)
        call = self.call('withdraw-during-asr')
        async def packets():
            yield json.dumps({'toolCall':{'functionCalls':[call]}})
            await started.wait()
            yield json.dumps({'toolCallCancellation':{'ids':[call['id']]}})
            release.set()
        self.live.upstream = packets()
        await self.live.receive_provider()
        await asyncio.gather(*list(self.live.tool_tasks.values()))
        await asyncio.sleep(.04)
        self.assertFalse(self.submitted())

    async def test_pause_then_resume_cannot_restore_the_same_inflight_audio_grant(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def transcribe(pcm):
            started.set(); await release.wait(); return 'Book the selected flight.'
        self.planner.transcribe_pcm.side_effect = transcribe
        await self.audio_turn(b'\x02\x00'*4000)
        task = asyncio.create_task(self.live.handle_tool(self.call('pause-during-asr')))
        await started.wait()
        await self.s.accept(InputEvent(id='pause',type='control',data={'action':'pause'}))
        await self.s.accept(InputEvent(id='resume',type='control',data={'action':'resume'}))
        self.assertFalse(self.s.paused)
        release.set()
        self.assertFalse((await asyncio.wait_for(task,.5))['ok'])
        await asyncio.sleep(.04)
        self.assertFalse(self.submitted())

    async def test_provider_withdrawal_after_preparation_prevents_submission(self):
        self.s.sandbox.config['prepare_delay'] = .08
        self.live.begin_input_turn('Book the selected flight.')
        call = self.call('withdraw-prepared')
        self.assertTrue((await self.live.handle_tool(call))['ok'])
        async def packets():
            yield json.dumps({'toolCallCancellation':{'ids':[call['id']]}})
        self.live.upstream = packets()
        await self.live.receive_provider()
        await asyncio.sleep(.1)
        self.assertFalse(self.submitted())

    async def test_disconnect_closes_effect_boundary_before_cancelling_asr(self):
        self.live = LiveConversation(self.s, self.client, android=True)
        self.live.send = AsyncMock()
        started = asyncio.Event()
        async def transcribe(pcm):
            started.set()
            try: await asyncio.Event().wait()
            except asyncio.CancelledError: return 'Set an alarm for 7 PM.'
        self.planner.transcribe_pcm.side_effect = transcribe
        await self.audio_turn(b'\x02\x00'*4000)
        call = {'id':'closing-alarm','name':'phone_set_alarm','args':{'hour':19,'minute':0,'label':'Evening',
            'base_revision':self.s.revision,'input_token':self.live.input_token,'user_request':'Set an alarm for 7 PM.'}}
        class Provider:
            async def __aenter__(self): return self
            async def __aexit__(self,*_): return False
            async def recv(self): return json.dumps({'setupComplete':{}})
            def __aiter__(self): return self.packets()
            async def packets(self):
                yield json.dumps({'toolCall':{'functionCalls':[call]}})
                await started.wait()
        with patch('thread_agent.live.websockets.connect',return_value=Provider()), patch('thread_agent.live.settings',return_value={'key':'offline-test','live_model':'mock','live_search':False}), patch.object(self.live,'configuration',return_value={}):
            await asyncio.wait_for(self.live.run(),1)
        self.assertTrue(self.live.closing)
        self.assertFalse(any(event['type']=='device_action' for event in self.client.output))
        self.assertFalse(self.live.turn_pcm)
        self.assertFalse(self.live.pre_speech_pcm)

    async def test_device_send_waiting_for_socket_lock_rechecks_new_input(self):
        self.live = LiveConversation(self.s, self.client, android=True)
        self.live.begin_input_turn('Set an alarm for 7 PM.')
        call = {'id':'queued-alarm','name':'phone_set_alarm','args':{'hour':19,'minute':0,'label':'Evening',
            'base_revision':self.s.revision,'input_token':self.live.input_token,'user_request':'Set an alarm for 7 PM.'}}
        await self.live.browser_lock.acquire()
        task = asyncio.create_task(self.live.handle_tool(call))
        await asyncio.sleep(.01)
        self.live.begin_input_turn('Never mind.')
        self.live.browser_lock.release()
        self.assertFalse((await asyncio.wait_for(task,.5))['ok'])
        self.assertFalse(any(event['type']=='device_action' for event in self.client.output))
        self.assertFalse(self.live.phone.pending)

    async def test_device_send_lock_respects_shared_pause_and_session_close(self):
        for stop in ('pause', 'close'):
            with self.subTest(stop=stop):
                self.live = LiveConversation(self.s, self.client, android=True)
                self.live.begin_input_turn('Set an alarm for 7 PM.')
                call = {'id':'locked-'+stop,'name':'phone_set_alarm','args':{'hour':19,'minute':0,'label':'Evening',
                    'base_revision':self.s.revision,'input_token':self.live.input_token,'user_request':'Set an alarm for 7 PM.'}}
                await self.live.browser_lock.acquire()
                task = asyncio.create_task(self.live.handle_tool(call))
                await asyncio.sleep(.01)
                if stop == 'pause': await self.s.control({'action':'pause'})
                else: await self.s.close()
                self.live.browser_lock.release()
                self.assertFalse((await asyncio.wait_for(task,.5))['ok'])
                self.assertFalse(any(event['type']=='device_action' for event in self.client.output))
                self.assertFalse(self.live.phone.pending)
                if stop == 'pause': await self.s.control({'action':'resume'})


if __name__ == '__main__': unittest.main()
