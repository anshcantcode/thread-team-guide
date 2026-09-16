"""Real wall-clock controller measurements with explicit scripted model delay.

This measures event-loop responsiveness, not AI understanding or acoustic onset.
The actual-model report separately measures semantic interpretation latency.
"""
import argparse
import asyncio
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from thread_agent.engine import Session
from thread_agent.fixtures import TRAVEL
from thread_agent.protocol import InputEvent, Interpretation
from thread_agent.planner import ModelPlanner, settings


class SlowPlanner:
    async def interpret(self, *_):
        await asyncio.sleep(.4)
        return Interpretation(intent='revise', changes=[{'slot': 'destination', 'value': 'Mumbai'}])


async def repetition(index, planner):
    s = Session(planner, external=True, evaluation=True, manifests={'travel': TRAVEL})
    try:
        s.apply(Interpretation(intent='revise', domain='travel', changes=[{'slot': k, 'value': v} for k, v in {
            'origin': 'Chennai', 'destination': 'Delhi', 'date': '2026-09-15'}.items()]), InputEvent(id='setup', type='text'))
        initial = next(o for o in s.operations.values() if o['purpose'] == 'lookup')
        start = (s.clock.now()-s.start_time)*1000
        await s.accept(InputEvent(id='correction', type='text', text='Actually Mumbai, keep everything else.'))
        await s.inputs.join()
        correction = next(e for e in s.trace if e['type'] == 'intent_interpreted')
        cancellation = next(e for e in s.trace if e['type'] == 'cancel' and e['call_id'] == initial['id'])
        coordination = next(e for e in s.trace if e['type'] == 'speak' and e.get('stage') == 'coordination')
        current = next(o for o in s.operations.values() if o['purpose'] == 'lookup' and o['status'] == 'running')
        stop_start = (s.clock.now()-s.start_time)*1000
        await s.accept(InputEvent(id='stop', type='text', text='Stop.'))
        stopped = next(e for e in s.trace if e['type'] == 'cancel' and e['call_id'] == current['id'])
        readings = {'coordination_ms': round(coordination['at_ms']-start, 2),
            'semantic_interpretation_ms': round(correction['at_ms']-start, 2),
            'decision_to_cancel_ms': round(cancellation['at_ms']-correction['at_ms'], 2),
            'explicit_stop_to_cancel_ms': round(stopped['at_ms']-stop_start, 2)}
        checks = {'coordination_under_300ms': readings['coordination_ms'] <= 300,
            'cancel_after_decision_under_20ms': readings['decision_to_cancel_ms'] <= 20,
            'stop_cancel_under_20ms': readings['explicit_stop_to_cancel_ms'] <= 20,
            'localized_state_preserved': s.slots['origin'] == 'Chennai' and s.slots['date'] == '2026-09-15' and s.slots['destination'] == 'Mumbai',
            'no_write_calls': not any(o['effect'] == 'write' for o in s.operations.values())}
        return {'repetition': index, 'timing_ms': readings, 'checks': checks, 'passed': all(checks.values()), 'trace': s.trace}
    except Exception as exc:
        errors = [e['text'] for e in s.trace if e['type'] in ('provider_error','input_error')]
        return {'repetition': index, 'passed': False, 'error': type(exc).__name__,
                'reported_failure': errors[-1] if errors else 'Required controller event was not observed.', 'trace': s.trace}
    finally:
        await s.close()


async def main(count, use_model=False, interval=12, output=None):
    planner = ModelPlanner() if use_model else SlowPlanner()
    rows = []
    source = lambda: {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (ROOT/'thread_agent').glob('*.py')}
    target = ROOT/output if output else ROOT/'reports'/('theme5-responsiveness-actual-model.json' if use_model else 'theme5-responsiveness.json')
    report = {'format': 'THREAD controller wall-clock responsiveness v2', 'official_evaluation': False,
        'created_utc':datetime.now(timezone.utc).isoformat(),
        'model': settings()['model'] if use_model else 'scripted deterministic 400ms interpretation delay; not a provider latency claim',
        'inputs': 'Fresh-session text corrections and exact Stop commands; one authored correction phrasing, not language coverage.',
        'acoustic_output': 'not measured', 'expected_repetitions':count, 'cases':rows,
        'source_sha256_at_start':source(), 'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    def save():
        metrics = {}
        for name in ('coordination_ms', 'semantic_interpretation_ms', 'decision_to_cancel_ms', 'explicit_stop_to_cancel_ms'):
            values = sorted(row['timing_ms'][name] for row in rows if 'timing_ms' in row)
            metrics[name] = {'samples': len(values), 'p50': values[math.ceil(.5*len(values))-1], 'p95': values[math.ceil(.95*len(values))-1], 'maximum': max(values)} if values else {'samples': 0}
        attempts = [e for row in rows for e in row['trace'] if e['type']=='provider_attempt']
        report.update(metrics_ms=metrics, repetitions=len(rows), completed=len(rows)==count,
            passed=len(rows)==count and all(row['passed'] for row in rows),
            provider_attempts=len(attempts), failed_provider_attempts=sum(e['outcome']!='http_200' for e in attempts),
            source_sha256_at_report=source(), source_changed_during_run=report['source_sha256_at_start']!=source())
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(report,indent=2),encoding='utf-8')
    save()
    try:
        for i in range(count):
            rows.append(await repetition(i, planner))
            save()
            print(json.dumps({k: v for k, v in rows[-1].items() if k != 'trace'}), flush=True)
            if use_model and i+1 < count: await asyncio.sleep(interval)
    finally:
        if use_model: await planner.close()
        save()
    print(json.dumps({k: v for k, v in report.items() if k not in ('cases', 'source_sha256_at_start','source_sha256_at_report')}, indent=2))
    return report['passed']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repetitions', type=int, default=25)
    parser.add_argument('--actual-model', action='store_true', help='Call configured model instead of scripted delay. Consumes normal API quota.')
    parser.add_argument('--interval', type=float, default=12)
    parser.add_argument('--output',help='Separate result path for this attempt; prior reports remain untouched.')
    args = parser.parse_args()
    if not 20 <= args.repetitions <= 100: parser.error('Use 20 to 100 measured repetitions.')
    raise SystemExit(0 if asyncio.run(main(args.repetitions, args.actual_model, args.interval, args.output)) else 1)
