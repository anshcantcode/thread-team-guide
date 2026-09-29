"""Five released recordings through Linux AgentServer dispatch; local diagnostic only.

The unchanged upstream LiveKit client retains its input-length capture window.
Output ASR uses the selected pinned CUDA Whisper model, NOT upstream NeMo.
No benchmark controller or official evaluator implementation is changed.
"""
import argparse
import asyncio
from contextlib import contextmanager
import hashlib
import json
import math
import os
import re
from pathlib import Path
import signal
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.fdb3_config import apply_environment, load_config, verify_whisper


def digest(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temporary.replace(path)


def select_recordings(manifest):
    rows = manifest['recordings']
    if manifest['observed'] != 100 or len(rows) != 100 or len({r['recording'] for r in rows}) != 100:
        raise ValueError('Require a complete, unique 100-recording manifest before selecting five')
    return sorted(rows, key=lambda row: row['recording'])[:5]


def call_sequence(calls):
    # Compare every call, in order, including duplicates and failed effects.
    # Ignore only run-specific clocks/IDs/results; never normalize arguments.
    return [{'function': call['function'], 'args': call['args']} for call in calls]


def require_judged_evaluation(evaluation):
    calls = evaluation.get('native_judge_calls', [])
    if (evaluation.get('infrastructure_error') or evaluation.get('status') != 'completed'
            or evaluation.get('judge_enabled') is not True or not calls
            or len(calls) != len(evaluation.get('judge_requests', []))
            or any(call.get('outcome') != 'success' or call.get('inference_requests') != 1
                   or call.get('native_response', {}).get('truncated') is True
                   or call.get('native_response', {}).get('stop_type') == 'limit' for call in calls)):
        raise ValueError('Missing/failed/malformed/truncated judge receipts are not a pass')


def compare_reference(report, output, reference):
    baseline = json.loads((reference / 'report.json').read_text(encoding='utf-8'))
    identity = json.loads((reference / 'identity.json').read_text(encoding='utf-8'))
    if baseline.get('identity_sha256') != digest(reference / 'identity.json'):
        raise ValueError('Windows report identity hash does not match its identity file')
    if identity['commit'] != load_config()['windows_reference_source']:
        raise ValueError('Wrong Windows reference source; expected run #3 f6329dd')
    if baseline['status'] != 'complete_diagnostic' or len(baseline['cases']) != 100:
        raise ValueError('Windows run #3 has not completed; do not compare a partial report')
    by_recording = {case['recording']: (index, case) for index, case in enumerate(baseline['cases'])}
    comparisons = []
    for case in report['cases']:
        index, original = by_recording[case['recording']]
        if case['input_sha256'] != original['input_sha256']:
            raise ValueError('Linux/Windows input hash mismatch')
        windows_path = reference / f'case-{index:03d}/inference/result.json'
        linux_path = output / case['directory'] / 'result.json'
        if original.get('result_sha256') != digest(windows_path):
            raise ValueError('Windows inference is missing its verified result hash')
        windows = json.loads(windows_path.read_text(encoding='utf-8'))
        linux = json.loads(linux_path.read_text(encoding='utf-8'))
        if windows.get('status') != 'completed' or linux.get('status') != 'completed':
            raise ValueError('Incomplete inference is not a valid tool-call comparison')
        left, right = call_sequence(windows['actual_tool_calls']), call_sequence(linux['actual_tool_calls'])
        comparisons.append({'recording': case['recording'], 'input_sha256': case['input_sha256'],
            'windows': left, 'linux': right, 'ordered_calls_equal': left == right,
            'windows_result_sha256': digest(windows_path), 'linux_result_sha256': digest(linux_path),
            'windows_strict_pass': original['strict_pass'], 'linux_strict_pass': case.get('strict_pass')})
    return {'status': 'COMPARED', 'exact_ordered_matches': sum(c['ordered_calls_equal'] for c in comparisons),
        'count': len(comparisons), 'reference_report_sha256': digest(reference / 'report.json'),
        'reference_identity_sha256': digest(reference / 'identity.json'), 'cases': comparisons,
        'limitations': ['Different controller source: f6329dd versus exported candidate.',
            'Linux espeak-ng versus Windows SAPI; different SDK job/capture lifecycle.',
            'Linux uses the unchanged upstream input-length audio capture; Windows has a longer settling window.',
            'All terminal tool calls retained; this is diagnostic comparison, not qualification or equivalence proof.']}


@contextmanager
def owned_process(command, log, env):
    with log.open('w', encoding='utf-8') as handle:
        process = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT,
                                   env=env, cwd=log.parent, start_new_session=True)
        try:
            yield process
        finally:
            # These groups were created by this process; never name-kill services.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            else:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    process.poll()  # Reap the group leader, if already exited.
                    try:
                        os.killpg(process.pid, 0)
                    except ProcessLookupError:
                        break
                    time.sleep(.2)
                else:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            if process.poll() is None:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    raise RuntimeError('Owned process did not exit; inspect its PID before another GPU run')


