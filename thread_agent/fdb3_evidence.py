"""Independent, fail-closed benchmark evidence checks; never infer success from exit 0."""
from pathlib import Path
import hashlib
import json
import wave
import re


def file_hash(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def read_tool_journal(path):
    """Recover conservative evidence after a killed worker, without inventing outcomes."""
    last={}
    malformed=0
    for line in Path(path).read_text(encoding='utf-8',errors='replace').splitlines():
        try:
            row=json.loads(line)
            call=row['call']; call_id=call['call_id']
            if not isinstance(call_id,str) or row['phase'] not in {'dispatch_intent','finished','not_submitted'}:
                raise ValueError('Invalid journal event')
            last[call_id]=row
        except (ValueError,TypeError,KeyError):
            malformed+=1
    return {'completed_invocations':[row['call'] for row in last.values() if row['phase']=='finished'],
            'possible_invocations':[row['call'] for row in last.values() if row['phase']=='dispatch_intent'],
            'definitely_not_submitted':[row['call'] for row in last.values() if row['phase']=='not_submitted'],
            'malformed_lines':malformed}


def audio_duration_seconds(path):
    """Duration of a WAV recording (the upstream capture window length)."""
    try:
        with wave.open(str(path), 'rb') as audio:
            return audio.getnframes() / audio.getframerate()
    except (wave.Error, EOFError):
        import subprocess  # WAVE_FORMAT_EXTENSIBLE (upstream 32-bit PCM) needs ffprobe.
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0',
                                str(path)], capture_output=True, text=True, check=True)
        return float(probe.stdout.strip())


def upstream_window(result, duration):
    """Split actual calls by the pinned upstream capture window.

    Upstream livekit_inference.py captures agent output for the input recording's
    duration from stream start, then reads the tool log. A call completing after
    that point would not be counted there. Evaluator-side only; returns None when
    the run has no stream clock (text/ASR replay or file I/O).
    """
    start = result.get('stream_start_time')
    if not isinstance(start, (int, float)) or not isinstance(duration, (int, float)):
        return None
    end = start + duration
    calls = result.get('actual_tool_calls') or []
    inside = [c for c in calls if isinstance(c.get('timestamp_end'), (int, float)) and c['timestamp_end'] <= end]
    late = [c for c in calls if c not in inside]
    signal = (result.get('output_signal') or {}).get('first_signal_at')
    return {'window_start': start, 'window_end': end, 'duration_seconds': duration,
            'calls_in_window': inside, 'late_calls': late,
            'late_call_seconds': [round(c['timestamp_end'] - end, 3) if isinstance(c.get('timestamp_end'), (int, float))
                                  else None for c in late],
            'first_output_signal_in_window': isinstance(signal, (int, float)) and signal <= end,
            'basis': 'pinned upstream capture window = input duration from stream start; call counted if completed by then'}


def verify_tool_trace(calls, journal):
    """A final result cannot hide a durable completed or possibly submitted call."""
    path=Path(journal)
    if not isinstance(calls,list):
        raise ValueError('Missing actual tool-call list')
    if not path.exists():
        if calls:
            raise ValueError('Actual calls lack durable journal')
        return
    recovered=read_tool_journal(path)
    if recovered['malformed_lines'] or recovered['possible_invocations']:
        raise ValueError('Unresolved/malformed durable tool evidence')
    completed=recovered['completed_invocations']
    actual={c['call_id']:c for c in calls}
    if len(actual)!=len(calls) or actual!={c['call_id']:c for c in completed}:
        raise ValueError('Final tool trace differs from durable invocations')


