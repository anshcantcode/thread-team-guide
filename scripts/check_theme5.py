"""Deterministic adversarial replay of the actual two-queue controller boundary.

Scripted interpretations deliberately isolate orchestration; these are NOT model
accuracy results or Samsung scenarios. A separate external mock owns the effects.
"""
import argparse
import asyncio
import base64
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import random
import subprocess
import sys

from PIL import Image
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from thread_agent.adapter import QueueAdapter
from thread_agent.fixtures import TRAVEL, DEVICE, lookup
from thread_agent.protocol import Interpretation, Manifest
from thread_agent.clock import VirtualClock


def plan(intent='revise', domain='', selection='', **slots):
    return Interpretation(intent=intent, domain=domain, selection=selection,
        changes=[{'slot': k, 'value': v if isinstance(v, str) else json.dumps(v)} for k, v in slots.items()])


class ScriptedPlanner:
    def __init__(self, clock):
        self.clock, self.plans, self.contexts = clock, {}, {}

    async def interpret(self, context, event):
        self.contexts[event.id] = deepcopy(context)
        delay, result = self.plans[event.id]
        await self.clock.sleep(delay)
        return deepcopy(result)


class Replay:
    def __init__(self, manifest, seed, *, lost_create=False, stale_status=False):
        self.clock = VirtualClock()
        self.planner = ScriptedPlanner(self.clock)
        self.adapter = QueueAdapter(self.planner, clock=self.clock, manifests=[manifest], date='2026-09-14')
        self.s = self.adapter.session
        self.s.sandbox.config.update(prepare_delay=.12, timeout=.6)
        self.random = random.Random(seed)
        self.effects, self.errors, self.tasks, self.inputs = {}, [], [], []
        self.lost_create, self.stale_status = lost_create, stale_status
        self.consumer = asyncio.create_task(self.adapter.run())
        self.pump = asyncio.create_task(self.output())

    async def flush(self):
        # Bounded cooperative turns; virtual time only advances below, never here.
        for _ in range(24):
            await asyncio.sleep(0)

    async def advance(self, target):
        await self.flush()
        while (due := self.clock.next_deadline()) is not None and due <= target:
            self.clock.advance_to(due)
            await self.flush()
        self.clock.advance_to(target)
        await self.flush()

    async def input(self, ident, text='', interpretation=None, delay=.02, **extra):
        self.planner.plans[ident] = (delay, interpretation or plan('acknowledge'))
        event = {'id': ident, 'type': 'text', 'text': text, **extra}
        self.inputs.append({'at_ms': round(self.clock.now()*1000, 6), 'event': deepcopy(event)})
        await self.adapter.events.put(event)
        await self.flush()

    async def output(self):
        while True:
            action = await self.adapter.actions.get()
            try:
                if action is None: return
                json.dumps(action, allow_nan=False)
                if action['type'] == 'tool_call':
                    matches = [(m, t) for m in self.s.manifests.values() for t in m.tools if t.name == action['tool']]
                    if len(matches) != 1:
                        self.errors.append('Unknown or ambiguous outbound tool')
                        continue
                    manifest, tool = matches[0]
                    if not Draft202012Validator(tool.parameters).is_valid(action['arguments']):
                        self.errors.append('Outbound call violates scenario schema')
                        continue
                    self.tasks.append(asyncio.create_task(self.service(action, manifest, tool)))
            finally:
                self.adapter.actions.task_done()

    async def service(self, action, manifest, tool):
        call_id, args = action['call_id'], action['arguments']
        delay = .25 + self.random.random()*.1
        if tool.purpose == 'lookup':
            domain = 'device' if 'indicator' in args else 'travel'
            result = {'status': 'completed', **lookup(domain, args)}
        elif tool.purpose == 'create':
            # Independent mock ledger: a different call ID is a different effect.
            self.effects.setdefault(call_id, {'args': deepcopy(args), 'reference': 'SERVICE-'+call_id, 'status': 'completed'})
            result = {'status': 'completed', 'reference': self.effects[call_id]['reference']}
            if self.lost_create: return
        else:
            original = args.get('operation_id')
            if original is None:
                original = next((key for key, value in self.effects.items() if value['reference'] == args.get('ticket_ref')), None)
            record = self.effects.get(original)
            if tool.purpose == 'cancel' and record:
                record['status'] = 'cancelled'
            result = {'status': record['status'], 'reference': record['reference']} if record else {'status': 'not_performed'}
            if tool.purpose == 'status' and self.stale_status:
                result, delay = {'status': 'not_performed'}, .7
            if tool.purpose == 'status' and self.lost_create:
                result = {'status': 'unknown'}
        await self.clock.sleep(delay)
        # Deliberately deliver after cancellation; cancellation is only a request.
        for suffix in ('first', 'duplicate'):
            await self.adapter.events.put({'id': call_id+'-'+suffix, 'type': 'tool_result',
                'data': {'call_id': call_id, 'result': deepcopy(result)}})

    async def finish(self, checks):
        await self.advance(max(self.clock.now(), 4))
        await self.adapter.events.put(None)
        await self.advance(self.clock.now()+2)
        await asyncio.wait_for(self.consumer, 1)
        await self.pump
        await asyncio.gather(*self.tasks)
        trace = self.s.trace
        return {'passed': all(checks.values()) and not self.errors, 'checks': checks,
                'protocol_errors': self.errors, 'effects': self.effects, 'state': self.s.summary(),
                'inputs': self.inputs, 'trace': trace,
                'logical_sha256': hashlib.sha256(json.dumps({'trace': trace, 'effects': self.effects}, sort_keys=True).encode()).hexdigest()}


