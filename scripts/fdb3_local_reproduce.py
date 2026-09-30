"""Owned zero-spend reproduction entrypoint; explicit external prerequisites.

Windows uses the SAPI development speech profile unless THREAD_FDB3_TTS_COMMAND
names a local synthesizer argv; other systems require that command (for example
espeak-ng or piper). This provisions a local environment and fresh diagnostic,
not Samsung's hosted environment. It never reads .env, starts cloud services, or
changes owner services. Exit 2 means incomplete inference/judging, 1 a complete
run that is not 100/100, 0 all pass.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import uuid
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from thread_agent.fdb3_evidence import file_hash
from scripts.fdb3_config import load_config


def model_arguments(config):
    """Keep the Windows diagnostic profile explicit, with the shared release seed."""
    seed = load_config()['llama']['seed']
    if 'seed' in config and (type(config['seed']) is not int or config['seed'] != seed):
        raise ValueError('Candidate drift: local reproduction seed must match the release seed')
    return ['-m', config['model_file'], '--host', '127.0.0.1', '--port', '8097',
            '--ctx-size', str(config.get('ctx_size', 4096)), '--parallel', '1',
            '--reasoning', 'off', '--skip-chat-parsing',
            '--gpu-layers', str(config.get('gpu_layers', 0)), '--cache-ram', '0',
            '--batch-size', '128', '--ubatch-size', '64', '--threads', '4',
            '--seed', str(seed)]


def validate(config):
    if config.get('budget_inr') != 0:
        raise ValueError('This entrypoint supports only the authorized zero-spend local lane')
    for key in ('model_file','whisper','llama_server','livekit_server','archive','upstream'):
        path=Path(config.get(key,''))
        if not path.exists() or not str(config.get(key,'')):
            raise ValueError(f'Missing {key}: supply its existing local path in the configuration')
    model_arguments(config)
    if not (Path(config['upstream'])/'v3/evaluate_pass_rate.py').is_file():
        raise ValueError('The upstream path must contain the pinned FDB v3 checkout')
    if shutil.which('ffmpeg') is None:
        raise ValueError('Install ffmpeg and place it on PATH')


def wait_ready(port, process, seconds=60, http_path=None):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        if process.poll() is not None:
            raise RuntimeError(f'Owned service exited before readiness on port {port}; inspect its log')
        try:
            with socket.create_connection(('127.0.0.1',port),timeout=.5):
                if http_path is None:
                    return
            with urllib.request.urlopen(f'http://127.0.0.1:{port}{http_path}',timeout=.5) as response:
                if response.status==200:
                    return
        except OSError:
            time.sleep(.25)
    raise TimeoutError(f'Owned service readiness timeout on port {port}')


def environment_path(fresh_environment=None):
    if fresh_environment is None:
        return ROOT/'.venv-fdb3'
    path = (ROOT/fresh_environment).resolve()
    if (not path.is_relative_to(ROOT.resolve()) or path == ROOT.resolve()
            or path.exists()):
        raise ValueError('Fresh environment must be a new directory inside this worktree')
    return path


def run(config, limit, fresh_environment=None):
    if sys.version_info[:2]!=(3,11):
        raise RuntimeError('The pinned lock targets Python 3.11')
    if os.name!='nt' and not os.environ.get('THREAD_FDB3_TTS_COMMAND'):
        raise RuntimeError('Set THREAD_FDB3_TTS_COMMAND to a local synthesizer argv (JSON) on this OS')
    validate(config)
    if (ROOT/'.thread-run/campaign.lock').exists():
        raise RuntimeError('A campaign lock exists; inspect its PID and report before resuming')
    for port in (7880,8097):
        with socket.socket() as probe:
            try: probe.bind(('127.0.0.1',port))
            except OSError as exc: raise RuntimeError(f'Port {port} is occupied; existing owner service will not be stopped') from exc
    environment=environment_path(fresh_environment)
    python=environment/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if not python.exists():
        subprocess.run([sys.executable,'-m','venv',str(environment)],check=True)
    subprocess.run([str(python),'-m','pip','install','-r',str(ROOT/'requirements-fdb3.lock')],check=True)
    subprocess.run([str(python),'-m','pip','check'],check=True)
    assets=ROOT/'.runtime/fdb-assets'
    if not assets.exists():
        subprocess.run([str(python),str(ROOT/'scripts/fdb3_prepare.py'),'--archive',config['archive'],
            '--upstream',config['upstream'],'--destination',str(assets)],check=True)
    manifest=json.loads((assets/'dataset-manifest.json').read_text())
    if file_hash(config['archive'])!=manifest['archive_sha256']:
        raise ValueError('Configured archive does not match the prepared dataset')
    run_tag='services-'+uuid.uuid4().hex[:12]
    logs=ROOT/'.thread-run/raw'/run_tag
    logs.mkdir(parents=True)
    owned=[]; handles=[]
    def launch(command, name):
        handle=(logs/(name+'.log')).open('w',encoding='utf-8'); handles.append(handle)
        process=subprocess.Popen(command,cwd=ROOT,stdout=handle,stderr=subprocess.STDOUT,
            **({'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True}))
        owned.append(process)
        return process
    try:
        model_args=model_arguments(config)
        if config.get('prompt_cache'):
            # Required for the per-scenario slot erase; nothing is ever saved to it.
            slots=logs/'slots'; slots.mkdir()
            model_args+=['--slot-save-path',str(slots)]
        model=launch([config['llama_server'],*model_args],'model')
        # TCP alone is insufficient: keep waiting through loading HTTP 503s.
        wait_ready(8097,model,http_path='/health')
        livekit=launch([config['livekit_server'],'--dev','--bind','127.0.0.1','--node-ip','127.0.0.1'],'livekit')
        wait_ready(7880,livekit)
        service={'pid':model.pid,'arguments':model_args,'model_path':config['model_file'],
            'server_sha256':file_hash(config['llama_server']),'livekit_sha256':file_hash(config['livekit_server']),
            'started_at':time.time(),'paid_requests':0}
        (ROOT/'.thread-run/raw/local-model-service.json').write_text(json.dumps(service,indent=2),encoding='utf-8')
        subprocess.run([str(python),str(ROOT/'scripts/fdb3_judge_probe.py'),'--upstream',str(Path(config['upstream'])/'v3'),
            '--output',str(logs/'judge-controls.json')],check=True,cwd=ROOT)
        # Planner prefix reuse is part of the declared candidate configuration.
        os.environ['THREAD_FDB3_PROMPT_CACHE']='1' if config.get('prompt_cache') else '0'
        command=[str(python),str(ROOT/'scripts/fdb3_run.py'),'--assets',str(assets),'--upstream',config['upstream'],
            '--whisper',config['whisper'],'--model-file',config['model_file'],'--room','--local-judge','--limit',str(limit)]
        campaign=launch(command,'campaign')
        return campaign.wait()
    finally:
        for process in reversed(owned):
            if process.poll() is None:
                # Only processes created in this invocation, including their
                # worker children. Never locate/kill arbitrary same-name servers.
                if os.name=='nt':
                    subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
                else:
                    import signal
                    try: os.killpg(process.pid,signal.SIGTERM)
                    except ProcessLookupError: pass
                process.wait(timeout=15)
        for handle in handles: handle.close()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',required=True,type=Path)
    parser.add_argument('--limit',type=int,default=100)
    parser.add_argument('--check',action='store_true',help='Prerequisite checks only; never gate evidence')
    parser.add_argument('--fresh-environment',type=Path,
                        help='Provision a new worktree-local environment; reject existing directories')
    args=parser.parse_args()
    if not 1<=args.limit<=100: parser.error('Limit must be 1..100')
    config=json.loads(args.config.read_text(encoding='utf-8-sig'))
    validate(config)
    if args.check:
        environment_path(args.fresh_environment)
        print('Local prerequisite paths exist. No inference, build, reproduction, or qualification claim.')
        return 0
    return run(config,args.limit,args.fresh_environment)


if __name__=='__main__': raise SystemExit(main())
