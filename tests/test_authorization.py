"""Adversarial model proposals must not become user authorization."""
import asyncio
import base64
from copy import deepcopy
import json
import io
import unittest
import wave
from unittest.mock import AsyncMock

from thread_agent.authorization import explicit_write_request
from thread_agent.engine import Session
from thread_agent.fixtures import TRAVEL, lookup
from thread_agent.live import LiveConversation
from thread_agent.protocol import InputEvent, Interpretation, Manifest
from thread_agent.adapter import parse_event
from thread_agent.planner import ModelPlanner


class ProposingPlanner:
    def __init__(self): self.plan = Interpretation(intent='acknowledge')
    async def interpret(self, *_): return deepcopy(self.plan)


class Client:
    async def send_json(self, value): pass


class AuthorityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.planner = ProposingPlanner()
        self.s = Session(self.planner, external=True, evaluation=True, manifests={'travel': TRAVEL})
        self.s.sandbox.config.update(prepare_delay=.005, timeout=10)
        self.s.apply(Interpretation(intent='revise', domain='travel', changes=[
            {'slot': k, 'value': v} for k, v in {'origin': 'Chennai', 'destination': 'Delhi', 'date': '2026-09-15'}.items()]), InputEvent(id='setup', type='text'))
        self.complete_lookup()
        self.s.apply(Interpretation(intent='select', selection=self.s.results['items'][0]['id']), InputEvent(id='select', type='text'))

    async def asyncTearDown(self): await self.s.close()

    def complete_lookup(self):
        op = next(o for o in reversed(list(self.s.operations.values())) if o['purpose'] == 'lookup')
        self.s.handle_result(op['id'], {'status': 'completed', **lookup('travel', op['arguments'])}, self.s.new_id('result'))

    async def input(self, words, intent='commit', **fields):
        self.planner.plan = Interpretation(intent=intent, **fields)
        await self.s.accept(InputEvent(id=self.s.new_id('input'), type='text', text=words))
        await self.s.inputs.join()
        await asyncio.sleep(.015)

    def writes(self, purpose=None):
        return [o for o in self.s.operations.values() if o['effect'] == 'write' and (purpose is None or o['purpose'] == purpose)]

    async def confirmed(self):
        await self.input('Book that flight.')
        op = self.writes('create')[-1]
        self.s.handle_result(op['id'], {'status': 'completed', 'reference': 'KNOWN-1'}, self.s.new_id('result'))
        return op

    async def test_wrong_object_conditional_quote_and_acknowledgment_create_no_effect(self):
        for words in ['Create a note.', 'Create a summary.', 'Book it if it is refundable.', 'He said "Book that flight".', 'Yes, that information looks correct.', 'Book the room.']:
            with self.subTest(words=words):
                await self.input(words)
                self.assertFalse(self.writes())

    async def test_audio_model_acknowledgment_cannot_become_a_booking(self):
        self.planner.plan = Interpretation(intent='commit', transcript='Yes, that information looks correct.')
        await self.s.accept(InputEvent(id='ack-audio', type='audio', data={'mime': 'audio/wav', 'base64': 'stub'}))
        await self.s.inputs.join()
        await asyncio.sleep(.015)
        self.assertFalse(self.writes())

    async def test_refused_complex_command_preserves_count_and_invalidates_old_option(self):
        await self.input('Please book this flight for two passengers.', changes=[{'slot': 'passengers', 'value': '2'}])
        self.assertEqual(self.s.slots['passengers'], 2)
        self.assertIsNone(self.s.results)
        self.assertIsNone(self.s.selection)
        self.assertFalse(self.writes())
        await self.input('Please book the selected flight.')
        self.assertFalse(self.writes())  # Fresh options must be reviewed first.
        self.complete_lookup()
        self.s.apply(Interpretation(intent='select', selection=self.s.results['items'][0]['id']), InputEvent(id='new-selection', type='text'))
        await self.input('Please book the selected flight.')
        self.assertEqual(self.writes('create')[0]['arguments']['passengers'], 2)

    async def test_cancel_search_and_invented_cancel_do_not_undo_confirmed_booking(self):
        op = await self.confirmed()
        await self.input('Cancel the search.', intent='cancel')
        self.assertFalse(self.writes('cancel'))
        self.assertEqual(op['confirmed_reference'], 'KNOWN-1')
        await self.input('Yes, that information looks correct.', intent='cancel')
        self.assertFalse(self.writes('cancel'))
        await self.input('Cancel that booking.', intent='cancel')
        self.assertEqual(len(self.writes('cancel')), 1)

    async def test_multiple_confirmed_actions_require_a_target_for_cancellation(self):
        await self.confirmed()
        await self.input('Book another separate flight.', intent='additional_action')
        second = self.writes('create')[-1]
        self.s.handle_result(second['id'], {'status': 'completed', 'reference': 'KNOWN-2'}, self.s.new_id('result'))
        self.assertEqual(len(self.writes('create')), 2)
        await self.input('Cancel that booking.', intent='cancel')
        self.assertFalse(self.writes('cancel'))
        await self.input('Cancel that booking.', intent='cancel', action_id=second['id'])
        self.assertEqual(len(self.writes('cancel')), 1)
        self.assertEqual(self.writes('cancel')[0]['arguments']['operation_id'], second['id'])

    async def test_live_old_interrupted_packet_cannot_reuse_prior_booking_words(self):
        live = LiveConversation(self.s, Client())
        live.input_epoch = 1
        await live.caption('user', 'Book that flight.')
        live.input_epoch += 1
        live.block_old_calls = True
        self.s.yield_floor()
        async def packets():
            yield json.dumps({'serverContent': {'interrupted': True}})
            yield json.dumps({'serverContent': {'turnComplete': True}})
        live.upstream = packets()
        await live.receive_provider()
        result = live.apply_tool({'id': 'stale-commit', 'name': 'update_task', 'args': {
            'intent': 'commit', 'base_revision': self.s.revision, 'results_id': self.s.results['id']}})
        self.assertFalse(result['ok'])
        self.assertTrue(self.s.floor_held)
        self.assertFalse(self.writes())

    async def test_live_refusal_keeps_current_correction(self):
        live = LiveConversation(self.s, Client())
        live.begin_input_turn('Please book this flight for two passengers.')
        await live.caption('user', 'Please book this flight for two passengers.')
        result = live.apply_tool({'id': 'complex', 'name': 'update_task', 'args': {
            'intent': 'commit', 'input_token': live.input_token, 'base_revision': self.s.revision, 'results_id': self.s.results['id'],
            'changes': [{'slot': 'passengers', 'value': '2'}]}})
        self.assertFalse(result['ok'])
        self.assertEqual(self.s.slots['passengers'], 2)
        self.assertIsNone(self.s.selection)
        self.assertFalse(self.writes())

    async def test_digital_silence_never_reaches_a_provider_or_mutates_state(self):
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000); wav.writeframes(b'\0'*32000)
        event = parse_event({'id': 'silence', 'type': 'audio', 'data': {'mime': 'audio/wav', 'base64': base64.b64encode(buf.getvalue()).decode()}})
        planner = ModelPlanner()
        planner.generate = AsyncMock(side_effect=AssertionError('Silent audio should not call the provider'))
        try:
            result = await planner.interpret(self.s.context(), event)
            self.assertEqual(result.intent, 'clarify')
            self.assertFalse(result.changes)
            planner.generate.assert_not_called()
        finally:
            await planner.close()

    async def test_truncated_wav_is_rejected_at_the_transport_boundary(self):
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000); wav.writeframes(b'\0'*32000)
        with self.assertRaises(ValueError):
            parse_event({'id': 'bad-wave', 'type': 'audio', 'data': {'mime': 'audio/wav', 'base64': base64.b64encode(buf.getvalue()[:-100]).decode()}})


class ManifestAuthorityTests(unittest.TestCase):
    def test_acknowledgment_cannot_be_declared_as_a_write_verb(self):
        for verb in ['yes', 'okay', 'correct', 'agree', 'go ahead', 'please']:
            with self.subTest(verb=verb):
                raw = TRAVEL.model_dump()
                next(t for t in raw['tools'] if t['purpose'] == 'create')['authorization_verbs'] = [verb]
                with self.assertRaises(ValueError): Manifest.model_validate(raw).check()

    def test_unknown_tool_has_a_scoped_canonical_command(self):
        tool = TRAVEL.tool('create').model_copy(update={'name': 'x37.materialize', 'authorization_objects': []})
        self.assertTrue(explicit_write_request('Submit the selected action.', tool))
        self.assertFalse(explicit_write_request('Create a note.', tool))

    def test_second_option_is_not_authority_for_an_additional_effect(self):
        self.assertFalse(explicit_write_request('Book the second flight.', TRAVEL.tool('create'), additional=True))
        self.assertTrue(explicit_write_request('Book another separate flight.', TRAVEL.tool('create'), additional=True))


if __name__ == '__main__': unittest.main()