async def booking(seed):
    r = Replay(TRAVEL, seed)
    await r.input('request', 'Chennai to Delhi tomorrow after nine', plan(domain='travel', origin='Chennai', destination='Delhi', date='2026-09-15', after='21:00'))
    await r.advance(.06)
    await r.input('repair', 'Actually Mumbai, keep everything else', plan(destination='Mumbai'))
    await r.advance(.7)
    ids = [i['id'] for i in r.s.results['items']]
    await r.input('book-a', 'Book the first option', plan('commit', selection=ids[0]))
    await r.advance(.74 + r.random.random()*.04)
    await r.input('choose-b', 'Wait, select the second instead', plan('select', selection=ids[1]))
    await r.advance(1)
    no_premature_effect = not r.effects
    await r.input('authorize-b', 'Book that second option', plan('commit'))
    await r.advance(2)
    state = r.s.slots
    return await r.finish({'selection_change_revoked_old_authority': no_premature_effect,
        'one_effect_for_current_option': len(r.effects) == 1 and next(iter(r.effects.values()))['args']['option_id'] == ids[1],
        'unrelated_constraints_preserved': state['origin'] == 'Chennai' and state['after'] == '21:00' and state['date'] == '2026-09-15',
        'latest_destination_only': state['destination'] == 'Mumbai' and r.s.results['arguments']['destination'] == 'Mumbai',
        'obsolete_read_excluded': any(e['type'] == 'stale_result_excluded' for e in r.s.trace)})


async def outcomes(seed, lost=False):
    r = Replay(TRAVEL, seed, lost_create=lost, stale_status=not lost)
    await r.input('request', interpretation=plan(domain='travel', origin='Chennai', destination='Delhi', date='2026-09-15'))
    await r.advance(.6)
    await r.input('book', 'Book this option', plan('commit', selection=r.s.results['items'][0]['id']))
    await r.advance(.76)
    await r.input('status', interpretation=plan('status'))
    await r.advance(1.8)
    await r.input('repeat', 'Book it', plan('commit'))
    await r.advance(2.5)
    op = next(o for o in r.s.operations.values() if o['purpose'] == 'create')
    return await r.finish({'single_effect': len(r.effects) == 1,
        'outcome_preserved': op['status'] == ('unknown' if lost else 'completed'),
        'unknown_visible': bool(r.s.unresolved()) if lost else not r.s.unresolved()})


async def unfamiliar(seed):
    raw = TRAVEL.model_dump()
    raw.update(id='expedition', title='Expedition permit')
    for t in raw['tools']:
        t['name'] = 'permit.' + t['purpose']
        if t['purpose'] == 'create': t['authorization_objects'] = ['permit']
        if t['purpose'] in ('cancel', 'status'):
            t['parameters'] = {'type': 'object', 'properties': {'ticket_ref': {'type': 'string'}}, 'required': ['ticket_ref'], 'additionalProperties': False}
            t['bindings'] = {'ticket_ref': 'reference'}
    r = Replay(Manifest.model_validate(raw).check(), seed)
    await r.input('permit', interpretation=plan(domain='expedition', origin='Leh', destination='Nubra', date='2026-09-15'))
    await r.advance(.6)
    await r.input('create', 'Create this permit', plan('commit', selection=r.s.results['items'][0]['id']))
    await r.advance(1.3)
    await r.input('cancel', 'Cancel the permit', plan('cancel'))
    await r.advance(2)
    cancel = next(o for o in r.s.operations.values() if o['purpose'] == 'cancel')
    return await r.finish({'one_created_then_cancelled': len(r.effects) == 1 and next(iter(r.effects.values()))['status'] == 'cancelled',
        'service_reference_binding': set(cancel['arguments']) == {'ticket_ref'}, 'no_builtin_manifest_leak': set(r.s.manifests) == {'expedition'}})


