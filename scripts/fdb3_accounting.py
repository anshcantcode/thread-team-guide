"""Reconcile retained local experiment artifacts without counting response mirrors twice.

Observed totals are lower bounds: early failed requests did not all retain usage.
This does not estimate missing tokens, electric power, cost, or provider invoices.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import time
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def request_journal(path):
    """Last durable snapshot per attempt, never each journal line as a retry."""
    latest={}
    for line in path.read_text(encoding='utf-8',errors='replace').splitlines():
        try:
            body=json.loads(line)
            record=body.get('request',body)
            if not isinstance(record.get('request_id'),str):
                continue
            latest[record['request_id']]=record
        except (ValueError,AttributeError,TypeError):
            continue  # Raw trailing partial bytes remain on disk; do not invent usage.
    return list(latest.values())


def request_rows(body):
    if isinstance(body, list):
        for entry in body:  # Early independently authored protocol probes.
            if isinstance(entry,dict):
                record=entry.get('response', entry.get('native', {}))
                if isinstance(record,dict):
                    yield 'probe', record
        return
    if not isinstance(body,dict):
        return
    planner=body.get('model_requests', body.get('usage', []))
    if isinstance(planner,list):
        for entry in planner:
            if isinstance(entry,dict):
                yield 'planner', entry
    native = body.get('native_judge_calls', body.get('native_calls'))
    if native is not None:
        if isinstance(native,list):
            for entry in native:
                if isinstance(entry,dict):
                    yield 'judge', entry
    else:
        requests=body.get('judge_requests', body.get('raw', []))
        if isinstance(requests,list):
            for entry in requests:
                if isinstance(entry,dict):
                    yield 'judge', entry


def usage(entry):
    if isinstance(entry.get('usage'), dict):
        return entry['usage']
    native = entry.get('native_response', entry)
    if 'tokens_predicted' in native and 'tokens_evaluated' in native:
        return {'prompt_tokens': native['tokens_evaluated'],
                'completion_tokens': native['tokens_predicted']}
    return None


def reconcile(root):
    rows = []
    totals = Counter()
    candidates = set(root.glob('*/result.json')) | set(root.glob('*/evaluation.json'))
    candidates |= set(root.glob('*/case-*/inference/result.json')) | set(root.glob('*/case-*/evaluation.json'))
    candidates |= set(root.glob('*/case-*/latency.json')) | set(root.glob('*/latency.json'))
    candidates |= set(root.glob('live-controls*/*/result.json'))
    candidates |= set(root.glob('live-empty-stt*/*/result.json'))
    candidates |= set(root.glob('services-*/judge-controls.json'))
    candidates |= set(root.glob('native-*-controls*/*/result.json'))
    candidates |= set(root.glob('extension-*/verification.json')) | set(root.glob('extension-*/readback-diagnosis.json'))
    for pattern in ('*/case-*/inference/*-requests.jsonl','*/*-requests.jsonl',
                    '*/case-*/inference/tool-calls.jsonl','*/tool-calls.jsonl'):
        candidates.update(path.parent/'result.json' for path in root.glob(pattern))
    candidates |= set(root.glob('development*.json')) | set(root.glob('independent*.json'))
    candidates |= set(root.glob('*-control.json')) | set(root.glob('stt-*.json'))
    if (root/'developer-audio/provenance.json').exists():
        candidates.add(root/'developer-audio/provenance.json')
    for path in sorted(candidates):
        if 'source' in path.relative_to(root).parts:
            continue
        try:
            body = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
        except (OSError, ValueError):
            rows.append({'artifact': str(path.relative_to(root)), 'unreadable': True})
            if path.name!='result.json':
                continue
            body={}  # Recover durable attempts even if the final JSON was truncated.
        counts = Counter()
        if isinstance(body,dict) and path.name=='result.json':
            model_journal=path.parent/'model-requests.jsonl'
            if model_journal.exists():
                body['model_requests']=request_journal(model_journal)
            stt_journal=path.parent/'stt-requests.jsonl'
            if stt_journal.exists():
                body['stt_attempts']=request_journal(stt_journal)
            tts_journal=path.parent/'tts-requests.jsonl'
            if tts_journal.exists():
                body['tts_requests']=request_journal(tts_journal)
            tool_journal=path.parent/'tool-calls.jsonl'
            if tool_journal.exists():
                # The final report and its journal are mirrors, not extra calls.
                from thread_agent.fdb3_evidence import read_tool_journal
                tools=read_tool_journal(tool_journal)
                if 'actual_tool_calls' not in body:
                    body['actual_tool_calls']=tools['completed_invocations']
                    counts['possible_unconfirmed_tool_invocations']+=len(tools['possible_invocations'])
                counts['malformed_tool_journal_lines']+=tools['malformed_lines']
        for lane, entry in request_rows(body):
            counts[lane + '_attempt_records'] += 1
            counts['reported_inference_requests'] += entry.get('inference_requests', 1)
            observed = usage(entry)
            if observed is None:
                counts['attempts_without_token_usage'] += 1
            else:
                counts['observed_prompt_tokens'] += observed.get('prompt_tokens', 0)
                counts['observed_completion_tokens'] += observed.get('completion_tokens', 0)
            counts['cancelled_attempts'] += entry.get('outcome') == 'cancelled'
            counts['failed_attempts'] += entry.get('outcome') == 'error'
        if isinstance(body, dict):
            # A diagnostic may declare a count rather than individual requests.
            # Keep this separate from observed attempts/tokens; do not fabricate rows.
            if type(body.get('model_requests')) is int:
                counts['declared_model_requests_without_records'] += body['model_requests']
            counts['stt_result_records'] += len(body.get('input_transcripts', []))
            counts['stt_attempt_records'] += len(body.get('stt_attempts',[]))
            counts['stt_probe_requests'] += body.get('stt_requests',0)
            counts['output_asr_requests'] += body.get('output_asr_requests',0)
            counts['latency_input_asr_requests'] += body.get('input_asr_evidence',{}).get('request_count',0)
            synthesis=body.get('tts_requests', [])
            counts['tts_attempt_records'] += len(synthesis) if isinstance(synthesis,list) else synthesis
            counts['fixture_tts_attempt_records'] += len(body.get('fixture_tts_requests',[]))
            counts['actual_tool_invocations'] += len(body.get('actual_tool_calls', []))
            # Native verification/probes are additional attempts, not inference
            # trace mirrors. Transport shell commands are reported separately.
            native = body.get('verification_device_commands', body.get('device_calls', []))
            if not native and 'actual_tool_calls' not in body:
                native = body.get('device_commands', [])
            counts['native_diagnostic_tool_attempt_records'] += len(native)
            transport = body.get('device_transport', body.get('transport', body.get('commands', [])))
            if not isinstance(transport, list):
                transport = body.get('commands', [])
            counts['native_transport_command_records'] += len(transport)
            counts['observed_worker_cpu_seconds'] += body.get('worker_cpu_seconds', 0)
        totals.update(counts)
        rows.append({'artifact': str(path.relative_to(root)), **counts})
    return {'recorded_at': time.time(), 'paid_requests': 0, 'paid_spend_inr': 0,
            'scope': 'retained local artifacts; incomplete lower bounds, not total resource measurement',
            'unknown': ['Early timed-out/cancelled model requests lacked usage telemetry.',
                        'Early STT/TTS/worker CPU accounting was absent; missing is not zero.',
                        'GPU use, total server CPU, electricity, and retry totals are not fully measured.',
                        'Explicit repeated development probes are separate attempts, not qualification.',
                        'An active batch can add artifacts after this snapshot.'],
            'totals': dict(totals), 'artifacts': rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', type=Path, default=Path('.thread-run/raw'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = reconcile(args.raw)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result['totals']))
