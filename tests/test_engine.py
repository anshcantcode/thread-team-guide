import asyncio
from copy import deepcopy
import unittest

from thread_agent.engine import Session, uid
from thread_agent.fixtures import TRAVEL, lookup
from thread_agent.protocol import InputEvent, Interpretation, Change, Manifest


def plan(intent='revise', domain='', selection='', **slots):
    import json
    return Interpretation(intent=intent, domain=domain, selection=selection,
                          changes=[Change(slot=k, value=json.dumps(v) if not isinstance(v, str) else v) for k,v in slots.items()])


class FakePlanner:
    def __init__(self): self.next = None; self.delay = 0
    async def interpret(self, context, event):
        result = deepcopy(self.next)
        await asyncio.sleep(self.delay)
        return result


async def eventually(predicate, timeout=1):
    async with asyncio.timeout(timeout):
        while not predicate(): await asyncio.sleep(.005)


class EngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.planner = FakePlanner()
        self.s = Session(self.planner, date='2026-09-12')
        self.s.sandbox.config.update(read_delay=.03, write_delay=.09, prepare_delay=.04, timeout=.16)

    async def asyncTearDown(self):
        await self.s.close()

    async def apply(self, interpretation, id=None):
        self.planner.next = interpretation
        text = 'Create another separate action.' if interpretation.intent == 'additional_action' else 'Create the selected action.' if interpretation.intent == 'commit' else 'test input'
        text = {'cancel': 'Cancel that action.', 'stop_work': 'Cancel the search.', 'speech_only': 'Stop talking, keep searching.'}.get(interpretation.intent, text)
        await self.s.accept(InputEvent(id=id or uid('input'), type='text', text=text, seen_results=(self.s.results or {}).get('id')))
        await self.s.inputs.join()

    async def flights(self):
        await self.apply(plan(domain='travel', origin='Chennai', destination='Delhi', date='2026-09-13', after='18:00'))
        await eventually(lambda: self.s.results is not None)

    async def select(self):
        await self.apply(plan('select',selection=self.s.results['items'][0]['id']))

    async def test_correction_preserves_other_slots_and_excludes_late_result(self):
        self.s.sandbox.config['late_reads'] = True
        await self.apply(plan(domain='travel',origin='Chennai',destination='Delhi',date='2026-09-13',after='21:00'))
        await self.apply(plan(destination='Mumbai'))
        await eventually(lambda: self.s.results is not None)
        self.assertEqual(self.s.slots['origin'], 'Chennai')
        self.assertEqual(self.s.slots['after'], '21:00')
        self.assertTrue(all(i['destination'] == 'Mumbai' for i in self.s.results['items']))
        self.assertTrue(any(e['type'] == 'stale_result_excluded' for e in self.s.trace))

    async def test_rapid_corrections_settle_on_final_destination(self):
        self.s.sandbox.config['late_reads'] = True
        await self.apply(plan(domain='travel',origin='Chennai',destination='Delhi',date='2026-09-13'))
        await self.apply(plan(destination='Mumbai'))
        await self.apply(plan(destination='Bengaluru'))
        await eventually(lambda: self.s.results is not None)
        self.assertEqual(self.s.results['arguments']['destination'], 'Bengaluru')
        self.assertEqual(sum(e['type']=='results_published' for e in self.s.trace), 1)

    async def test_completed_lookup_is_superseded_without_claiming_it_was_cancelled(self):
        await self.flights()
        completed=self.s.results['call_id']
        await self.apply(plan(destination='Mumbai'))
        self.assertTrue(self.s.operations[completed]['obsolete'])
        self.assertFalse(any(e['type'] in ('cancel','cancellation_confirmed') and e.get('call_id')==completed for e in self.s.trace))

    async def test_received_but_held_result_is_not_described_as_cancelled(self):
        await self.apply(plan(domain='travel',origin='Chennai',destination='Delhi',date='2026-09-13'))
        call=next(iter(self.s.operations))
        self.planner.delay=.12; self.planner.next=plan(destination='Mumbai')
        await self.s.accept(InputEvent(id='slow-correction',type='text',text='Actually Mumbai'))
        await eventually(lambda:any(e['type']=='result_held' for e in self.s.trace))
        await self.s.control({'action':'cancel'})
        await self.s.inputs.join()
        self.assertIsNone(self.s.results)
        self.assertFalse(any(e['type'] in ('cancel','cancellation_confirmed') and e.get('call_id')==call for e in self.s.trace))

    async def test_unrelated_preference_retains_lookup(self):
        await self.apply(plan(domain='travel',origin='Chennai',destination='Delhi',date='2026-09-13'))
        first = next(iter(self.s.operations))
        await self.apply(plan(seat='aisle'))
        await eventually(lambda: self.s.results is not None)
        self.assertEqual(self.s.results['call_id'], first)
        self.assertEqual(len(self.s.operations), 1)

    async def test_reconnect_resume_keeps_applicable_completed_results(self):
        await self.flights()
        call=self.s.results['call_id']
        self.s.yield_floor()
        await self.s.control({'action':'resume'})
        self.assertFalse(self.s.floor_held)
        self.assertEqual(self.s.results['call_id'],call)
        self.assertEqual(len(self.s.operations),1)

    async def test_passenger_change_recomputes_availability_and_price(self):
        await self.flights()
        previous = self.s.results['id']
        await self.apply(plan(passengers=5))
        await eventually(lambda: self.s.results is not None)
        self.assertNotEqual(previous, self.s.results['id'])
        self.assertTrue(all(i['passengers']==5 for i in self.s.results['items']))
        self.assertFalse(any(i['departure']=='21:40' for i in self.s.results['items']))

    async def test_missing_date_does_not_search(self):
        await self.apply(plan(domain='travel',origin='Chennai',destination='Mumbai'))
        self.assertEqual(self.s.missing(), ['date'])
        self.assertFalse(self.s.operations)

    async def test_contradiction_is_preserved_and_blocks_work(self):
        await self.apply(plan(domain='travel',origin='Chennai',destination='Mumbai',date='2026-09-13',after='22:00',before='20:00'))
        self.assertTrue(self.s.paused)
        self.assertEqual(self.s.slots['before'], '20:00')
        self.assertFalse(self.s.operations)

    async def test_no_matches_differs_from_failure(self):
        await self.flights()
        await self.apply(plan(after='23:00'))
        await eventually(lambda: self.s.results is not None)
        self.assertEqual(self.s.results['items'], [])
        self.s.sandbox.config['fail_next_read'] = True
        await self.apply(plan(after='22:00'))
        await eventually(lambda: any(op['status']=='failed' for op in self.s.operations.values()))
        self.assertIsNone(self.s.results)
        self.assertEqual(self.s.slots['after'], '22:00')

    async def test_acknowledgement_and_status_do_not_duplicate_search(self):
        await self.flights()
        await self.apply(plan('acknowledge'))
        await self.apply(plan('status'))
        self.assertEqual(len(self.s.operations),1)
        self.assertEqual(len(self.s.sandbox.submissions),0)

    async def test_hypothetical_cannot_mutate_intent(self):
        await self.flights()
        await self.apply(plan('compare',destination='Mumbai'))
        self.assertEqual(self.s.slots['destination'], 'Delhi')

    async def test_before_submission_stop_prevents_service_call(self):
        await self.flights(); await self.select(); await self.apply(plan('commit'))
        await self.s.control({'action':'cancel'})
        await asyncio.sleep(.08)
        self.assertEqual(self.s.sandbox.submissions,[])
        self.assertTrue(any(op['status']=='not_submitted' for op in self.s.operations.values()))

    async def test_new_utterance_holds_prepared_write_while_model_is_slow(self):
        await self.flights(); await self.select(); await self.apply(plan('commit'))
        self.planner.delay = .10; self.planner.next = plan('cancel')
        await self.s.accept(InputEvent(id=uid('input'),type='text',text="Wait, don't book it"))
        await asyncio.sleep(.07)
        self.assertEqual(self.s.sandbox.submissions, [])
        await self.s.inputs.join()
        self.assertEqual(self.s.sandbox.submissions, [])

    async def test_post_submission_cancel_is_not_instant_confirmation(self):
        self.s.sandbox.config['write_delay']=.5
        await self.flights(); await self.select(); await self.apply(plan('commit'))
        await eventually(lambda: bool(self.s.sandbox.submissions))
        await self.s.control({'action':'cancel'})
        self.assertTrue(any(op['status']=='cancel_requested' for op in self.s.operations.values()))
        await eventually(lambda: any(op['status']=='not_performed' for op in self.s.operations.values()))
        self.assertEqual(self.s.sandbox.creations, [])

    async def test_duplicate_input_and_result_create_only_one_record(self):
        await self.flights(); await self.select()
        await self.apply(plan('commit'),id='same-delivery')
        await self.apply(plan('commit'),id='same-delivery')
        await eventually(lambda: any(op['purpose']=='create' and op['status']=='completed' for op in self.s.operations.values()))
        await self.s.control({'action':'duplicate_result'})
        self.assertEqual(len(self.s.sandbox.submissions),1)
        self.assertEqual(len(self.s.sandbox.creations),1)
        self.assertTrue(any(e['type']=='duplicate_result_ignored' for e in self.s.trace))

    async def test_unknown_outcome_blocks_replacement(self):
        self.s.sandbox.config['action_mode']='delayed'
        await self.flights(); await self.select(); await self.apply(plan('commit'))
        await eventually(lambda: bool(self.s.unresolved()))
        await self.apply(plan('commit'))
        self.assertEqual(len(self.s.sandbox.submissions),1)

    async def test_late_write_survives_goal_switch(self):
        await self.flights(); await self.select(); await self.apply(plan('commit'))
        await eventually(lambda: bool(self.s.sandbox.submissions))
        await self.apply(plan(domain='device',model='THREAD R1',indicator='network'))
        await eventually(lambda: any(op['purpose']=='create' and op['status']=='completed' for op in self.s.operations.values()))
        self.assertEqual(self.s.domain,'device')
        # The current manual lookup can finish after the older write's notice.
        # Both completions must be retained, regardless of callback ordering.
        self.assertTrue(any('earlier request' in row['text'] for row in self.s.transcript if row['role'] == 'assistant'))
        self.assertTrue(any(action['status'] == 'completed' and action['confirmed_reference'] for action in self.s.summary()['actions']))

    async def test_explicit_additional_action_is_allowed(self):
        await self.flights(); await self.select(); await self.apply(plan('commit'))
        await eventually(lambda: len(self.s.sandbox.creations)==1)
        await self.apply(plan('additional_action'))
        await eventually(lambda: len(self.s.sandbox.creations)==2)
        self.assertEqual(len(self.s.sandbox.submissions),2)

    async def test_changed_details_invalidate_prior_authorization(self):
        await self.flights(); await self.select(); await self.apply(plan('commit'))
        await self.apply(plan(destination='Mumbai'))
        await asyncio.sleep(.09)
        self.assertEqual(self.s.sandbox.submissions,[])
        self.assertIsNone(self.s.selection)

    async def test_stale_result_reference_cannot_select(self):
        await self.flights()
        old_id=self.s.results['id']
        await self.apply(plan(destination='Mumbai'))
        await eventually(lambda: self.s.results is not None)
        self.s.apply(plan('select',selection=self.s.results['items'][0]['id']),InputEvent(id=uid('input'),type='text',seen_results=old_id))
        self.assertIsNone(self.s.selection)

    async def test_stop_speech_preserves_search(self):
        await self.apply(plan(domain='travel',origin='Chennai',destination='Delhi',date='2026-09-13'))
        await self.apply(plan('speech_only'))
        await eventually(lambda: self.s.results is not None)
        self.assertTrue(self.s.speech_muted)

    async def test_stop_task_excludes_late_reads(self):
        self.s.sandbox.config['late_reads']=True
        await self.apply(plan(domain='travel',origin='Chennai',destination='Delhi',date='2026-09-13'))
        await self.apply(plan('stop_work'))
        await asyncio.sleep(.06)
        self.assertIsNone(self.s.results)
        self.assertTrue(self.s.paused)
        self.assertTrue(any(e['type'] == 'cancel' for e in self.s.trace))

    async def test_target_correction_retains_model_and_cites_correct_section(self):
        self.s.sandbox.config['late_reads']=True
        await self.apply(plan(domain='device',model='THREAD R1',indicator='power'))
        await self.apply(plan(indicator='network'))
        await eventually(lambda: self.s.results is not None)
        self.assertEqual(self.s.slots['model'],'THREAD R1')
        self.assertEqual(self.s.results['evidence']['page'],3)
        self.assertIn('network',self.s.results['items'][0]['id'])

    async def test_unknown_device_has_no_matching_manual(self):
        await self.apply(plan(domain='device',model='Real router X',indicator='network'))
        await eventually(lambda: self.s.results is not None)
        self.assertEqual(self.s.results['items'],[])
        self.assertIn('No matching',self.s.results['note'])

    async def test_replaced_frame_cannot_inherit_inflight_visual_interpretation(self):
        started=asyncio.Event(); release=asyncio.Event()
        async def interpret(context,event):
            if event.id=='old-frame':
                started.set(); await release.wait()
                return plan(domain='device',model='OLD DEVICE',indicator='network')
            return plan('clarify',domain='device',model='NEW DEVICE')
        self.planner.interpret=interpret
        await self.s.accept(InputEvent(id='old-frame',type='frame',data={'mime':'image/png','base64':'old'}))
        await started.wait()
        await self.s.accept(InputEvent(id='new-frame',type='frame',data={'mime':'image/png','base64':'new'}))
        release.set(); await self.s.inputs.join()
        self.assertEqual(self.s.slots['model'],'NEW DEVICE')
        self.assertNotIn('indicator',self.s.slots)
        self.assertFalse(self.s.operations)
        self.assertTrue(any(e['type']=='interpretation_superseded' for e in self.s.trace))

    async def test_new_session_has_no_task_memory(self):
        await self.flights()
        other=Session(self.planner)
        self.assertFalse(other.slots); self.assertFalse(other.operations)
        await other.close()

    async def test_end_preserves_unresolved_outcome(self):
        self.s.sandbox.config['action_mode']='delayed'
        await self.flights(); await self.select(); await self.apply(plan('commit'))
        await eventually(lambda: bool(self.s.sandbox.submissions))
        await self.s.control({'action':'end'})
        self.assertTrue(self.s.ended); self.assertTrue(self.s.unresolved())
        self.assertIn('does not undo',self.s.transcript[-1]['text'])

    async def test_custom_manifest_uses_described_tool_not_flight_name(self):
        m=TRAVEL.model_copy(deep=True); m.id='newtravel'; m.title='New capability'
        m.tools[0].name='unfamiliar.q9'; m.tools[1].name='unfamiliar.z7'
        self.s.manifests[m.id]=m.check(); self.s.external=True
        await self.apply(plan(domain='newtravel',origin='Chennai',destination='Delhi',date='2026-09-13'))
        op=next(iter(self.s.operations.values()))
        self.assertEqual(op['tool'],'unfamiliar.q9')
        self.s.handle_result(op['id'],{'status':'completed',**lookup('travel',op['arguments'])},'notice-1')
        self.assertIsNotNone(self.s.results)

    async def test_malformed_service_completion_stays_unknown(self):
        self.s.external=True
        await self.apply(plan(domain='travel',origin='Chennai',destination='Delhi',date='2026-09-13'))
        read=next(iter(self.s.operations.values()))
        self.s.handle_result(read['id'],{'status':'completed',**lookup('travel',read['arguments'])},'n1')
        await self.select(); await self.apply(plan('commit'))
        await eventually(lambda: any(o['status']=='submitted' for o in self.s.operations.values()))
        write=next(o for o in self.s.operations.values() if o['purpose']=='create')
        self.s.handle_result(write['id'],{'status':'completed'},'n2')
        self.assertEqual(write['status'],'unknown')

    async def test_unknown_write_result_cannot_finish_a_prepared_action(self):
        await self.flights(); await self.select(); await self.apply(plan('commit'))
        write=next(o for o in self.s.operations.values() if o['purpose']=='create')
        self.s.handle_result(write['id'],{'status':'completed','reference':'UNTRUSTED'},'early')
        self.assertEqual(write['status'],'prepared')

    async def test_cancel_declined_reports_existing_record(self):
        self.s.sandbox.config['action_mode']='too_late'
        await self.flights(); await self.select(); await self.apply(plan('commit'))
        await eventually(lambda: len(self.s.sandbox.creations)==1)
        await self.s.control({'action':'cancel'})
        await eventually(lambda: any(e['type']=='cancellation_declined' for e in self.s.trace))
        write=next(o for o in self.s.operations.values() if o['purpose']=='create')
        self.assertEqual(write['status'],'completed')
        self.assertEqual(len(self.s.sandbox.creations),1)

    async def test_speech_interrupt_signal_holds_prepared_write(self):
        await self.flights(); await self.select(); await self.apply(plan('commit'))
        await self.s.accept(InputEvent(id='speech-onset',type='interrupt'))
        await asyncio.sleep(.07)
        self.assertEqual(self.s.sandbox.submissions,[])

    async def test_return_to_prior_goal_performs_fresh_lookup(self):
        await self.flights()
        previous=self.s.results['call_id']
        await self.apply(plan(domain='device',model='THREAD R1',indicator='power'))
        await self.apply(plan('resume',domain='travel'))
        await eventually(lambda:self.s.results is not None and self.s.results['domain']=='travel')
        self.assertNotEqual(previous,self.s.results['call_id'])
        self.assertEqual(self.s.slots['origin'],'Chennai')

    async def test_partial_starts_only_provisional_read_and_final_reuses_it(self):
        self.s.sandbox.config['read_delay']=.4
        self.planner.next=plan(domain='travel',origin='Chennai',destination='Delhi',date='2026-09-13')
        await self.s.accept(InputEvent(id='partial1',type='partial',text='Find Chennai to Delhi tomorrow',utterance_id='u1'))
        await eventually(lambda:bool(self.s.operations))
        self.assertFalse(self.s.slots)
        self.assertFalse(self.s.sandbox.submissions)
        await self.apply(plan(domain='travel',origin='Chennai',destination='Delhi',date='2026-09-13'))
        await eventually(lambda:self.s.results is not None)
        self.assertEqual(len(self.s.operations),1)

    async def test_domain_switch_removals_do_not_erase_new_valid_slots(self):
        await self.flights()
        p=plan(domain='device',model='THREAD R1',indicator='network'); p.remove=['origin','date']
        await self.apply(p)
        self.assertEqual(self.s.slots['model'],'THREAD R1')
        self.assertNotIn('origin',self.s.slots)


class SchemaTests(unittest.TestCase):
    def test_conflicting_effect_manifest_is_rejected(self):
        m=TRAVEL.model_copy(deep=True); m.tools[1].effect='read'
        with self.assertRaises(ValueError): m.check()

    def test_missing_effect_cannot_be_guessed(self):
        m=TRAVEL.model_dump(); m['tools'][1].pop('effect')
        with self.assertRaises(ValueError): Manifest.model_validate(m)


if __name__=='__main__': unittest.main()
