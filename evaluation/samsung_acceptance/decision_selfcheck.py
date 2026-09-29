"""Offline evidence-boundary controls through the real recorder and supervisor.

All candidate/harness code below is an authored fixture. Every HTTP call uses
MockTransport; there are no credentials or provider calls in these controls.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


PLANNER = r'''
import asyncio, json, os
from contextlib import nullcontext
import httpx

def planner_trace(observer): return nullcontext()
class Planner:
    client = None
    async def setup(self):
        async def reply(request):
            body = json.loads(request.content)
            mode = body['mode']
            await asyncio.sleep(.001)
            if mode == 'cancel':
                await asyncio.sleep(100)
            if mode == 'missing':
                raise httpx.ConnectError('authored failure')
            if mode == 'malformed_http':
                return httpx.Response(200, content=b'not JSON')
            if mode == 'embedding':
                return httpx.Response(200, json={'embedding': {'values': [0.6, 0.8]}})
            decision = {'observations': [{'type': 'image', 'message_index': 0,
                'visible_text': ['HDMI'], 'observation': 'printed label', 'uncertain': False}],
                'intent': 'fixture', 'slots': {'original': 'preserved'},
                'tool_calls': [{'api_name': 'undeclared', 'args': {},
                    'response_template': 'observed {title}', 'result_evidence': {
                        'path': 'title', 'contains': 'HDMI', 'target_basis': 'printed_text'},
                    'general_function': 'carries video',
                    'authorization': {'quote': 'Do this fixture action.'}}] if mode == 'rejected' else [],
                'clarification': None if mode == 'rejected' else 'Which target?', 'response': None,
                'nested': {'echo': os.environ['THREAD_API_KEY'], 'headers': {'private': 'HEADER_SENTINEL'},
                    'prompt': 'PROMPT_SENTINEL', 'inlineData': {'data': 'MEDIA_SENTINEL'}}}
            text = 'not a JSON decision' if mode == 'invalid' else json.dumps(decision)
            return httpx.Response(200, json={'modelVersion': 'gemini-3.5-flash-lite',
                'responseId': 'authored', 'usageMetadata': {'totalTokenCount': 1}, 'candidates': [
                    {'finishReason': 'STOP', 'content': {'parts': [
                        {'text': 'THOUGHT_SENTINEL', 'thought': True}, {'text': text}]}}]})
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
    async def _decide(self, context, record):
        response = await self.client.post('https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent',
            headers={'x-goog-api-key': os.environ['THREAD_API_KEY']}, json={'mode': context['mode'], 'prompt': 'REQUEST_PROMPT_SENTINEL'})
        record['status'] = response.status_code
        payload = response.json()
        decision = json.loads(payload['candidates'][0]['content']['parts'][1]['text'])
        if context['mode'] == 'validation':
            record['validation_error'] = 'authored native decision rejected'
            raise ValueError('authored validation failure')
        return decision
    async def plan(self, context):
        record = {'revision': context['revision'], 'request_id': str(context['revision']).zfill(32)}
        try:
            return await self._decide(context, record)
        except asyncio.CancelledError:
            record['status'] = 'cancelled'
            raise
        except ValueError:
            record['status'] = 'invalid_output'
            raise
        except httpx.HTTPError:
            record['status'] = 'transport_error'
            raise
    async def close(self): await self.client.aclose()
'''

AGENT = '''
class ParticipantAgent:
    def __init__(self, revision): self.revision = revision
    def _apply(self, decision):
        # A controller rejection is distinct from the provider's clarification.
        self.outcome = 'runtime_rejected' if decision.get('tool_calls') else 'model_clarified'
        decision['slots']['original'] = 'mutated after capture'
        if decision.get('observations'):
            decision['observations'][0]['visible_text'][0] = 'MUTATED'
'''

EMBEDDING = '''
async def embed_image(client):
    evidence = {'input_sha256': 'authored-image-hash', 'status': 'pending'}
    response = await client.post('https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:embedContent', json={'mode': 'embedding'})
    values = response.json()['embedding']['values']
    evidence.update(status='success', dimensions=2, norm=1.0)
    return {'values': values, 'evidence': evidence}
'''

EVALUATOR = '''
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from participant.planner import Planner
from participant.agent import ParticipantAgent
from participant.embedding import embed_image

def run_once(scenario, cls, time_scale, wall_cap_s, setup_cap_s):
    trace = []
    async def go():
        planner = Planner()
        await planner.setup()
        try:
            context = {'mode': scenario['mode'], 'revision': scenario['revision']}
            if context['mode'] == 'cancel':
                task = asyncio.create_task(planner.plan(context))
                await asyncio.sleep(.01)
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                return
            try:
                decision = await planner.plan(context)
            except Exception:
                decision = {'slots': {}, 'clarification': 'runtime fallback'}
            agent = ParticipantAgent(context['revision'])
            agent._apply(decision)
            trace.append({'kind': 'fixture', 'outcome': agent.outcome, 't_ms': 0})
            if context['mode'] == 'clarification':
                embedded = await embed_image(planner.client)
                embedded['values'][0] = 99  # Captured returned vector must stay intact.
        finally:
            await planner.close()
    asyncio.run(go())
    return {'scenario_id': scenario['scenario_id'], 'total': 0, 'breakdown': {}}
for path in sorted((Path(__file__).parent / 'scenarios').glob('*.json')):
    run_once(json.loads(path.read_text()), None, 1, 120, 300)
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    modes = ('clarification', 'rejected', 'validation', 'invalid', 'malformed_http', 'cancel', 'missing')
    with tempfile.TemporaryDirectory(prefix='decision-control-') as folder:
        root = Path(folder)
        kit, candidate = root / 'kit', root / 'candidate'
        (kit / 'harness').mkdir(parents=True)
        (kit / 'scenarios').mkdir()
        (candidate / 'participant').mkdir(parents=True)
        for path in (kit / 'harness/__init__.py', candidate / 'participant/__init__.py'):
            path.write_text('')
        (kit / 'harness/mock_env.py').write_text('TOOL_REGISTRY = {}\n')
        (kit / 'submission.yaml').write_text('authored fixture\n')
        (candidate / 'PACKAGE_MANIFEST.json').write_text('{"source_git_revision":"authored-decision-fixture"}')
        for name, code in {'planner': PLANNER, 'agent': AGENT, 'embedding': EMBEDDING}.items():
            (candidate / 'participant' / (name + '.py')).write_text(code)
        (kit / 'eval_submission.py').write_text(EVALUATOR)
        for index, mode in enumerate(modes):
            (kit / 'scenarios' / f'{index}-{mode}.json').write_text(json.dumps(
                {'scenario_id': mode, 'mode': mode, 'revision': index + 1, 'events': [], 'ground_truth': {}}))
        env = dict(os.environ)
        for name in ('SECRET_GEMINI_API_KEY', 'THREAD_API_KEY', 'GEMINI_API_KEY', 'GOOGLE_API_KEY'):
            env[name] = 'OFFLINE-CREDENTIAL-SENTINEL'
        command = [sys.executable, '-B', '-m', 'evaluation.samsung_acceptance.run', '--out', str(args.out / 'supervised'),
            '--wall-seconds', '15', '--', '--submission', str(candidate), '--kit', str(kit), '--reference-kit', str(kit),
            '--scenarios', str(kit / 'scenarios'), '--mode', 'real-provider', '--reps', '1', '--decision-evidence',
            '--max-generation-requests', '7', '--max-embedding-requests', '1', '--cap-generation-model', 'gemini-3.5-flash-lite']
        process = subprocess.run(command, env=env, capture_output=True, timeout=20)
        (args.out / 'launcher.stdout').write_bytes(process.stdout)
        (args.out / 'launcher.stderr').write_bytes(process.stderr)
        run = args.out / 'supervised/run'
        manifest = json.loads((run / 'manifest.json').read_text())
        assert process.returncode == 0, (process.returncode, manifest.get('wrapper_error'))
        assert manifest['sources_unchanged'] and not manifest['decision_observer_errors']
        assert not manifest['observer_errors'] and not manifest['transport_observer_errors']
        assert manifest['request_budget']['admitted_starts'] == {'generation': 7, 'embedding': 1}
        rows = {mode: json.loads((run / f'attempt-{index:03d}-{mode}.json').read_text()) for index, mode in enumerate(modes, 1)}
        for mode, row in rows.items():
            evidence = row['decision_evidence']
            assert len([r for r in evidence if r['stage'] == 'provider_response']) == 1, mode
            assert len([r for r in evidence if r['stage'] == 'planner_return']) == 1, mode
            assert all(r['transport'] == 'MockTransport' for r in row['transport_requests'])
            provider = next(r for r in evidence if r['stage'] == 'provider_response')
            planner = next(r for r in evidence if r['stage'] == 'planner_return')
            if mode in {'cancel', 'missing'}:
                assert provider['provider_response']['state'] == 'absent'
                assert planner['return_state'] == 'no_return_value'
            elif mode == 'malformed_http':
                assert provider['provider_response']['state'] == 'invalid_json'
            else:
                candidate_row = provider['provider_response']['candidates'][0]
                assert candidate_row['decision_state'] == ('invalid_json' if mode == 'invalid' else 'parsed_json')
                assert provider['request_body_sha256'] == row['transport_requests'][0]['body_sha256']
            if mode == 'validation':
                assert provider['runtime_metadata']['validation_error']
            if mode in {'clarification', 'rejected'}:
                applied = next(r for r in evidence if r['stage'] == 'controller_apply')
                native = provider['provider_response']['candidates'][0]['native_decision']
                for decision in (native, planner['value'], applied['decision']):
                    assert decision['slots']['original'] == 'preserved'
                    assert decision['observations'][0]['visible_text'] == ['HDMI']
                    assert decision['observations'][0]['uncertain'] is False
                    assert decision['nested'] == {'echo': '[credential removed]'}
                assert bool(native['tool_calls']) == (mode == 'rejected')
                assert row['trace'][0]['outcome'] == ('runtime_rejected' if mode == 'rejected' else 'model_clarified')
        embedded = next(r for r in rows['clarification']['decision_evidence'] if r['stage'] == 'embedding_return')
        assert embedded['value']['values'] == embedded['provider_response']['embedding_values'] == [0.6, 0.8]
        for path in run.glob('*.json'):
            content = path.read_text()
            assert all(marker not in content for marker in ('OFFLINE-CREDENTIAL-SENTINEL', 'HEADER_SENTINEL',
                'PROMPT_SENTINEL', 'MEDIA_SENTINEL', 'THOUGHT_SENTINEL', 'MUTATED', 'mutated after capture'))
        report = {'passed': True, 'real_provider_calls': 0, 'controls': list(modes), 'actual_mock_starts': 8,
                  'immutable_snapshots': True, 'credentials_private_fields_and_thoughts_omitted': True,
                  'raw_returned_unused_embedding_preserved': True}
        (args.out / 'checks.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report))


if __name__ == '__main__':
    main()