def verify_series(series, root):
    errors = []
    identity = series.get("frozen_identity")
    required = {"code", "configuration", "dataset", "benchmark", "judge", "dependencies"}
    if not isinstance(identity, dict) or set(identity) != required or not all(identity.values()):
        errors.append("Missing full frozen identity")
    else:
        artifacts=series.get('identity_artifacts',{})
        for kind,digest in identity.items():
            artifact=artifacts.get(kind,{})
            path=(Path(root)/artifact.get('path','')).resolve()
            if (not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest)
                    or not path.is_relative_to(Path(root).resolve()) or not path.is_file()
                    or artifact.get('sha256')!=digest or file_hash(path)!=digest):
                errors.append('Unbound frozen identity artifact')
    runs = series.get("runs", [])
    if len(runs) != 3:
        errors.append("Exactly three preregistered runs required")
    ids = set()
    artifacts_seen = set()
    for run in runs:
        rid = run.get("run_id")
        if not rid or rid in ids:
            errors.append("Duplicate or missing run ID")
        ids.add(rid)
        if run.get("identity") != identity:
            errors.append("Changed frozen identity")
        registered, started = run.get("registered_at"), run.get("started_at")
        if type(registered) not in (int, float) or type(started) not in (int, float) or registered >= started:
            errors.append("Not preregistered before inference")
        if run.get("fresh_inference") is not True or run.get("judge_enabled") is not True:
            errors.append("Fresh judged inference required")
        cases = run.get("cases", [])
        names = {case.get("recording") for case in cases}
        expected = series.get("recordings", [])
        if len(expected) != 100 or len(set(expected)) != 100 or len(cases) != 100 or names != set(expected):
            errors.append("Incomplete or duplicated 100-recording coverage")
        for case in cases:
            if case.get("strict_pass") is not True or case.get("status") != "completed":
                errors.append("Nonpassing recording")
            for kind in ("inference", "evaluation", "audio"):
                artifact = case.get(kind, {})
                path = (Path(root) / artifact.get("path", "")).resolve()
                if path in artifacts_seen:
                    errors.append("Reused artifact across cases/runs")
                artifacts_seen.add(path)
                if not path.is_relative_to(Path(root).resolve()) or not path.is_file():
                    errors.append("Missing/outside evidence artifact")
                    continue
                if file_hash(path) != artifact.get("sha256"):
                    errors.append("Evidence hash mismatch")
                if kind == "audio":
                    try:
                        with wave.open(str(path),"rb") as audio:
                            if audio.getnframes() == 0 or not any(audio.readframes(audio.getnframes())):
                                errors.append("Empty/silent speech artifact")
                    except (wave.Error,EOFError,OSError):
                        errors.append("Invalid speech artifact")
                if kind in {"inference", "evaluation"}:
                    try:
                        body = json.loads(path.read_text(encoding="utf-8"))
                        if kind == "inference":
                            if body.get("status") != "completed" or body.get("run_id") != rid:
                                errors.append("Inference identity/status mismatch")
                            if body.get("input_sha256") != case.get("input_sha256"):
                                errors.append("Wrong input audio")
                            if body.get("recording") != case.get("recording"):
                                errors.append("Recording identity mismatch")
                            if not body.get("actual_tool_calls"):
                                errors.append("Empty tool trace")
                            if (body.get('qualification_eligible') is not True or
                                    body.get('fresh_inference') is not True or body.get('identity')!=identity):
                                errors.append('Diagnostic/nonfresh/unbound inference')
                            if body.get('audio_sha256')!=case.get('audio',{}).get('sha256'):
                                errors.append('Speech not bound to inference')
                            if not isinstance(body.get('transcript'),str) or not body['transcript'].strip():
                                errors.append('Missing spoken transcript')
                        elif (body.get("judge_enabled") is not True or
                              body.get("strict", {}).get("passed") is not True or body.get("run_id") != rid):
                            errors.append("Judge/pass/run mismatch")
                        if kind=='evaluation':
                            requests=body.get('judge_requests',[])
                            native=body.get('native_judge_calls')
                            if (body.get('qualification_eligible') is not True or body.get('infrastructure_error')
                                    or not requests or any(r.get('valid') is not True or r.get('status_code')!=200 for r in requests)
                                    or native is not None and (len(native)!=len(requests) or any(
                                        r.get('outcome')!='success' or r.get('inference_requests')!=1
                                        or r.get('native_response',{}).get('truncated') is True for r in native))):
                                errors.append('Failed/diagnostic/unvalidated judge evidence')
                            if (body.get('inference_sha256')!=case.get('inference',{}).get('sha256')
                                    or body.get('judge_identity_sha256')!=(identity or {}).get('judge')):
                                errors.append('Evaluation not bound to inference/judge')
                    except (ValueError, OSError):
                        errors.append("Malformed report")
    return {"passed": not errors, "scope":"literal-series artifact validation; not all mission gates",
            "errors": sorted(set(errors))}
