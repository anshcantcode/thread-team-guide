"""Evaluator-only, text-only counterfactual receipts from saved tool outcomes.

Does not run inference, tools, audio or TTS, and never writes into input runs.
Prepare first; --judge explicitly enables a serial, lock-guarded local judge.
"""
import argparse
import ast
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from types import ModuleType
from typing import Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from participant.agent import ParticipantAgent
from thread_agent.fdb3 import load_contract
from thread_agent.fdb3_judge_transport import NativeJudgeTransport
from scripts.fdb3_evaluate import checkpoint_json


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def source_identity():
    files = ["participant/agent.py", "participant/presentation.py", "participant/spoken.py",
             "thread_agent/fdb3.py", "thread_agent/fdb3_judge_transport.py", "scripts/fdb3_compare_answers.py"]
    return {name: digest(ROOT / name) for name in files}


def old_renderer(revision):
    source = subprocess.check_output(["git", "show", f"{revision}:participant/agent.py"], cwd=ROOT)
    module = ModuleType("participant._task_c_baseline")
    module.__package__ = "participant"
    exec(compile(source, f"{revision}:participant/agent.py", "exec"), module.__dict__)
    return module.ParticipantAgent, hashlib.sha256(source).hexdigest()


def render_case(cls, result, tools):
    agent = cls(asyncio.Queue(), asyncio.Queue())
    agent.tools = deepcopy(tools)
    operations = deepcopy(result.get("operations", []))
    agent.operations = {op["call_id"]: op for op in operations}
    # Compare the same actual outcomes, never gold-derived successes. Retained
    # consumers are views of one executed call, not another completed step.
    sources = {op.get("retained_from_call_id") for op in operations}
    selected = [op for op in operations if "result" in op and op["call_id"] not in sources]
    parts = []
    for op in selected:
        agent.revision = op["revision"]
        parts.append(agent._render(op))
    if not parts:
        # No receipt exists to re-render. Preserve recorded terminal speech in
        # both arms, rather than inventing completion or dropping the case.
        parts = [event["payload"]["text"] for event in result.get("controller_events", [])
                 if event["action"] in {"final_response", "clarification_request"}]
    return " ".join(parts), [op["call_id"] for op in selected]


def check_lock(path):
    if not path.exists():
        return
    try:
        purpose = read(path)["purpose"]
    except (OSError, ValueError, KeyError):
        raise RuntimeError("Shared lock is unreadable; no judge request is authorized")
    if not isinstance(purpose, str) or re.search(r"full|held[\s_-]*out", purpose, re.I):
        raise RuntimeError(f"Shared lock forbids judging: {purpose}")


def prepare(args):
    old, old_hash = old_renderer(args.baseline)
    tools = load_contract(args.contract)
    rows, runs = [], []
    for run in args.run:
        if not (run / "report.json").is_file():
            raise ValueError(f"No report.json yet: {run}")
        report, manifest = read(run / "report.json"), read(run / "dataset-manifest.json")
        metadata_by_id = {row["recording"]: row for row in manifest["recordings"]}
        runs.append({"path": str(run), "report_sha256": digest(run / "report.json"),
                     "manifest_sha256": digest(run / "dataset-manifest.json"),
                     "benchmark_commit": manifest.get("upstream_commit"),
                     "expected": report.get("expected"), "available_cases": len(report["cases"]),
                     "report_status": report.get("status")})
        for index, case in enumerate(report["cases"]):
            path = run / f"case-{index:03d}" / "inference/result.json"
            if not path.is_file():
                raise ValueError(f"Missing saved inference: {path}")
            metadata_path = args.metadata_root / case["recording"] / "metadata.json"
            metadata_hash = digest(metadata_path)
            if metadata_hash != metadata_by_id[case["recording"]]["metadata_sha256"]:
                raise ValueError(f"Metadata hash mismatch: {metadata_path}")
            result = read(path)
            if digest(path) != case.get("result_sha256"):
                raise ValueError(f"Saved inference hash mismatch: {path}")
            metadata = read(metadata_path)
            old_text, calls = render_case(old, result, tools)
            new_text, new_calls = render_case(ParticipantAgent, result, tools)
            assert calls == new_calls
            rows.append({"run": run.name, "case": f"case-{index:03d}", "recording": case["recording"],
                         "input_result_sha256": digest(path), "metadata_sha256": metadata_hash,
                         "expected_intent": metadata["dialogue"][-1].get("ai", ""),
                         "selected_call_ids": calls, "old": old_text, "new": new_text})
    return {"scope": "text-only operation-joined receipts, not fresh inference or speech round trip",
            "selection": "all recorded outcomes with a result, in dispatch order; retained source replaced by its consumer; no-result cases retain terminal speech",
            "baseline_commit": subprocess.check_output(["git", "rev-parse", args.baseline], cwd=ROOT, text=True).strip(),
            "baseline_agent_sha256": old_hash, "source_sha256": source_identity(),
            "upstream_evaluator_sha256": digest(args.upstream / "evaluate_tool_calls.py"),
            "contract_sha256": {name: digest(args.contract / name) for name in ("cascaded_agent.py", "mock_apis.py")},
            "runs": runs, "cases": rows}


