"""Tool execution across tasks and unfamiliar manifests, independent of the model."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from thread_agent.capabilities import Notebook
from thread_agent.engine import Session, uid
from thread_agent.fixtures import obj, text
from thread_agent.live import LiveConversation
from thread_agent.protocol import Manifest, InputEvent, Interpretation, Change


def plan(domain='',intent='revise',**slots):
    return Interpretation(domain=domain,intent=intent,changes=[Change(slot=k,value=v if isinstance(v,str) else json.dumps(v)) for k,v in slots.items()])


class WorkspaceEngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.s=Session(None,date='2026-09-13');self.s.sandbox.config.update(read_delay=.001,prepare_delay=.015,write_delay=.001)
        self.folder=tempfile.TemporaryDirectory();self.s.sandbox.notebook=Notebook(Path(self.folder.name)/'notes.sqlite')
    async def asyncTearDown(self): await self.s.close();self.folder.cleanup()
    async def apply(self,interpretation):
        self.s.floor_held=False
        self.s.apply(interpretation,InputEvent(id=uid('input'),type='text',seen_results=(self.s.results or {}).get('id')))
        pending=[op['task'] for op in self.s.operations.values() if op['purpose']=='lookup' and op.get('task') and not op['task'].done()]
        if pending: await asyncio.wait(pending,timeout=1)
    async def note(self):
        await self.apply(plan('notes',title='Keep',body='Important text'))
    async def saved_note(self):
        await self.note();await self.apply(plan(intent='commit'))
        async with asyncio.timeout(1):
            while not self.s.sandbox.notebook.search(): await asyncio.sleep(.01)
    async def test_calculation_runs_actual_local_executor(self):
        await self.apply(plan('calculate',expression='0.1+0.2'))
        self.assertEqual(self.s.results['items'][0]['value'],'0.3');self.assertEqual(self.s.results['provenance'],'computed')
    async def test_omitted_document_domain_resolves_unique_schema(self):
        await self.apply(plan(kind='checklist',title='Trip',blocks=[{'heading':'Pack','items':['Camera']}]))
        self.assertEqual(self.s.domain,'document');self.assertEqual(self.s.results['items'][0]['document']['title'],'Trip')
    async def test_omitted_date_domain_resolves_unique_schema(self):
        await self.apply(plan(operation='add',start='2028-02-28',days=2));self.assertEqual(self.s.results['items'][0]['value'],'2028-03-01')
    async def test_ambiguous_omitted_domain_cannot_guess(self):
        with self.assertRaises(ValueError): await self.apply(plan(title='A title shared by multiple capabilities'))
        self.assertEqual(self.s.domain,'');self.assertFalse(self.s.operations)
    async def test_calculation_correction_replaces_old_result(self):
        await self.apply(plan('calculate',expression='10*3'));old=self.s.results['id']
        await self.apply(plan(expression='10*4'));self.assertNotEqual(self.s.results['id'],old);self.assertEqual(self.s.results['items'][0]['value'],'40')
    async def test_units_run_actual_executor(self):
        await self.apply(plan('convert',value=1,from_unit='mi',to_unit='km'));self.assertEqual(self.s.results['items'][0]['value'],1.609344)
    async def test_document_survives_calculator_switch(self):
        await self.apply(plan('document',kind='plan',title='Trip',blocks=[{'heading':'Day one','items':['Museum']}]))
        await self.apply(plan('calculate',expression='2+2'));self.assertEqual(self.s.workspace['document:plan']['items'][0]['document']['blocks'][0]['items'],['Museum'])
    async def test_document_revision_replaces_same_kind_shelf(self):
        await self.apply(plan('document',kind='plan',title='Trip',blocks=[{'heading':'Day one','text':'Museum'}]))
        await self.apply(plan(blocks=[{'heading':'Day one','text':'Park'}]));self.assertEqual(len(self.s.workspace),1);self.assertEqual(self.s.slots['title'],'Trip')
    async def test_different_document_kinds_keep_distinct_cards(self):
        await self.apply(plan('document',kind='plan',title='Trip',blocks=[{'heading':'Day one','text':'Museum'}]))
        await self.apply(plan(kind='recipe',title='Dinner',blocks=[{'heading':'Ingredients','items':['Chickpeas']}]))
        self.assertEqual(set(self.s.workspace),{'document:plan','document:recipe'})
    async def test_resume_restores_previous_task_constraints(self):
        await self.apply(plan('convert',value=25,from_unit='c',to_unit='f'));await self.apply(plan('calculate',expression='5*5'))
        await self.apply(plan('convert',intent='resume'));self.assertEqual(self.s.slots,{'value':25,'from_unit':'c','to_unit':'f'})
    async def test_unsupported_does_not_erase_document(self):
        await self.apply(plan('document',kind='writing',title='Letter',blocks=[{'heading':'Draft','text':'Dear friend'}]))
        before=deepcopy(self.s.slots);await self.apply(plan(intent='unsupported'));self.assertEqual(self.s.slots,before)
    async def test_comparison_runs_without_mutating_active_results(self):
        await self.apply(plan('travel',origin='Chennai',destination='Delhi',date='2026-10-08'))
        original=deepcopy(self.s.results)
        await self.apply(plan(intent='compare',destination='Mumbai'))
        self.assertEqual(self.s.results,original);self.assertEqual(self.s.slots['destination'],'Delhi')
        self.assertEqual(self.s.workspace['comparison:travel']['arguments']['destination'],'Mumbai');self.assertFalse(self.s.sandbox.submissions)
    async def test_invalid_schema_cannot_partially_mutate(self):
        await self.apply(plan('convert',value=1,from_unit='m',to_unit='km'));before=deepcopy(self.s.slots)
        with self.assertRaises(ValueError): await self.apply(plan(value=5,unknown='bad'))
        self.assertEqual(self.s.slots,before)
    async def test_nonfinite_input_cannot_poison_serialized_state(self):
        with self.assertRaises(ValueError): await self.apply(plan('convert',value=float('nan'),from_unit='m',to_unit='km'))
        self.assertEqual(self.s.slots,{})
        json.dumps(self.s.snapshot(),allow_nan=False)
    async def test_new_document_clears_obsolete_table(self):
        await self.apply(plan('document',kind='comparison',title='Compare',blocks=[{'heading':'Result','text':'Use A'}],columns=['A','B'],rows=[['one','two']]))
        await self.apply(plan(kind='code',title='A function',blocks=[{'heading':'Code','text':'def f(): return 1'}]))
        self.assertNotIn('columns',self.s.slots);self.assertNotIn('rows',self.s.slots)
    async def test_timer_status_reports_remaining_time(self):
        await self.apply(plan('timer',seconds=60));self.s.report_status()
        self.assertIn('seconds remain',self.s.transcript[-1]['text']);self.assertNotIn('booking',self.s.transcript[-1]['text'])
    async def test_failed_tool_keeps_explicit_error_evidence(self):
        await self.apply(plan('calculate',expression='1/0'))
        self.assertIsNone(self.s.results);op=list(self.s.operations.values())[-1];self.assertEqual(op['status'],'failed');self.assertIn('error',op['result'])
    async def test_retry_after_error_uses_corrected_expression(self):
        await self.apply(plan('calculate',expression='1/0'));await self.apply(plan(expression='1/4'));self.assertEqual(self.s.results['items'][0]['value'],'0.25')
    async def test_readonly_result_cannot_fake_a_booking(self):
        await self.apply(plan('calculate',expression='2+2'));await self.apply(plan(intent='commit'));self.assertFalse(self.s.sandbox.submissions)
    async def test_note_preview_not_saved(self):
        await self.note();self.assertEqual(self.s.sandbox.notebook.search(),[])
    async def test_note_acknowledgment_not_saved(self):
        await self.note();await self.apply(plan(intent='acknowledge'));self.assertEqual(self.s.sandbox.notebook.search(),[])
    async def test_explicit_save_has_persistent_reference(self):
        await self.saved_note();self.assertEqual(self.s.sandbox.notebook.search()[0]['body'],'Important text')
        self.assertTrue(next(o['result']['reference'] for o in self.s.operations.values() if o['purpose']=='create').startswith('NOTE-'))
    async def test_note_correction_invalidates_prepared_save(self):
        await self.note();self.s.sandbox.config['prepare_delay']=.1;await self.apply(plan(intent='commit'))
        await self.apply(plan(body='Changed'));await asyncio.sleep(.12);self.assertEqual(self.s.sandbox.notebook.search(),[])
    async def test_repeated_save_does_not_duplicate_note(self):
        await self.saved_note();await self.apply(plan(intent='commit'));self.assertEqual(len(self.s.sandbox.notebook.search()),1)
    async def test_library_retrieves_saved_data(self):
        await self.saved_note();await self.apply(plan('library',query='Keep'));self.assertEqual(self.s.results['items'][0]['body'],'Important text');self.assertEqual(self.s.results['provenance'],'saved')
    async def test_cancel_different_task_does_not_archive_saved_note(self):
        await self.saved_note();await self.apply(plan('timer',seconds=60));await self.apply(plan(intent='cancel'));await asyncio.sleep(.3)
        self.assertEqual(len(self.s.sandbox.notebook.search()),1)
    async def test_timer_pause_freezes_remaining_time(self):
        await self.apply(plan('timer',seconds=60));before=self.s.results['items'][0]['end_at'];await self.apply(plan(intent='pause'))
        self.assertIn('paused_at',self.s.results['items'][0]);await asyncio.sleep(.025);await self.s.control({'action':'resume'})
        self.assertNotIn('paused_at',self.s.results['items'][0]);self.assertGreater(self.s.results['items'][0]['end_at'],before)
    async def test_timer_cancel_is_visible_in_card(self):
        await self.apply(plan('timer',seconds=60));await self.apply(plan(intent='cancel'));self.assertTrue(self.s.results['items'][0]['cancelled'])
    async def test_speech_only_does_not_pause_timer(self):
        await self.apply(plan('timer',seconds=60));await self.apply(plan(intent='speech_only'));self.assertNotIn('paused_at',self.s.results['items'][0])
    async def test_external_result_cannot_spoof_controller_fields(self):
        self.s.external=True
        await self.apply(plan('calculate',expression='2+2'));op=list(self.s.operations.values())[-1]
        self.s.handle_result(op['id'],{'status':'completed','source':'External calculator','items':[{'id':'one','title':'4'}],
                                     'domain':'notes','id':'spoof','arguments':{'body':'wrong'},'call_id':'spoof'},'notice')
        self.assertEqual(self.s.results['domain'],'calculate');self.assertEqual(self.s.results['call_id'],op['id']);self.assertNotEqual(self.s.results['id'],'spoof')
    async def test_grounding_only_accepts_web_sources(self):
        live=LiveConversation(self.s,None)
        live.publish_grounding({'groundingChunks':[{'web':{'uri':'javascript:alert(1)','title':'Bad'}},{'web':{'uri':'https://example.com','title':'Example'}},{'web':{'uri':'https://example.com','title':'duplicate'}}]})
        self.assertEqual(len(self.s.workspace['web']['items']),1);self.assertEqual(self.s.workspace['web']['provenance'],'live')


UNFAMILIAR = [
    ('parcel','Parcel tracker','parcel_id','parcel.events','ZX-314'),
    ('bookshelf','Library catalogue','isbn','catalog.find','9780140328721'),
    ('museum','Museum visits','exhibition','visits.lookup','Modern ceramics'),
    ('tickets','Issue triage','project','issues.search','Atlas'),
    ('garden','Plant care','species','garden.manual','Ficus elastica'),
    ('inventory','Stock count','sku','stock.read','M8-BOLT'),
    ('transit','Bus services','stop_id','routes.arrivals','STOP-04'),
    ('laundry','Appliance manual','model','manuals.find','Wash-X'),
    ('lab','Experiment record','sample_id','lab.lookup','SAMPLE-7'),
    ('lessons','Learning catalogue','topic','courses.search','Linear algebra'),
    ('cafeteria','Cafeteria menu','date','menu.read','2026-10-08'),
    ('rental','Equipment hire','equipment','rental.availability','Tripod'),
]
for domain,title,slot,tool,value in UNFAMILIAR:
    async def check(self,domain=domain,title=title,slot=slot,tool=tool,value=value):
        self.s.external=True
        m=Manifest(id=domain,title=title,description='An unfamiliar described read capability.',slots=obj({slot:text('Exact user-supplied identifier.')}),tools=[{'name':tool,'description':'Retrieve evidence for the described current identifier.','purpose':'lookup','effect':'read','parameters':obj({slot:text('Identifier.')},[slot])}]).check()
        await self.s.accept(InputEvent(id=uid('manifest'),type='manifest',data={'manifest':m.model_dump()}))
        await self.apply(plan(domain,**{slot:value}));op=list(self.s.operations.values())[-1]
        self.assertEqual(op['tool'],tool);self.assertEqual(op['arguments'],{slot:value})
        await self.s.accept(InputEvent(id=uid('result'),type='tool_result',data={'call_id':op['id'],'result':{'status':'completed','source':title,'items':[{'id':'one','title':'Returned evidence'}]}}))
        self.assertEqual(self.s.results['source'],title);self.assertFalse(self.s.sandbox.submissions)
    setattr(WorkspaceEngineTests,'test_unfamiliar_'+domain,check)
