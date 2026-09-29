"""Independent positive/negative judge protocol controls, no benchmark examples."""
import argparse
from functools import partial
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.fdb3_evaluate import load, checkpoint_json
from thread_agent.fdb3_judge_transport import NativeJudgeTransport
import httpx
from openai import OpenAI

def run_probe(upstream, output):
    if output.exists():
        raise FileExistsError("Fresh output required")
    rows, native_calls, results, valid = [], [], [], []
    report = {"passed": False, "status": "in_progress", "cases": results, "valid_json": valid,
        "raw": rows, "native_calls": native_calls, "paid_requests": 0, "qualification": False}
    checkpoint_error = None

    def checkpoint(_calls=None):
        nonlocal checkpoint_error
        if checkpoint_error is not None:
            raise checkpoint_error  # Never resume HTTP after an evidence-write failure.
        report["recorded_at"] = time.time()
        try:
            checkpoint_json(output, report)  # fsync + atomic replacement before submission.
        except BaseException as exc:
            checkpoint_error = exc
            raise

    checkpoint()  # Persist even interruption during evaluator/client initialization.
    def capture(response):
        response.read()
        rows.append(response.json())
    module = load("evaluate_pass_rate", upstream)
    with OpenAI(base_url="http://127.0.0.1:8097/v1",api_key="local-unbilled",max_retries=0,
                http_client=httpx.Client(timeout=90,trust_env=False,event_hooks={"response":[capture]},
                    transport=NativeJudgeTransport('http://127.0.0.1:8097/v1',native_calls,
                                                   record_callback=checkpoint))) as client:
        client.chat.completions.create=partial(client.chat.completions.create,response_format={"type":"json_object"},
            extra_body={"chat_template_kwargs":{"enable_thinking":False},"cache_prompt":False})
        module._openai_client=client
        for actual in ["F17", "G28"]:
            result = module.llm_judge_argument({"tag":"F17"},{"tag":actual},"lookup_asset")
            if checkpoint_error is not None:
                raise checkpoint_error  # The upstream evaluator may swallow SDK exceptions.
            results.append(result)
            checkpoint()
    for row in rows:
        try:
            body=json.loads(row["choices"][0]["message"]["content"])
            valid.append(type(body.get("correct")) is bool and isinstance(body.get("explanation"),str))
        except (ValueError,KeyError,TypeError):
            valid.append(False)
    report.update(status="completed", passed=len(rows)==2 and all(valid) and results[0][0] is True and results[1][0] is False)
    checkpoint()
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--upstream",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args()
    if args.output.exists(): parser.error("Fresh output required")
    report = run_probe(args.upstream, args.output)
    print(json.dumps({key: report[key] for key in ("passed", "valid_json", "cases")}))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
