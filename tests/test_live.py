import asyncio
import base64
import json
import unittest
from unittest.mock import AsyncMock, patch

from thread_agent.engine import Session
from thread_agent.live import LiveConversation, tool_schema
from thread_agent.protocol import InputEvent


class NoBatchPlanner:
    async def interpret(self, *args):
        raise AssertionError('Native voice must not enter the batch planner')


class Browser:
    def __init__(self): self.events = []
    async def send_json(self, event): self.events.append(event)


class NativeTaskTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.session = Session(NoBatchPlanner(), date='2026-09-13')
        self.session.sandbox.config.update(read_delay=.05, prepare_delay=.1)
        self.browser = Browser()
        self.live = LiveConversation(self.session, self.browser)
        self.live.input_epoch = 1
        self.session.live_feedback = self.live.feedback

    async def asyncTearDown(self): await self.session.close()

    async def test_typed_turn_is_ordered_and_explicitly_complete(self):
        packets=[]
        class Upstream:
            async def send(self,raw): packets.append(json.loads(raw))
        self.live.upstream=Upstream()
        await self.live.send_text_turn('Keep the current date; change the city.')
        self.assertEqual(packets,[{'clientContent':{'turns':[{'role':'user','parts':[{'text':'Keep the current date; change the city.'}]}],'turnComplete':True}}])

    async def test_native_document_uses_structured_json(self):
        response=await self.live.handle_tool({'id':'doc-one','name':'publish_document','args':{'base_revision':0,'kind':'checklist','title':'Packing','blocks':[{'heading':'Essentials','items':['Camera','Rain jacket']} ]}})
        self.assertTrue(response['ok']);self.assertEqual(response['state']['domain'],'document')
        self.assertEqual(response['state']['results']['items'][0]['document']['blocks'][0]['items'],['Camera','Rain jacket'])

    async def test_native_document_error_explicitly_denies_success(self):
        response=self.live.apply_tool({'id':'doc-bad','name':'publish_document','args':{'base_revision':0,'kind':'plan','title':'Empty','blocks':[]}})
        self.assertFalse(response['ok']);self.assertEqual(self.session.domain,'');self.assertIn('Never claim success',response['instruction'])

    async def test_native_document_title_cannot_be_mistaken_for_finished_work(self):
        response=self.call('title-only',intent='revise',domain='document',base_revision=0,
                           changes=[{'slot':'kind','value':'plan'},{'slot':'title','value':'Kyoto'}])
        self.assertFalse(response['ok']);self.assertEqual(self.session.domain,'')
        self.assertIn('publish_document',response['error'])

    async def test_native_weather_is_independent_of_google_grounding(self):
        with patch('thread_agent.sandbox.safe_execute',new=AsyncMock(return_value={'status':'completed','items':[{'id':'weather-test','kind':'weather','title':'Chennai'}],'provenance':'live','source':'Open-Meteo'})) as lookup:
            response=await self.live.handle_tool({'id':'weather-one','name':'get_weather','args':{'base_revision':0,'city':'Chennai','country_code':'IN','days':3}})
        self.assertTrue(response['ok']);self.assertEqual(response['state']['domain'],'weather')
        self.assertEqual(response['state']['results']['provenance'],'live')
        self.assertEqual(lookup.call_args.args[:2],('weather',{'days':3,'city':'Chennai','country_code':'IN'}))

    async def test_native_weather_invalid_days_does_not_change_task(self):
        response=self.live.apply_tool({'id':'weather-bad','name':'get_weather','args':{'base_revision':0,'city':'Tokyo','days':100}})
        self.assertFalse(response['ok']);self.assertEqual(self.session.domain,'')

    async def test_new_football_subject_drops_old_identity_but_keeps_requested_count(self):
        evidence={'status':'completed','items':[],'provenance':'live','source':'Test sports evidence'}
        with patch('thread_agent.sandbox.safe_execute',new=AsyncMock(return_value=evidence)):
            first=await self.live.handle_tool({'id':'bruno-one','name':'get_recent_games','args':{'base_revision':0,'query':'Bruno Fernandes','entity_type':'player','entity_id':'124091','team':'Manchester United','limit':3}})
            self.assertTrue(first['ok'])
            second=await self.live.handle_tool({'id':'bruno-two','name':'get_recent_games','args':{'base_revision':self.session.revision,'query':'Bruno Guimaraes','entity_type':'player'}})
        self.assertTrue(second['ok'])
        self.assertEqual(self.session.slots['limit'],3)
        self.assertNotIn('entity_id',self.session.slots)
        self.assertNotIn('team',self.session.slots)

    async def test_unmentioned_constraint_removal_is_rejected(self):
        await self.search()
        self.session.slots['after']='21:00'
        self.session.transcript.append({'id':'user-edit','role':'user','text':'Change the destination to Delhi on October eighth.'})
        result=self.call('unasked-removal',intent='revise',base_revision=1,remove=['after'],changes=[{'slot':'destination','value':'Delhi'}])
        self.assertFalse(result['ok']);self.assertEqual(self.session.slots['after'],'21:00')
        self.assertEqual(self.session.slots['destination'],'Mumbai')
        invented=self.call('invented-quote',intent='revise',base_revision=1,remove=['after'],remove_evidence=[{'slot':'after','quote':'Remove the after limit'}])
        self.assertFalse(invented['ok']);self.assertEqual(self.session.slots['after'],'21:00')

    async def test_explicit_final_clear_command_survives_omitted_model_removal(self):
        await self.search()
        self.session.slots['after']='21:00'
        self.session.transcript.append({'id':'user-edit','role':'user','text':'Before nine in the evening instead. Remove the after limit.'})
        # The model omitted remove. The explicit final command still takes effect.
        result=await self.live.handle_tool({'id':'explicit-removal','name':'update_task','args':{'intent':'revise','base_revision':1,'domain':'travel','changes':[{'slot':'before','value':'21:00'}]}})
        self.assertTrue(result['ok']);self.assertNotIn('after',self.session.slots)
        self.assertEqual(self.session.slots['before'],'21:00')

    async def test_negated_removal_is_not_an_explicit_clear_command(self):
        await self.search()
        self.session.slots['after']='21:00'
        self.session.transcript.append({'id':'user-edit','role':'user','text':'Change the city to Delhi. Do not remove the after limit.'})
        result=self.call('keep-limit',intent='revise',base_revision=1,changes=[{'slot':'destination','value':'Delhi'}])
        self.assertTrue(result['ok']);self.assertEqual(self.session.slots['after'],'21:00')

    async def test_note_acknowledgement_cannot_become_a_native_write(self):
        preview=await self.live.handle_tool({'id':'note-preview','name':'lookup_notes','args':{'base_revision':0,'title':'Native save boundary','body':'Test preview only.'}})
        rid=preview['state']['results']['id']
        self.session.transcript.append({'id':'user-ack','role':'user','text':'That wording looks good.', 'input_epoch': self.live.input_epoch})
        self.live.begin_input_turn('That wording looks good.')
        refused=self.call('bad-save',intent='commit',domain='notes',base_revision=1,results_id=rid)
        self.assertFalse(refused['ok']);self.assertFalse(self.session.sandbox.submissions)
        self.session.transcript.append({'id':'user-save','role':'user','text':'Please save that exact note now.', 'input_epoch': self.live.input_epoch})
        self.live.begin_input_turn('Please save that exact note now.')
        allowed=self.call('allowed-save',intent='commit',domain='notes',base_revision=1,results_id=rid)
        self.assertTrue(allowed['ok'])

    def call(self, call_id, **args):
        args.setdefault('input_token', self.live.input_token)
        return self.live.apply_tool({'id':call_id, 'name':'update_task', 'args':args})

    async def search(self):
        result = self.call('search', intent='revise', domain='travel', base_revision=0,
                           changes=[{'slot':k,'value':v} for k,v in {'origin':'Chennai','destination':'Mumbai','date':'2026-10-08'}.items()])
        self.assertNotIn('error',result)
        await asyncio.wait_for(asyncio.gather(*(op['task'] for op in self.session.operations.values()
            if op['purpose']=='lookup' and op.get('task'))), 2)

    async def test_native_task_keeps_corrections_and_rejects_stale_calls(self):
        await self.search()
        old_results = self.session.results['id']
        result = self.call('correction',intent='revise',base_revision=1,changes=[{'slot':'destination','value':'Delhi'}])
        self.assertEqual(result['state']['slots']['date'],'2026-10-08')
        self.assertEqual(result['state']['slots']['destination'],'Delhi')
        stale = self.call('stale',intent='commit',base_revision=1,results_id=old_results)
        self.assertIn('error',stale)
        self.assertFalse(self.session.sandbox.submissions)
        self.assertEqual(self.call('correction',intent='cancel',base_revision=2),result)

    async def test_barge_in_holds_then_cancels_prepared_write(self):
        await self.search()
        s=self.session; rid=s.results['id']; option=s.results['items'][0]['id']
        self.call('select',intent='select',base_revision=1,selection=option,results_id=rid)
        s.transcript.append({'id':'explicit-booking', 'role':'user', 'text':'Book that selected flight.', 'input_epoch': self.live.input_epoch})
        self.live.begin_input_turn('Book that selected flight.')
        self.call('book',intent='commit',base_revision=1,results_id=rid)
        s.yield_floor(); self.live.user_speaking=True; self.live.begin_input_turn()
        await asyncio.sleep(.14)
        self.assertFalse(s.sandbox.submissions)
        rejected=self.call('old-call',intent='commit',base_revision=1,results_id=rid)
        self.assertIn('error',rejected)
        self.live.user_speaking=False
        self.live.begin_input_turn('Cancel the search.')
        self.call('cancel',intent='cancel',base_revision=1)
        await asyncio.sleep(.05)
        self.assertFalse(s.sandbox.submissions)
        self.assertEqual(next(o for o in s.operations.values() if o['purpose']=='create')['status'],'not_submitted')

    async def test_native_feedback_is_not_a_second_spoken_transcript(self):
        count=len(self.session.transcript)
        self.session.say('Backend lookup is pending.')
        self.assertEqual(len(self.session.transcript),count)
        self.assertEqual((await self.live.feedback.get())['type'],'task_feedback')
        self.assertNotIn('$defs',tool_schema()['parametersJsonSchema'])

    async def test_greeting_cannot_resume_prepared_actions(self):
        self.live.input_epoch = 0
        self.session.floor_held = True
        result = self.call('greeting-tool', intent='resume', base_revision=0)
        self.assertIn('error',result)
        self.assertTrue(self.session.floor_held)

    async def test_fast_lookup_returns_once_with_tool_response(self):
        consumer = asyncio.create_task(self.live.receive_feedback())
        try:
            result = await self.live.handle_tool({'id':'fast','name':'update_task','args':{
                'intent':'revise','domain':'travel','base_revision':0,
                'changes':[{'slot':k,'value':v} for k,v in {'origin':'Chennai','destination':'Delhi','date':'2026-10-08'}.items()]}})
            self.assertEqual(len(result['state']['results']['items']),4)
            self.assertTrue(self.live.feedback.empty())
            self.assertEqual(self.live.buffered_feedback,[])
            self.assertFalse(consumer.done(), 'Fast results must not leak to a second voice update')
        finally:
            consumer.cancel(); await asyncio.gather(consumer,return_exceptions=True)

    async def test_mixed_provider_event_preserves_audio_and_captions(self):
        pcm=base64.b64encode(b'\0\0'*480).decode()
        class Upstream:
            def __aiter__(self):
                async def generate():
                    yield json.dumps({'serverContent':{'inputTranscription':{'text':'Hi'},'outputTranscription':{'text':'Hello'},'modelTurn':{'parts':[{'inlineData':{'data':pcm,'mimeType':'audio/pcm;rate=24000'}}]},'turnComplete':True}})
                return generate()
        self.live.upstream=Upstream()
        await self.live.receive_provider()
        self.assertEqual([e['role'] for e in self.browser.events if e['type']=='caption'],['user','assistant'])
        self.assertEqual(len([e for e in self.browser.events if e['type']=='audio']),1)
        self.assertNotIn(pcm,json.dumps(self.session.trace))


if __name__=='__main__': unittest.main()