def wait_health(process, port, seconds=120, path='/'):
    deadline = time.monotonic() + seconds
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'Owned service {port} exited; retain its log')
        try:
            with opener.open(f'http://127.0.0.1:{port}{path}', timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(.5)
    raise TimeoutError(f'Owned service {port} readiness exceeded {seconds}s')


def wait_session(journals, room, status, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        for path in journals.glob('*.session.json'):
            value = json.loads(path.read_text(encoding='utf-8'))
            if value['room'] == room and value['status'] == status:
                return value
        time.sleep(.2)
    raise TimeoutError(f'AgentServer never produced {status} receipt for owned room')


async def dispatch_room(room, delete=False):
    from livekit import api
    client = api.LiveKitAPI(url='http://127.0.0.1:7980', api_key='devkey', api_secret='secret')
    try:
        if delete:
            await client.room.delete_room(api.DeleteRoomRequest(room=room))
        else:
            await client.room.create_room(api.CreateRoomRequest(name=room, empty_timeout=180))
            dispatch = await client.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(room=room, agent_name='thread-fdb3-task-b'))
            return dispatch.id
    finally:
        await client.aclose()


def decode_output(whisper, audio, output):
    selected = verify_whisper(whisper)
    from thread_agent.fdb3_voice import WhisperSTT, trim_trailing_silence
    recognizer = WhisperSTT(whisper)
    samples, trimmed = trim_trailing_silence(audio)
    text, chunks = recognizer.transcribe(samples, filter_silence=True)
    if not text.strip():
        raise ValueError('No recognized captured speech; cannot claim completed inference')
    save(output, {'transcript': text, 'asr_chunks': chunks, 'trimmed_trailing_seconds': trimmed,
                  'output_asr': f"faster-whisper {selected['name']} {recognizer.device}/{recognizer.compute_type}; NOT NeMo",
                  'whisper': selected})


def run_case(index, row, args, output, env):
    from thread_agent.fdb3_evidence import verify_tool_trace
    case_dir = output / f'case-{index:03d}'
    case_dir.mkdir()
    case = {'recording': row['recording'], 'input_sha256': row['sha256'],
            'directory': case_dir.name, 'status': 'infrastructure_error', 'strict_pass': False}
    original = args.assets / 'evaluator-data' / row['relative_path']
    metadata = original.parent / 'metadata.json'
    if digest(original) != row['sha256'] or digest(metadata) != row['metadata_sha256']:
        raise ValueError('Input or evaluator metadata changed after preregistration')
    shutil.copyfile(original, case_dir / 'input.wav')
    journals = case_dir / 'journals'
    journals.mkdir()
    room = 'thread-smoke-' + uuid.uuid4().hex
    case_env = dict(env, THREAD_FDB3_JOURNAL_DIR=str(journals),
                    THREAD_FDB3_TELEMETRY=str(case_dir / 'collector.jsonl'))
    try:
        with owned_process([sys.executable, str(ROOT / 'scripts/fdb3_agent.py'), 'start'],
                           case_dir / 'agent.log', case_env) as agent:
            wait_health(agent, 8181)
            case['dispatch_id'] = asyncio.run(dispatch_room(room))
            try:
                wait_session(journals, room, 'ready')
                command = [sys.executable, str(output / 'evaluator/livekit_inference.py'),
                           '--input', str(case_dir / 'input.wav'), '--output', str(case_dir / 'spoken.wav'),
                           '--room', room]
                # Client cwd has no .env.local. No inherited credentials activate billing.
                with (case_dir / 'client.log').open('w', encoding='utf-8') as log:
                    subprocess.run(command, env=case_env, cwd=case_dir, stdout=log,
                                   stderr=subprocess.STDOUT, check=True,
                                   timeout=math.ceil(row['duration_seconds']) + 90)
            finally:
                asyncio.run(dispatch_room(room, delete=True))
            receipt = wait_session(journals, room, 'closed', seconds=45)
        save(case_dir / 'session-receipt.json', receipt)
        successes = [r for r in receipt['model_requests'] if r['outcome'] == 'success']
        if (receipt['errors'] or receipt['whisper_device'] != 'cuda' or receipt['compute_type'] != 'float16'
                or not receipt['input_transcripts'] or not successes
                or any(r['outcome'] not in {'success', 'cancelled'} for r in receipt['model_requests'])
                or any(not r.get('cache_prompt') or r.get('cache_boundary_overlap') for r in successes)
                or any(r['outcome'] != 'success' for r in receipt['stt_attempts'])):
            raise ValueError('AgentSession failed or did not exercise CUDA ASR and the planner')
        verify_tool_trace(receipt['actual_tool_calls'], Path(receipt['tool_journal']))
        collector = case_dir / 'collector.jsonl'
        collected = [json.loads(line)['call'] for line in collector.read_text().splitlines()] if collector.exists() else []
        if collected != receipt['actual_tool_calls']:
            raise ValueError('Terminal collector and agent call journal disagree')
        with (case_dir / 'output-asr.log').open('w', encoding='utf-8') as log:
            subprocess.run([sys.executable, str(Path(__file__).resolve()), '--decode-output',
                '--whisper', str(args.whisper), '--audio', str(case_dir / 'spoken.wav'),
                '--output', str(case_dir / 'output-asr.json')], env=env, stdout=log,
                stderr=subprocess.STDOUT, check=True, timeout=90)
        speech = json.loads((case_dir / 'output-asr.json').read_text())
        result = dict(speech, status='completed', input_sha256=row['sha256'],
                      actual_tool_calls=receipt['actual_tool_calls'], room=room,
                      transport='AgentServer explicit dispatch + unchanged upstream WebRTC client',
                      capture_window='upstream input-duration audio; all terminal calls retained',
                      qualification=False)
        save(case_dir / 'result.json', result)
        with (case_dir / 'evaluation.log').open('w', encoding='utf-8') as log:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fdb3_evaluate.py'),
                '--upstream', str(output / 'evaluator'), '--metadata', str(metadata),
                '--result', str(case_dir / 'result.json'), '--output', str(case_dir / 'evaluation.json'),
                '--judge-endpoint', 'http://127.0.0.1:8197/v1', '--judge-identity', load_config()['model']['name']],
                env=env, cwd=case_dir, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
        evaluation = json.loads((case_dir / 'evaluation.json').read_text())
        require_judged_evaluation(evaluation)
        case.update(status='completed', strict_pass=evaluation['strict']['passed'] is True,
                    result_sha256=digest(case_dir / 'result.json'),
                    evaluation_sha256=digest(case_dir / 'evaluation.json'))
    except Exception as exc:
        case.update(error_type=type(exc).__name__, error=str(exc))
    return case