def judge_function(path, client):
    # Compile the exact upstream functions without its .env loading or global
    # hosted client fallback. The prompt, token cap and scoring are unchanged.
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in {"_strip_json_fences", "llm_judge_response"}]
    if len(functions) != 2:
        raise ValueError("Upstream judge functions were not found")
    namespace = {"json": json, "Tuple": Tuple, "_get_openai_client": lambda: client}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), namespace)
    return namespace["llm_judge_response"]


def summarize(prepared, output):
    rows = []
    for index, case in enumerate(prepared["cases"]):
        arms = {side: read(output / f"{index:03d}-{side}.json") for side in ("old", "new")
                if (output / f"{index:03d}-{side}.json").exists()}
        rows.append({**{key: case[key] for key in ("run", "case", "recording")}, "arms": arms})
    groups = {}
    for run in prepared["runs"]:
        subset = [row for row in rows if row["run"] == Path(run["path"]).name]
        paired = [row for row in subset if len(row["arms"]) == 2 and all(arm["valid"] for arm in row["arms"].values())]
        groups[Path(run["path"]).name] = {
            "prepared": len(subset), "paired_valid": len(paired),
            "old_mean": sum(row["arms"]["old"]["score"] for row in paired) / len(paired) if paired else None,
            "new_mean": sum(row["arms"]["new"]["score"] for row in paired) / len(paired) if paired else None,
            "regressions": [{"case": row["case"], "recording": row["recording"],
                             "old": row["arms"]["old"]["score"], "new": row["arms"]["new"]["score"],
                             "new_explanation": row["arms"]["new"]["explanation"]} for row in paired
                            if row["arms"]["new"]["score"] < row["arms"]["old"]["score"]],
            "improvements": sum(row["arms"]["new"]["score"] > row["arms"]["old"]["score"] for row in paired),
            "invalid_arms": sum(not arm["valid"] for row in subset for arm in row["arms"].values())}
    return {"scope": prepared["scope"], "groups": groups,
            "judge_seconds": sum(arm["seconds"] for row in rows for arm in row["arms"].values()),
            "judge_requests": sum(len(arm["native_calls"]) for row in rows for arm in row["arms"].values()),
            "paid_spend_inr": 0, "qualification": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, action="append", required=True)
    parser.add_argument("--metadata-root", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--baseline", default="1fb0572")
    parser.add_argument("--judge", action="store_true")
    args = parser.parse_args()
    # Never create an output under evidence, even through a path alias.
    target = args.output.resolve()
    protected = [path.resolve() for path in [*args.run, args.metadata_root, args.contract, args.upstream]]
    if any(target == path or path in target.parents for path in protected):
        parser.error("Output must be separate from all read-only inputs")
    args.output.mkdir(parents=True, exist_ok=True)
    prepared_path = args.output / "prepared.json"
    if prepared_path.exists():
        prepared = read(prepared_path)
        if prepared["source_sha256"] != source_identity() or prepared["upstream_evaluator_sha256"] != digest(args.upstream / "evaluate_tool_calls.py"):
            raise ValueError("Frozen source changed: use a new output directory")
    else:
        prepared = prepare(args)
        checkpoint_json(prepared_path, prepared)
    summary = summarize(prepared, args.output)
    checkpoint_json(args.output / "summary.json", summary)
    print(json.dumps(summary), flush=True)
    if not args.judge:
        return
    import httpx
    from openai import OpenAI
    for index, case in enumerate(prepared["cases"]):
        # Alternate paired order to reduce systematic old/new time-order bias.
        for side in (("old", "new") if index % 2 == 0 else ("new", "old")):
            destination = args.output / f"{index:03d}-{side}.json"
            if destination.exists():
                continue
            if summary["judge_seconds"] >= 3600:
                print("Stopped at the 60-minute judge-time budget", flush=True)
                return
            check_lock(args.lock)
            started, calls = time.monotonic(), []
            def checkpoint(native):
                checkpoint_json(destination.with_suffix(".pending.json"), {"native_calls": native})
                if native and native[-1]["outcome"] == "pending":
                    check_lock(args.lock)
            client = OpenAI(base_url="http://127.0.0.1:8097/v1", api_key="local-unbilled", max_retries=0,
                            http_client=httpx.Client(timeout=90, trust_env=False, transport=NativeJudgeTransport(
                                "http://127.0.0.1:8097/v1", calls, record_callback=checkpoint)))
            try:
                judge = judge_function(args.upstream / "evaluate_tool_calls.py", client)
                score, explanation = judge(case["expected_intent"], case[side])
            finally:
                client.close()
            valid = not case[side]  # Upstream's empty-transcript zero requires no request.
            if calls and len(calls) == 1 and calls[0]["outcome"] == "success":
                try:
                    content = json.loads(calls[0]["native_response"]["content"])
                    valid = (type(content.get("correct")) is bool and isinstance(content.get("explanation"), str)
                             and calls[0]["native_response"].get("stop_type") != "limit")
                except (KeyError, ValueError):
                    valid = False
            checkpoint_json(destination, {"score": score if valid else None, "explanation": explanation,
                "valid": valid, "seconds": time.monotonic() - started, "native_calls": calls,
                "text_sha256": hashlib.sha256(case[side].encode()).hexdigest(), "prepared_sha256": digest(prepared_path)})
            summary = summarize(prepared, args.output)
            checkpoint_json(args.output / "summary.json", summary)
            print(f"{case['run']} {case['case']} {side}: {score if valid else 'INVALID'}", flush=True)
            if not valid:
                raise RuntimeError("Invalid judge evidence; stopped without scoring it as a zero")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