async def perception(seed):
    raw = DEVICE.model_dump()
    raw['id'] = 'camera_support'
    r = Replay(Manifest.model_validate(raw).check(), seed)
    png = io.BytesIO()
    Image.new('RGB', (16, 16), '#808080').save(png, format='PNG')
    media = {'mime': 'image/png', 'base64': base64.b64encode(png.getvalue()).decode()}
    await r.input('frame-a', interpretation=plan(domain='camera_support', model='THREAD R1', indicator='power'), type='frame', data=media)
    await r.advance(.08)
    await r.input('frame-b', interpretation=plan('clarify', domain='camera_support', model='THREAD R1'), type='frame', data=media)
    await r.advance(.6)
    old_excluded = r.s.results is None and 'indicator' not in r.s.slots
    await r.input('target', 'The network indicator', plan(domain='camera_support', indicator='network'))
    await r.advance(1.2)
    final = next(e for e in reversed(r.s.trace) if e['type'] == 'final')
    return await r.finish({'old_frame_excluded': old_excluded, 'new_frame_bound': r.s.results['media_id'] == 'frame-b',
        'correct_manual_section': final['state_snapshot']['evidence']['evidence']['page'] == 3,
        'spoken_guidance_grounded': 'connection' in final['text'], 'no_effects_from_perception': not r.effects})


async def preemption(seed):
    r = Replay(TRAVEL, seed)
    await r.input('original', 'Chennai to Delhi on September 15', plan(domain='travel', origin='Chennai', destination='Delhi', date='2026-09-15'), delay=5)
    await r.advance(.05 + r.random.random()*.2)
    await r.input('correction', 'Actually Mumbai', plan(domain='travel', origin='Chennai', destination='Mumbai', date='2026-09-15'))
    await r.advance(.8)
    context = r.planner.contexts['correction']
    return await r.finish({'correction_did_not_wait_five_seconds': r.s.slots.get('destination') == 'Mumbai',
        'pending_words_retained': context['unprocessed_inputs'][0]['text'] == 'Chennai to Delhi on September 15',
        'old_intent_never_applied': not any(e['type'] == 'intent_interpreted' and e['input_id'] == 'original' for e in r.s.trace)})


SCENARIOS = [('booking_repair', booking), ('reordered_outcome', outcomes),
             ('unknown_outcome', lambda s: outcomes(s, True)), ('unfamiliar_chain', unfamiliar),
             ('replaced_frame', perception), ('preempted_reasoning', preemption)]


async def fingerprints(seeds):
    rows = []
    for seed in range(seeds):
        for name, fn in SCENARIOS:
            result = await fn(seed)
            rows.append({'scenario': name, 'seed': seed, 'passed': result['passed'], 'logical_sha256': result['logical_sha256']})
    return rows


async def run(seeds):
    rows = []
    for seed in range(seeds):
        for name, fn in SCENARIOS:
            result = await fn(seed)
            repeated = await fn(seed)
            result['checks']['same_seed_identical_trace'] = result['logical_sha256'] == repeated['logical_sha256']
            result['passed'] = result['passed'] and result['checks']['same_seed_identical_trace']
            rows.append({'scenario': name, 'seed': seed, **result})
        if seed % 10 == 0: print(f'Completed seed {seed}; {len(rows)} scenario checks', flush=True)
    expected = [{k: row[k] for k in ('scenario', 'seed', 'passed', 'logical_sha256')} for row in rows]
    fresh = []
    for hash_seed in ('1', '2'):
        process = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--fingerprints', '--seeds', str(seeds)],
            env={**os.environ, 'PYTHONHASHSEED': hash_seed}, capture_output=True, text=True, timeout=120)
        actual = json.loads(process.stdout) if process.returncode == 0 else []
        fresh.append({'python_hash_seed': hash_seed, 'exit_code': process.returncode,
            'scenarios_checked': len(actual), 'identical': actual == expected,
            'logical_sha256': hashlib.sha256(json.dumps(actual, sort_keys=True).encode()).hexdigest()})
        print(f'Fresh interpreter PYTHONHASHSEED={hash_seed}: {len(actual)} checks, identical={actual == expected}', flush=True)
    hashes = {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
              for base in ('thread_agent', 'scripts', 'tests') for p in (ROOT/base).glob('*.py')}
    report = {'format': 'THREAD deterministic replay v1', 'official_evaluation': False,
        'interpretations': 'scripted controller tests, not model understanding or acoustic measurements',
        'clock': 'virtual seconds, fixed 2026-09-14 UTC epoch', 'seeds': seeds,
        'scenario_count': len(rows), 'executions': len(rows)*2 + sum(p['scenarios_checked'] for p in fresh),
        'paired_executions': len(rows)*2, 'fresh_process_checks': fresh,
        'passed': all(r['passed'] for r in rows) and all(p['identical'] for p in fresh),
        'source_sha256': hashes, 'cases': rows}
    destination = ROOT/'reports'/'theme5-replay.json'
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('cases', 'source_sha256')}, indent=2))
    print(destination)
    return report['passed']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', type=int, default=50)
    parser.add_argument('--fingerprints', action='store_true', help='Fresh-process verification mode; emits JSON only and writes no report.')
    args = parser.parse_args()
    if not 1 <= args.seeds <= 1000: parser.error('Use 1–1000 fixed seeds.')
    if args.fingerprints:
        print(json.dumps(asyncio.run(fingerprints(args.seeds)), sort_keys=True))
    else:
        raise SystemExit(0 if asyncio.run(run(args.seeds)) else 1)
