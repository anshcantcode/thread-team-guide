"""Evaluator process. Gold data enters only after the audio worker has exited."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from functools import partial
from urllib.parse import urlparse
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from thread_agent.fdb3_judge_transport import NativeJudgeTransport


def load(name, root):
    spec = importlib.util.spec_from_file_location(name, root / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def checkpoint_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8') as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def evaluate(upstream, metadata, result, judge_endpoint=None, judge_identity=None, *, record_callback=None):
    requests = []
    native_calls = []
    client = None
    report = {"mode": "official_evaluator_local_judge_diagnostic" if judge_endpoint else "official_exact_match_diagnostic",
        "status": "infrastructure_error", "infrastructure_error": "Evaluation incomplete; retain pending attempts",
        "judge_enabled": bool(judge_endpoint), "judge_identity": judge_identity,
        "requested_model_alias": "gpt-4o" if judge_endpoint else None,
        "judge_note": "Local backend is the declared Qwen model, NOT OpenAI GPT-4o or Samsung's judge." if judge_endpoint else None,
        "judge_configuration": {"transport":"llama.cpp native completion","json_schema":"correct:boolean, explanation:string","enable_thinking":False,"cache_prompt":False,"max_retries":0} if judge_endpoint else None,
        "qualification_eligible": False,
        "strict": {"passed": False, "failure_reason": "Evaluation incomplete"}, "quality": None,
        "judge_requests": requests, "native_judge_calls": native_calls}
    def checkpoint():
        if record_callback is not None:
            record_callback(report)
    try:
        checkpoint()
        strict = load("evaluate_pass_rate", upstream)
        quality = load("evaluate_tool_calls", upstream)
        if judge_endpoint:
            parsed = urlparse(judge_endpoint)
            if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or not judge_identity:
                raise ValueError("Local diagnostic judge requires loopback endpoint and actual model identity")
            import httpx
            from openai import OpenAI
            def checked(response):
                entry = {"status_code": response.status_code, "valid": False}
                requests.append(entry)
                try:
                    response.read()
                    body = response.json()
                    content = body["choices"][0]["message"]["content"]
                    entry.update(usage=body.get("usage"),returned_model=body.get("model"),content=content)
                    judgment = json.loads(strict._strip_json_fences(content))
                    entry['valid'] = type(judgment.get("correct")) is bool and isinstance(judgment.get("explanation"),str)
                finally:
                    checkpoint()
            client = OpenAI(base_url=judge_endpoint, api_key="local-unbilled", max_retries=0,
                            http_client=httpx.Client(timeout=90,trust_env=False,event_hooks={"response":[checked]},
                                transport=NativeJudgeTransport(judge_endpoint,native_calls,
                                    record_callback=lambda calls: checkpoint())))
            # Local transport configuration; upstream prompts and scoring stay unchanged.
            client.chat.completions.create = partial(client.chat.completions.create,
                response_format={"type":"json_object"},
                extra_body={"chat_template_kwargs":{"enable_thinking":False},"cache_prompt":False})
            strict._openai_client = quality._openai_client = client
        calls = result.get("actual_tool_calls", [])
        transcript = result.get("transcript", "")
        report['strict'] = strict.evaluate_scenario_pass(metadata, calls, transcript, result, use_llm=bool(client))
        checkpoint()
        report['quality'] = quality.evaluate_scenario(metadata, calls, transcript, result, use_llm=bool(client))
        if client and (not requests or len(requests)!=len(native_calls)
                       or any(call.get("outcome")!="success" or call.get("inference_requests")!=1 for call in native_calls)
                       or any(not r["valid"] or r["status_code"] != 200 for r in requests)):
            report["infrastructure_error"] = "Judge failed or silently fell back; this is not valid judged evidence"
        else:
            report.pop('infrastructure_error')
            report['status'] = 'completed'
        return report
    except BaseException as exc:
        report.update(status='infrastructure_error', infrastructure_error=str(exc) or type(exc).__name__,
                      error_type=type(exc).__name__)
        raise
    finally:
        try:
            if client:
                client.close()
        except BaseException as exc:
            report.update(status='infrastructure_error', infrastructure_error=str(exc) or type(exc).__name__,
                          error_type=type(exc).__name__)
            raise
        finally:
            checkpoint()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--judge-endpoint")
    parser.add_argument("--judge-identity")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refusing to overwrite an evaluation")
    checkpoint_json(args.output, {'status': 'infrastructure_error', 'qualification_eligible': False,
        'infrastructure_error': 'Evaluation initialization incomplete',
        'strict': {'passed': False, 'failure_reason': 'Evaluation incomplete'},
        'judge_requests': [], 'native_judge_calls': []})
    result_bytes = args.result.read_bytes()
    result = json.loads(result_bytes)
    if result.get("status") != "completed":
        parser.error("Cannot score an incomplete inference as a completed recording")
    metadata_bytes = args.metadata.read_bytes()
    provenance = {
        "inference_sha256": hashlib.sha256(result_bytes).hexdigest(),
        "metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
        "input_sha256": result.get("input_sha256"),
        "evaluator_sha256": {name: hashlib.sha256((args.upstream / name).read_bytes()).hexdigest()
                             for name in ("evaluate_pass_rate.py", "evaluate_tool_calls.py", "analyze_tool_latency.py")},
    }
    def save(body):
        body.update(provenance)
        checkpoint_json(args.output, body)
    report = evaluate(args.upstream, json.loads(metadata_bytes), result,
                      args.judge_endpoint, args.judge_identity,
                      record_callback=save)
    if any(hashlib.sha256((args.upstream / name).read_bytes()).hexdigest() != value
           for name, value in provenance["evaluator_sha256"].items()):
        report.update(status="infrastructure_error", infrastructure_error="Evaluator changed during scoring")
    save(report)
    print(json.dumps({"strict_pass": report["strict"]["passed"],
                      "failure_reason": report["strict"]["failure_reason"], "judge_enabled": report["judge_enabled"]}))
    return 1 if report.get("infrastructure_error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