def run(args):
    config = load_config()
    apply_environment()
    output = args.output.resolve()
    output.mkdir(parents=False, exist_ok=False)
    report = {'status': 'started', 'expected': 5, 'qualification': False, 'paid_requests': 0,
              'full_benchmark': False, 'judge_mode': 'local', 'judge_identity': config['model']['name'],
              'official_latency': False, 'cases': [],
              'selection_rule': 'first five unique recording IDs, lexicographically sorted'}
    save(output / 'report.json', report)
    try:
        manifest = json.loads((args.assets / 'dataset-manifest.json').read_text())
        if manifest['upstream_commit'] != config['upstream_commit'] or manifest['archive_sha256'] != config['archive_sha256']:
            raise ValueError('Prepared assets do not match candidate upstream/archive')
        selected = select_recordings(manifest)
        save(output / 'selection.json', selected)  # Written before any service or inference.
        if digest(args.model) != config['model']['sha256']:
            raise ValueError('Wrong planner model')
        whisper_identity = verify_whisper(args.whisper, config=config)
        (output / 'contract').mkdir()
        (output / 'evaluator').mkdir()
        for name, expected in manifest['contract_hashes'].items():
            if digest(args.assets / 'agent-contract' / name) != expected:
                raise ValueError('Changed public contract')
            shutil.copyfile(args.assets / 'agent-contract' / name, output / 'contract' / name)
        upstream_commit = subprocess.check_output(['git', '-C', str(args.upstream), 'rev-parse', 'HEAD'], text=True).strip()
        if upstream_commit != config['upstream_commit']:
            raise ValueError('Wrong upstream checkout')
        for name in ('evaluate_pass_rate.py', 'evaluate_tool_calls.py', 'analyze_tool_latency.py', 'livekit_inference.py'):
            source = args.upstream / 'v3' / name
            pinned = subprocess.check_output(['git', '-C', str(args.upstream), 'show', f'{upstream_commit}:v3/{name}'])
            # Worktree line-ending checkout is not a scoring-source modification.
            if source.read_bytes().replace(b'\r\n', b'\n') != pinned.replace(b'\r\n', b'\n'):
                raise ValueError('Modified upstream source: ' + name)
            shutil.copyfile(source, output / 'evaluator' / name)
        for port in (8197, 7980, 7981, 8181):
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', port))
        env = dict(os.environ, LIVEKIT_URL='ws://127.0.0.1:7980', LIVEKIT_API_KEY='devkey',
            LIVEKIT_API_SECRET='secret', THREAD_FDB3_ENDPOINT='http://127.0.0.1:8197/v1',
            THREAD_FDB3_MODEL='local-qwen', THREAD_FDB3_CONTRACT=str(output / 'contract'),
            THREAD_FDB3_WHISPER=str(args.whisper), THREAD_FDB3_CACHE_OWNER_FILE=str(output / 'cache-owner'),
            THREAD_FDB3_AGENT_NAME='thread-fdb3-task-b', THREAD_AGENT_PORT='8181',
            THREAD_FDB3_TTS_COMMAND='["espeak-ng","-w","{output}","-f","{text_file}"]',
            THREAD_FDB3_TTS_PROFILE='espeak-ng', OPENAI_API_KEY='local-no-billing',
            OPENAI_BASE_URL='http://127.0.0.1:8197/v1')
        (output / 'slots').mkdir()
        planner_command = [str(args.llama_server), '-m', str(args.model), '--host', '127.0.0.1',
            '--port', '8197', *config['llama']['args'], '--slot-save-path', str(output / 'slots'),
            # b10930 maps backend INFO/offload receipts to TRACE (verbosity 4).
            # Observability only: keep all measured model/sampling flags intact.
            '-lv', '4']
        report['identity'] = {'source': json.loads((ROOT / 'source-identity.json').read_text()),
            'candidate_sha256': digest(ROOT / 'config/fdb3-candidate.json'),
            'dataset_manifest_sha256': digest(args.assets / 'dataset-manifest.json'),
            'planner_command': planner_command, 'llama_binary_sha256': digest(args.llama_server),
            'environment': config['environment'], 'upstream_commit': upstream_commit,
            'whisper': whisper_identity,
            'evaluator_sha256': {p.name: digest(p) for p in (output / 'evaluator').iterdir()}}
        build_identity = args.llama_server.parents[2] / 'build-identity.json'
        report['identity']['llama_build'] = json.loads(build_identity.read_text())
        report['identity']['llama_build_receipt_sha256'] = digest(build_identity)
        if (report['identity']['llama_build']['llama_binary_sha256'] != digest(args.llama_server)
                or report['identity']['llama_build']['llama_source_commit'] != config['llama']['commit']):
            raise ValueError('Planner build receipt does not bind the pinned source and actual binary')
        save(output / 'report.json', report)
        with owned_process(planner_command, output / 'planner.log', env) as planner:
            wait_health(planner, 8197, path='/health')
            offload = re.search(r'offloaded (\d+)/(\d+) layers to GPU', (output / 'planner.log').read_text())
            if not offload or int(offload.group(1)) <= 0 or offload.group(1) != offload.group(2):
                raise ValueError('Planner log does not confirm full GPU offload; CPU fallback is not this candidate')
            report['gpu_after_planner_start'] = subprocess.check_output([
                'nvidia-smi', '--query-gpu=name,memory.total,memory.used,memory.free',
                '--format=csv,noheader'], text=True).strip()
            save(output / 'report.json', report)
            with owned_process([str(args.livekit_server), '--dev', '--bind', '127.0.0.1',
                    '--node-ip', '127.0.0.1', '--port', '7980', '--rtc.tcp_port', '7981'],
                    output / 'livekit.log', env) as livekit:
                wait_health(livekit, 7980, seconds=30)
                for index, row in enumerate(selected):
                    report['cases'].append(run_case(index, row, args, output, env))
                    save(output / 'report.json', report)
        report.update(status='complete_smoke', evaluated=sum(c['status'] == 'completed' for c in report['cases']),
                      strict_pass=sum(c['strict_pass'] for c in report['cases']))
        try:
            comparison = compare_reference(report, output, args.reference)
            save(output / 'windows-comparison.json', comparison)
            report['comparison'] = {'status': comparison['status'], 'exact_ordered_matches': comparison['exact_ordered_matches']}
        except (OSError, KeyError, ValueError) as exc:
            report['comparison'] = {'status': 'BLOCKED', 'reason': str(exc)}
        if report['evaluated'] != 5 or report['comparison']['status'] != 'COMPARED':
            return 2
        return 0 if report['strict_pass'] == 5 else 1
    except BaseException as exc:
        report.update(status='infrastructure_error', error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        save(output / 'report.json', report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--decode-output', action='store_true')
    for name in ('assets', 'upstream', 'whisper', 'model', 'llama-server', 'livekit-server', 'reference', 'audio'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if sys.platform != 'linux':
        parser.error('Only run this probe in Linux during the granted phase-2 slot')
    if args.decode_output:
        if not args.whisper or not args.audio:
            parser.error('Output ASR requires --whisper and --audio')
        decode_output(args.whisper, args.audio, args.output)
        return 0
    if any(getattr(args, name) is None for name in ('assets', 'upstream', 'whisper', 'model', 'llama_server', 'livekit_server', 'reference')):
        parser.error('Smoke requires all resource paths and the read-only Windows reference')
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    return run(args)


if __name__ == '__main__':
    raise SystemExit(main())
