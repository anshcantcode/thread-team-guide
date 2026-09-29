"""Fresh sequential zero-spend campaign. Local diagnostic, never qualification."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from thread_agent.fdb3_evidence import audio_duration_seconds, file_hash, read_tool_journal, upstream_window, verify_tool_trace


def atomic_json(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2), encoding="utf-8")
    os.replace(temp, path)


def evaluate_snapshot(snapshot, evaluator, metadata, result, destination, endpoint=None, model=None):
    """Run evaluator code and transport from the same immutable snapshot as inference."""
    command=[sys.executable,str(snapshot/'scripts/fdb3_evaluate.py'),
        '--upstream',str(evaluator),'--metadata',str(metadata),'--result',str(result),
        '--output',str(destination)]
    if endpoint:
        command.extend(['--judge-endpoint',endpoint,'--judge-identity',model])
    with destination.with_suffix('.log').open('w',encoding='utf-8') as log:
        try:
            child=subprocess.run(command,cwd=snapshot,stdout=log,stderr=subprocess.STDOUT,timeout=600)
        except subprocess.TimeoutExpired as exc:
            raise ValueError('Snapshot evaluator exceeded 600-second deadline') from exc
    if child.returncode:
        raise ValueError('Snapshot evaluator failed; retain its raw report/log')
    return json.loads(destination.read_text(encoding='utf-8'))


def latency_snapshot(snapshot, evaluator, result, audio, whisper, destination, endpoint=None, model=None):
    """Keep latency failures separate from correctness; never invent absent clocks."""
    command=[sys.executable,str(snapshot/'scripts/fdb3_latency.py'),
        '--upstream',str(evaluator),'--result',str(result),'--input-audio',str(audio),
        '--whisper',str(whisper.resolve()),'--output-asr-identity','local faster-whisper '+str(whisper.resolve()),
        '--output',str(destination)]
    if endpoint:
        command.extend(['--judge-endpoint',endpoint,'--judge-identity',model])
    with destination.with_suffix('.log').open('w',encoding='utf-8') as log:
        try:
            child=subprocess.run(command,cwd=snapshot,stdout=log,stderr=subprocess.STDOUT,timeout=180)
            exit_code=child.returncode
        except subprocess.TimeoutExpired:
            exit_code=124
    if not destination.exists():
        atomic_json(destination,{'status':'infrastructure_error','qualification_eligible':False,
            'error':'Latency child produced no report','exit_code':exit_code})
    report=json.loads(destination.read_text(encoding='utf-8'))
    status=report['status']
    if exit_code and status=='complete_diagnostic':
        status='infrastructure_error'
    return {'status':status,'exit_code':exit_code,'sha256':file_hash(destination)}


@contextmanager
def campaign_lock(state_dir):
    """Cover preparation as well as inference; never remove another owner's lock."""
    lock = state_dir / "campaign.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(descriptor, str(os.getpid()).encode())
    finally:
        os.close(descriptor)
    try:
        yield
    finally:
        if lock.exists() and lock.read_text() == str(os.getpid()):
            lock.unlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", required=True, type=Path)
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--whisper", required=True, type=Path)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8097/v1")
    parser.add_argument("--model", default="local-qwen")
    parser.add_argument("--model-file", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--manual", action="store_true")
    parser.add_argument("--local-judge", action="store_true")
    parser.add_argument("--unpaced", action="store_true", help="Explicit accelerated diagnostic, not comparable to realtime")
    parser.add_argument("--room", action="store_true", help="Loopback LiveKit WebRTC with automatic VAD")
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error("Limit must be between 1 and 100")
    if args.room and (args.manual or args.unpaced):
        parser.error("Room input requires automatic VAD and real-time pacing")
    assets, upstream = args.assets.resolve(), args.upstream.resolve()
    manifest = json.loads((assets / "dataset-manifest.json").read_text(encoding="utf-8"))
    if manifest["observed"] != 100 or len(manifest["recordings"]) != 100:
        parser.error("Incomplete dataset")
    for name, expected in manifest["contract_hashes"].items():
        if file_hash(assets / "agent-contract" / name) != expected:
            parser.error("Changed tool contract")
    state_dir = ROOT / ".thread-run"
    with campaign_lock(state_dir):
        return run_campaign(args, assets, upstream, manifest, state_dir)


def run_campaign(args, assets, upstream, manifest, state_dir):
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
    output = state_dir / "raw" / run_id
    output.mkdir()
    config = {k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()}
    sources = {str(p.relative_to(ROOT)): file_hash(p) for directory in ("participant", "thread_agent", "scripts")
               for p in (ROOT / directory).glob("*.py")}
    snapshot = output / "source"
    for relative in sources:
        destination = snapshot / relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT / relative,destination)
        if file_hash(destination)!=sources[relative]:
            raise ValueError('Source changed during snapshot creation')
    contract=output/'contract'
    contract.mkdir()
    for name in manifest['contract_hashes']:
        shutil.copyfile(assets/'agent-contract'/name,contract/name)
    evaluator=output/'evaluator'
    evaluator.mkdir()
    for name in ('evaluate_pass_rate.py','evaluate_tool_calls.py','analyze_tool_latency.py'):
        shutil.copyfile(upstream/'v3'/name,evaluator/name)
    shutil.copyfile(assets/'dataset-manifest.json',output/'dataset-manifest.json')
    identity = {"source_hashes":sources,"config":config,"model_sha256":file_hash(args.model_file),
                "planner_prompt_cache":os.environ.get("THREAD_FDB3_PROMPT_CACHE","0")=="1",
                "planner_guidance":int(os.environ.get("THREAD_FDB3_PLANNER_GUIDANCE","1")),
                "planner_follow_up":os.environ.get("THREAD_FDB3_FOLLOW_UP"),
                "planner_cache_scope":"scenario", "whisper_prompt":os.environ.get("THREAD_FDB3_WHISPER_PROMPT"), "planner_arg_normalize":os.environ.get("THREAD_FDB3_ARG_NORMALIZE","0")=="1",
                "dataset_manifest_sha256":file_hash(assets / "dataset-manifest.json"),
                "upstream_commit":manifest["upstream_commit"],
                "commit":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
                "dirty":bool(subprocess.check_output(["git","status","--porcelain"],cwd=ROOT,text=True)),
                "python":sys.version,"dependencies_sha256":file_hash(ROOT / "requirements-fdb3.lock"),
                "installed_packages":subprocess.check_output([sys.executable,'-m','pip','freeze','--all'],text=True).splitlines(),
                "whisper_assets":{str(p.relative_to(args.whisper)):file_hash(p) for p in args.whisper.rglob('*') if p.is_file()},
                "evaluator_hashes":{p.name:file_hash(p) for p in evaluator.iterdir()},
                "local_model_service":json.loads((state_dir / "raw/local-model-service.json").read_text(encoding="utf-8-sig"))}
    atomic_json(output / "identity.json",identity)
    report = {"run_id":run_id,"registered_at":time.time(),"status":"running","expected":100,
              "requested":args.limit,"cases":[],"qualification":False,"paid_requests":0,
              "judge":"local Qwen diagnostic" if args.local_judge else "disabled",
              "identity_sha256":file_hash(output / "identity.json")}
    atomic_json(output / "report.json",report)
    try:
        for index,row in enumerate(manifest["recordings"][:args.limit]):
            case_root = output / f"case-{index:03d}"
            case_root.mkdir()
            original = assets / "evaluator-data" / row["relative_path"]
            if file_hash(original) != row["sha256"]:
                raise ValueError("Input hash changed")
            audio = case_root / "input.wav"
            shutil.copyfile(original,audio)
            command = [sys.executable,str(snapshot / "scripts/fdb3_audio_worker.py"),"--audio",str(audio),
                       "--output",str(case_root / "inference"),"--contract",str(contract),
                       "--whisper",str(args.whisper.resolve()),"--endpoint",args.endpoint,"--model",args.model]
            if args.manual: command.append("--manual")
            if args.unpaced: command.append("--unpaced")
            if args.room: command.append("--room")
            started = time.time()
            with (case_root / "worker.log").open("w",encoding="utf-8") as log:
                try:
                    child = subprocess.run(command,cwd=assets / "agent-contract",stdout=log,stderr=subprocess.STDOUT,timeout=450)
                    exit_code = child.returncode
                except subprocess.TimeoutExpired:
                    exit_code = 124
            case = {"recording":row["recording"],"input_sha256":row["sha256"],"exit_code":exit_code,
                    "started_at":started,"finished_at":time.time(),"command":command,
                    "status":"infrastructure_error","strict_pass":False}
            result_path = case_root / "inference/result.json"
            try:
                if exit_code == 0 and result_path.is_file():
                    result = json.loads(result_path.read_text(encoding="utf-8"))
                    if result.get("status") != "completed" or result.get("input_sha256") != row["sha256"]:
                        raise ValueError("Incomplete or wrong-input inference")
                    verify_tool_trace(result.get('actual_tool_calls'),case_root/'inference/tool-calls.jsonl')
                    metadata_path=original.parent/'metadata.json'
                    if file_hash(metadata_path)!=row['metadata_sha256']:
                        raise ValueError('Evaluator metadata hash changed')
                    evaluation = evaluate_snapshot(snapshot,evaluator,metadata_path,result_path,case_root/'evaluation.json',
                        args.endpoint if args.local_judge else None,args.model_file.name if args.local_judge else None)
                    case.update(status="completed" if not evaluation.get("infrastructure_error") else "infrastructure_error",
                                strict_pass=evaluation["strict"]["passed"] is True and not evaluation.get("infrastructure_error"),failure_reason=evaluation["strict"]["failure_reason"],
                                result_sha256=file_hash(result_path),evaluation_sha256=file_hash(case_root / "evaluation.json"))
                    window=upstream_window(result,audio_duration_seconds(audio))
                    if window is None:
                        case['window_strict_pass']=None
                    elif not window['late_calls']:
                        case['window_strict_pass']=case['strict_pass']
                    else:
                        # Re-score on the calls the pinned upstream capture window would read.
                        windowed_path=case_root/'inference/result-window.json'
                        atomic_json(windowed_path,dict(result,actual_tool_calls=window['calls_in_window'],window_filtered=True))
                        windowed=evaluate_snapshot(snapshot,evaluator,metadata_path,windowed_path,case_root/'evaluation-window.json',
                            args.endpoint if args.local_judge else None,args.model_file.name if args.local_judge else None)
                        case['window_strict_pass']=windowed['strict']['passed'] is True and not windowed.get('infrastructure_error')
                    if window is not None:
                        case['upstream_window']={'late_calls':len(window['late_calls']),'late_call_seconds':window['late_call_seconds'],
                            'first_output_signal_in_window':window['first_output_signal_in_window'],'duration_seconds':window['duration_seconds']}
                    if args.room:
                        case['latency']=latency_snapshot(snapshot,evaluator,result_path,audio,args.whisper,
                            case_root/'latency.json',args.endpoint if args.local_judge else None,
                            args.model_file.name if args.local_judge else None)
                    else:
                        case['latency']={'status':'unavailable','reason':'Direct synthesis capture lacks real playout clock'}
            except (OSError,ValueError,KeyError,TypeError) as exc:
                case.update(status="infrastructure_error",strict_pass=False,error_type=type(exc).__name__,error=str(exc))
            journal=case_root/'inference/tool-calls.jsonl'
            if journal.is_file():
                case['tool_journal']={'sha256':file_hash(journal),**read_tool_journal(journal)}
            elif not result_path.is_file():
                case['tool_accounting']='unknown: no final result or durable journal; zero calls cannot be inferred'
            report["cases"].append(case)
            atomic_json(output / "report.json",report)
            print(json.dumps({"run_id":run_id,"case":index+1,"status":case["status"],"strict_pass":case["strict_pass"]}),flush=True)
        report.update(status="complete_diagnostic" if args.limit == 100 else "partial_diagnostic",
                      evaluated=sum(c["status"] == "completed" for c in report["cases"]),
                      strict_pass=sum(c["strict_pass"] for c in report["cases"]),
                      window_strict_pass=sum(c.get("window_strict_pass") is True for c in report["cases"]),
                      finished_at=time.time())
        atomic_json(output / "report.json",report)
    except BaseException as exc:
        report.update(status="aborted",error_type=type(exc).__name__,finished_at=time.time())
        atomic_json(output / "report.json",report)
        raise
    finally:
        with (state_dir / "experiments.jsonl").open("a",encoding="utf-8") as history:
            history.write(json.dumps({"run_id":run_id,"report":str(output.relative_to(ROOT) / "report.json"),
                "status":report["status"],"identity_sha256":report["identity_sha256"],"paid_requests":0})+"\n")
    print(output)
    # 2: incomplete inference/judging (never relabeled); 1: complete but not all pass; 0: all pass.
    if report.get("evaluated") != 100:
        return 2
    return 0 if report.get("strict_pass") == 100 else 1


if __name__ == "__main__":
    raise SystemExit(main())
