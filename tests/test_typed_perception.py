"""Typed unfamiliar slots and direct observation answers through the controller."""
import unittest
from unittest.mock import AsyncMock, patch

from thread_agent.engine import Session
from thread_agent.fixtures import DEVICE, TRAVEL
from thread_agent.planner import ModelPlanner
from thread_agent.protocol import Manifest, InputEvent, Interpretation
from thread_agent.adapter import parse_event


class TypedPerceptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_price_comparison_answers_from_two_actual_same_currency_results(self):
        from thread_agent.fixtures import lookup
        session = Session(None, external=True, evaluation=True, manifests={'travel':TRAVEL})
        try:
            session.apply(Interpretation(intent='revise',domain='travel',changes=[{'slot':k,'value':v} for k,v in {
                'origin':'Chennai','destination':'Delhi','date':'2026-09-15'}.items()]),InputEvent(id='setup',type='text'))
            read = next(iter(session.operations.values()))
            session.handle_result(read['id'],{'status':'completed',**lookup('travel',read['arguments'])},'base')
            baseline_id = session.results['id']
            session.apply(Interpretation(intent='compare',domain='travel',changes=[{'slot':'destination','value':'Pune'}]),InputEvent(id='compare',type='text',text='Would Pune be cheaper?'))
            comparison = next(op for op in session.operations.values() if op.get('comparison'))
            result = {'status':'completed',**lookup('travel',comparison['arguments'])}
            for item in result['items']: item['price'] -= 500
            session.handle_result(comparison['id'],result,'alternative')
            self.assertEqual(session.slots['destination'],'Delhi')
            evidence = session.workspace['comparison:travel']['price_comparison']
            self.assertEqual(evidence['baseline_result_id'],baseline_id)
            self.assertEqual(evidence['difference'],-500)
            self.assertIn('500 INR lower',next(e['text'] for e in reversed(session.trace) if e['type']=='final'))
            self.assertTrue(session.summary()['comparison_evidence'])
        finally: await session.close()

    async def test_resolution_fault_is_reported_without_killing_the_next_input(self):
        from thread_agent.engine import Unresolvable
        planner = type('Planner', (), {'interpret': AsyncMock(side_effect=[Unresolvable('#/missing'), Interpretation(intent='status')])})()
        session = Session(planner,external=True,evaluation=True,manifests={'travel':TRAVEL})
        try:
            for ident in ('first-fault','next-valid'):
                await session.accept(InputEvent(id=ident,type='text',text='What is the current status?'))
                await session.inputs.join()
            self.assertEqual(session.pending_inputs, 0)
            self.assertTrue(any(e['type']=='input_error' for e in session.trace))
            self.assertTrue(any(e['type']=='intent_interpreted' and e['input_id']=='next-valid' for e in session.trace))
        finally: await session.close()

    async def test_local_schema_references_are_rejected_before_registration(self):
        for keyword in ('$ref', '$dynamicRef', '$recursiveRef'):
            manifest = TRAVEL.model_dump()
            manifest['slots']['$defs'] = {'place': {'type': 'string'}}
            manifest['slots']['properties']['origin'] = {keyword: '#/$defs/place'}
            with self.assertRaisesRegex(ValueError, 'inline schemas'):
                parse_event({'id':'unsupported-reference','type':'manifest','data':{'manifest':manifest}})

    async def test_audio_is_transcribed_without_context_before_typed_interpretation(self):
        planner = ModelPlanner()
        words = 'Keep the source depot. Use East Gate as the destination.'
        planner.transcribe_audio = AsyncMock(return_value=words)
        planner.generate = AsyncMock(return_value={'intent':'revise','domain':'travel','changes':[{'slot':'destination','value':'East Gate'}]})
        import base64, io, wave
        audio = io.BytesIO()
        with wave.open(audio,'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000); wav.writeframes(b'\x01\x00'*4000)
        event = InputEvent(id='audio-separation',type='audio',data={'mime':'audio/wav','base64':base64.b64encode(audio.getvalue()).decode()})
        session = Session(planner,external=True,evaluation=True,manifests={'travel':TRAVEL})
        try:
            result = await planner.interpret(session.context(),event)
            self.assertEqual(result.transcript, words)
            parts = planner.generate.await_args.args[0]
            self.assertTrue(all('inlineData' not in part for part in parts))
            self.assertIn(words, parts[0]['text'])
        finally: await session.close(); await planner.close()

    async def test_native_nested_slot_value_reaches_an_unfamiliar_read_unchanged(self):
        slot = {'type': 'object', 'properties': {'low': {'type': 'number'}, 'high': {'type': 'number'},
            'labels': {'type': 'array', 'items': {'type': 'string'}}}, 'required': ['low', 'high', 'labels'], 'additionalProperties': False}
        schema = {'type': 'object', 'properties': {'humidity_window': slot}, 'required': ['humidity_window'], 'additionalProperties': False}
        manifest = Manifest(id='greenhouse', title='Greenhouse environments', description='Query declared environmental ranges.', slots=schema,
            tools=[{'name': 'gh.inspect', 'description': 'Find a matching controlled greenhouse environment.', 'purpose': 'lookup', 'effect': 'read', 'parameters': schema}]).check()
        value = {'low': 20.5, 'high': 35, 'labels': ['covered', 'airflow']}
        planner = ModelPlanner()
        planner.generate = AsyncMock(return_value={'intent': 'revise', 'domain': 'greenhouse', 'changes': [{'slot': 'humidity_window', 'value': value}]})
        session = Session(planner, external=True, evaluation=True, manifests={'greenhouse': manifest})
        try:
            await session.accept(InputEvent(id='typed-object', type='text', text='Find an environment with humidity 20.5 to 35 and covered, airflow labels.'))
            await session.inputs.join()
            operation = next(iter(session.operations.values()))
            self.assertEqual(operation['arguments']['humidity_window'], value)
            output_schema = planner.generate.await_args.args[1]
            variant = output_schema['properties']['changes']['items']['anyOf'][0]
            self.assertEqual(variant['properties']['value'], slot)
        finally:
            await session.close(); await planner.close()

    async def test_label_only_answer_does_not_require_a_manual_target(self):
        session = Session(None, external=True, evaluation=True, manifests={'device': DEVICE})
        try:
            session.media = {'id': 'current-image', 'mime': 'image/png'}
            session.apply(Interpretation(intent='observe', domain='device', observation='The visible label reads ALTO 52.',
                changes=[{'slot': 'model', 'value': 'ALTO 52', 'source': 'frame'}]), InputEvent(id='image-question', type='frame'))
            self.assertFalse(session.operations)
            answer = next(e for e in reversed(session.trace) if e['type'] == 'final')
            self.assertEqual(answer['text'], 'The visible label reads ALTO 52.')
            self.assertEqual(answer['state_snapshot']['perception']['media_id'], 'current-image')
        finally: await session.close()

    async def test_unrequested_speech_mute_is_rejected_without_losing_the_task(self):
        planner = type('Planner', (), {'interpret': AsyncMock(return_value=Interpretation(intent='speech_only'))})()
        session = Session(planner, external=True, evaluation=True, manifests={'travel': TRAVEL})
        try:
            await session.accept(InputEvent(id='negated-change', type='text', text='Do not change the destination. The current one is correct.'))
            await session.inputs.join()
            self.assertFalse(session.speech_muted)
            self.assertTrue(any(e['type'] == 'work_retained' for e in session.trace))
        finally: await session.close()

    async def test_local_schema_keeps_submitted_action_identifiers(self):
        planner = ModelPlanner()
        planner.generate = AsyncMock(return_value={'intent': 'status'})
        context = {'date': '2026-09-14', 'timezone': 'Asia/Kolkata', 'history': [], 'manifests': [TRAVEL.model_dump()],
            'actions': [{'call_id': 'action-42', 'tool': 'flights.reserve', 'status': 'completed'}]}
        try:
            with patch('thread_agent.planner.settings', return_value={'provider': 'local'}):
                await planner.interpret(context, InputEvent(id='status', type='text', text='What happened to my action?'))
            schema = planner.generate.await_args.args[1]
            self.assertIn('action-42', schema['properties']['action_id']['enum'])
        finally: await planner.close()


if __name__ == '__main__': unittest.main()
