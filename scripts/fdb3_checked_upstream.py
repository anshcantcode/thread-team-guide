"""Run an unchanged upstream judge CLI with durable, fail-closed receipts.

Upstream intentionally falls back to exact matching after judge errors. Keep its
report intact, but never present that fallback as a completed judged run.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.fdb3_evaluate import checkpoint_json, load
from thread_agent.fdb3_judge_transport import NativeJudgeTransport


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_checked(module, argv, client, evidence, report, *, local, native_calls):
    """Transport instrumentation only; module.main owns prompts and scoring."""
    requests = report.setdefault("judge_requests", [])
    report["native_judge_calls"] = native_calls
    report.update(status="infrastructure_error", qualification_eligible=False,
                  infrastructure_error="Judge execution incomplete", upstream_exit_code=None)

    def save():
        checkpoint_json(evidence, report)

    original_create = client.chat.completions.create
    original_argv = sys.argv
    original_client = module._openai_client

    def checked_create(*args, **kwargs):
        receipt = {"outcome": "pending", "requested_model": kwargs.get("model")}
        requests.append(receipt)
        save()
        try:
            reply = original_create(*args, **kwargs)
            choice = reply.choices[0]
            content = choice.message.content
            receipt.update(content=content, returned_model=reply.model,
                           finish_reason=choice.finish_reason)
            judgment = json.loads(module._strip_json_fences(content))
            if (not isinstance(judgment, dict) or type(judgment.get("correct")) is not bool
                    or not isinstance(judgment.get("explanation"), str)
                    or choice.finish_reason != "stop"):
                raise ValueError("Invalid or unfinished judge response")
            receipt["outcome"] = "success"
            return reply
        except BaseException as error:
            receipt.update(outcome="error", error_type=type(error).__name__)
            raise
        finally:
            save()

    try:
        save()
        client.chat.completions.create = checked_create
        module._openai_client = client
        sys.argv = [module.__name__] + list(argv)
        try:
            module.main()
            report["upstream_exit_code"] = 0
        except SystemExit as error:
            report["upstream_exit_code"] = error.code if isinstance(error.code, int) else (0 if error.code is None else 1)
        if (report["upstream_exit_code"] == 0 and requests
                and all(row["outcome"] == "success" for row in requests)
                and (not local or (len(requests) == len(native_calls) and all(
                    row.get("outcome") == "success" and row.get("inference_requests") == 1
                    for row in native_calls)))):
            report.update(status="completed")
            report.pop("infrastructure_error", None)
    except BaseException as error:
        report.update(status="infrastructure_error", error_type=type(error).__name__,
                      error_traceback=traceback.format_tb(error.__traceback__),
                      infrastructure_error="Evaluator or receipt persistence failed")
    finally:
        sys.argv = original_argv
        module._openai_client = original_client
        client.chat.completions.create = original_create
        save()
    return 0 if report["status"] == "completed" else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--script", choices=("evaluate_tool_calls", "evaluate_pass_rate"), required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--judge-mode", choices=("local", "hosted"), required=True)
    parser.add_argument("--judge-endpoint")
    parser.add_argument("--judge-identity", required=True)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.evidence.exists():
        parser.error("Refusing to overwrite judge receipts")
    forwarded = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
    inputs = argparse.ArgumentParser(add_help=False)
    for name in ("benchmark", "results-dir", "provider", "output"):
        inputs.add_argument("--" + name, required=True)
    inputs.add_argument("--use-llm", action="store_true", required=True)
    options = inputs.parse_args(forwarded)
    output = Path(options.output)
    if output.exists():
        parser.error("Refusing to overwrite upstream output")
    report = {"status": "infrastructure_error", "qualification_eligible": False,
              "judge_mode": args.judge_mode, "judge_identity": args.judge_identity,
              "evaluator_script": args.script, "output_path": str(output.resolve()),
              "infrastructure_error": "Judge initialization incomplete", "judge_requests": [],
              "native_judge_calls": []}
    checkpoint_json(args.evidence, report)
    client = None
    code = 2
    try:
        import httpx
        from openai import OpenAI
        evaluator_path = args.upstream / (args.script + ".py")
        report["evaluator_sha256"] = digest(evaluator_path)
        report["benchmark_sha256"] = digest(options.benchmark)
        results = Path(options.results_dir)
        report["inference_sha256"] = {p.relative_to(results).as_posix(): digest(p)
                                      for p in sorted(results.rglob(f"result_{options.provider}.json"))}
        checkpoint_json(args.evidence, report)
        native = report["native_judge_calls"]
        if args.judge_mode == "local":
            if not args.judge_endpoint:
                raise ValueError("Local mode requires an explicit loopback judge endpoint")
            transport = NativeJudgeTransport(args.judge_endpoint, native,
                record_callback=lambda calls: checkpoint_json(args.evidence, report))
            client = OpenAI(base_url=args.judge_endpoint, api_key="local-unbilled", max_retries=0,
                http_client=httpx.Client(timeout=90, trust_env=False, transport=transport))
        else:
            if os.environ.get("THREAD_FDB3_HOSTED_JUDGE_AUTHORIZED") != "1" or not os.environ.get("OPENAI_API_KEY"):
                raise ValueError("Hosted judging requires explicit authorization and credentials")
            client = OpenAI(max_retries=0, timeout=90)
        module = load(args.script, args.upstream)
        code = run_checked(module, forwarded, client, args.evidence, report,
                           local=args.judge_mode == "local", native_calls=native)
        if (digest(evaluator_path) != report["evaluator_sha256"]
                or digest(options.benchmark) != report["benchmark_sha256"]
                or {p.relative_to(results).as_posix(): digest(p)
                    for p in sorted(results.rglob(f"result_{options.provider}.json"))} != report["inference_sha256"]):
            raise ValueError("Evaluated source or inputs changed during scoring")
        report["output_sha256"] = digest(output)
        if not report["inference_sha256"]:
            raise ValueError("No inference inputs were inventoried")
    except BaseException as error:
        report.update(status="infrastructure_error", error_type=type(error).__name__,
                      initialization_traceback=traceback.format_tb(error.__traceback__),
                      infrastructure_error="Incomplete checked evaluator execution")
        code = 2
    finally:
        try:
            if client is not None:
                client.close()
        except BaseException as error:
            report.update(status="infrastructure_error", error_type=type(error).__name__,
                          infrastructure_error="Judge client cleanup failed")
            code = 2
        finally:
            checkpoint_json(args.evidence, report)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
