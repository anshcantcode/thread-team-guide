"""Run the unchanged official evaluator, retaining every score and trace.

Uses read-only Python return observers on eval_submission.run_once and candidate
HTTP response frames. No official or participant code/globals are patched.
Only allowlisted metadata is retained from already-buffered HTTP 429 responses.
An optional private observer retains sanitized non-thought provider decisions,
planner/controller snapshots and actual embedding values from existing buffers.
Attempt markers are written at official run boundaries; profiling/parsing adds
overhead. HTTP 429 aborts the batch without retrying or starting another case.
Optional request caps also stop before dispatch; they do not pace requests.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib
import importlib.metadata
import json
import os
import re
import runpy
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .audit import audit_public
from .decisions import DecisionObserver
from .quota import QuotaObserver, RequestCapStop, TransportObserver


def write_json(path: Path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def fingerprint(root: Path) -> dict[str, str]:
    found = {}
    excluded = {".git", ".venv", ".runtime", "__pycache__", ".pytest_cache", "node_modules"}
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in excluded)
        for name in sorted(files):
            path = Path(directory) / name
            if (name == ".env" or (name.startswith(".env.") and name != ".env.example")
                    or path.suffix in {".pyc", ".pyo"}):
                continue
            found[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return found


class Tee:
    def __init__(self, stream, logfile):
        self.stream, self.logfile = stream, logfile

    def write(self, value):
        self.logfile.write(value)
        self.logfile.flush()
        return self.stream.write(value)

    def flush(self):
        self.logfile.flush()
        self.stream.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--reference-kit", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="New, nonexistent evidence directory")
    parser.add_argument("--mode", choices=("real-provider", "organizer-reference", "scripted"), required=True)
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--time-scale", type=float, default=1)
    parser.add_argument("--scenarios", type=Path)
    parser.add_argument("--env-file", type=Path, help="Load key values in memory; never copied or recorded")
    parser.add_argument("--max-generation-requests", type=int)
    parser.add_argument("--max-embedding-requests", type=int)
    parser.add_argument("--cap-generation-model", help="Exact Gemini generation model allowed by an optional request cap")
    parser.add_argument("--decision-evidence", action="store_true", help="Private sanitized provider/planner/controller snapshots; real-provider mode only")
    parser.add_argument("--delivery-evidence", action="store_true", help="Read-only task-correlated HTTP stage times; pinned runtime and explicit request caps required")
    args = parser.parse_args()
    if args.decision_evidence and sys.version_info[:2] != (3, 11):
        parser.error("--decision-evidence requires the verified Python 3.11 profile-event semantics")
    if args.decision_evidence and args.mode != "real-provider":
        parser.error("--decision-evidence requires real-provider mode")
    capped = args.max_generation_requests is not None or args.max_embedding_requests is not None
    if capped and (args.mode != "real-provider" or args.max_generation_requests is None
                   or args.max_embedding_requests is None or min(args.max_generation_requests, args.max_embedding_requests) < 0
                   or not re.fullmatch(r"gemini-[A-Za-z0-9._-]{1,80}", args.cap_generation_model or "")):
        parser.error("request caps require real-provider mode, both nonnegative limits, and an exact --cap-generation-model")
    if args.cap_generation_model and not capped:
        parser.error("--cap-generation-model requires both request caps")
    caps = {"generation": args.max_generation_requests, "embedding": args.max_embedding_requests} if capped else None
    if args.delivery_evidence:
        if args.mode != "real-provider" or not capped:
            parser.error("--delivery-evidence requires real-provider mode and explicit request caps")
        from .delivery import DeliveryObserver, validate_runtime
        try:
            delivery_versions = validate_runtime()
        except RuntimeError as exc:
            parser.error(str(exc))
    for name in ("submission", "kit", "reference_kit", "out"):
        setattr(args, name, getattr(args, name).resolve())
    if args.reps < 1 or args.time_scale <= 0:
        parser.error("positive repetitions and time scale required")
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file.resolve(), override=False)
    if args.out.exists():
        parser.error("--out already exists; every attempt must be preserved")
    if any(args.out.is_relative_to(root) for root in (args.submission, args.kit, args.reference_kit)):
        parser.error("--out must be outside the frozen source and kit roots")
    sys.dont_write_bytecode = True
    args.out.mkdir(parents=True)
    before = {"submission": fingerprint(args.submission), "kit": fingerprint(args.kit),
              "reference_kit": fingerprint(args.reference_kit)}
    official_files = {p: digest for p, digest in before["reference_kit"].items()
                      if p != "submission.yaml"}
    mismatch = [p for p, digest in official_files.items() if before["kit"].get(p) != digest]
    manifest = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "argv": sys.argv, "mode": args.mode, "submission": str(args.submission),
        "kit": str(args.kit), "reference_kit": str(args.reference_kit),
        "reps": args.reps, "time_scale": args.time_scale,
        "request_caps": caps, "cap_generation_model": args.cap_generation_model,
        "decision_evidence_enabled": args.decision_evidence,
        "python_executable": sys.executable, "python_version": sys.version,
        "platform": sys.platform,
        "platform_details": str(os.uname()) if hasattr(os, "uname") else str(sys.getwindowsversion()),
        "packages": sorted({f"{d.metadata['Name']}=={d.version}" for d in importlib.metadata.distributions()}),
        "environment": {name: os.environ.get(name) for name in
                        ("PARTICIPANT_MODEL", "PARTICIPANT_MEDIA_ROOT", "PARTICIPANT_THINKING_LEVEL",
                         "PARTICIPANT_IMAGE_EMBEDDING", "PARTICIPANT_PREWARM", "PARTICIPANT_TIMEOUT_SECONDS",
                         "PARTICIPANT_THINKING_BUDGET", "PARTICIPANT_AUDIO_MODE",
                         "THREAD_MODEL", "THREAD_PROVIDER")},
        "credential_presence": {name: bool(os.environ.get(name)) for name in
                                ("SECRET_GEMINI_API_KEY", "THREAD_API_KEY", "GEMINI_API_KEY")},
        "fingerprints_before": before, "official_mismatches": mismatch,
        "acceptance_source_sha256": fingerprint(Path(__file__).resolve().parent),
        "observer": "sys.setprofile observer; no code/global patches. Records buffered request hashes, imports and allowlisted HTTP 429 metadata. Optional private decision evidence snapshots provider/planner/controller stages and actual embedding values. Adds overhead; no extra requests, retries, stream reads or clock changes. A captured 429 aborts the batch. Optional explicit request caps also abort before unallocated transport.",
        "limitations": ["Platform is recorded above; no GPU or hidden-set claim.",
                        "Official deterministic score only; no LLM quality multiplier or hidden-set result."],
    }
    if args.delivery_evidence:
        manifest["delivery_evidence"] = {"versions": delivery_versions,
            "observer": "Read-only exact profile boundaries; no trace extension or runtime patches. Monotonic times include observer overhead; unmatched or absent stages remain explicit."}
    write_json(args.out / "manifest.json", manifest)
    if mismatch:
        raise SystemExit("Official kit mismatch; see retained manifest.json")
    evaluator = args.kit / "eval_submission.py"
    original_argv, original_cwd = sys.argv[:], Path.cwd()
    official_args = [str(evaluator), str(args.submission), "--reps", str(args.reps),
                     "--time-scale", str(args.time_scale), "--out", str(args.out / "official-report.json")]
    if args.scenarios:
        official_args.extend(["--scenarios", str(args.scenarios.resolve())])
    manifest["official_command_argv"] = [sys.executable, *official_args]
    scenario_root = args.scenarios.resolve() if args.scenarios else args.kit / "scenarios"
    manifest["selected_scenarios"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in sorted(scenario_root.glob("*.json"))}
    planned = [{"attempt": i + 1, "scenario_id": sid} for i, sid in enumerate(
        json.loads(p.read_text(encoding="utf-8"))["scenario_id"]
        for p in sorted(scenario_root.glob("*.json")) for _ in range(args.reps))]
    attempts, current_evidence, observer_errors, prescenario_evidence = [], [], [], []
    quota_observer, transport_observer, prescenario_quota = None, None, []
    prescenario_transport, runtime_configurations = [], []
    setup_code = None
    decision_observer, prescenario_decisions = None, []
    delivery_observer, prescenario_delivery = None, []

    class QuotaStop(SystemExit):
        pass

    class DeliveryStop(SystemExit):
        pass

    def observe(frame, event, result):
        if decision_observer is not None:
            decision_observer.capture(frame, event, result)
        if transport_observer is not None:
            try:
                transport_observer.capture(frame, event, result)
            except RequestCapStop:
                manifest["request_cap_stopped"] = True
                manifest["wrapper_error"] = "Request allocation guard stopped before transport; remaining attempts unrun"
                raise
        if delivery_observer is not None:
            delivery_observer.capture(frame, event, result)
            if delivery_observer.errors:
                manifest["delivery_observer_error"] = True
                manifest["wrapper_error"] = "Delivery evidence observer failed; batch aborted, remaining attempts unrun"
                raise DeliveryStop(77)
        if event == "return" and quota_observer is not None:
            quota_observer.capture(frame)
            if quota_observer.rows:
                manifest["quota_stopped"] = True
                manifest["wrapper_error"] = "HTTP 429 observed; batch aborted, remaining attempts unrun"
                # SystemExit also leaves asyncio's task runner, so another input
                # in this same scenario cannot issue another provider request.
                raise QuotaStop(75)
        if event == "return" and frame.f_code is setup_code:
            instance = frame.f_locals.get("self")
            if instance is not None and instance.client is not None:
                config = {name: getattr(instance, name, None) for name in
                          ("model", "thinking", "thinking_budget", "image_embedding", "timeout", "audio_mode")}
                config["prewarm"] = frame.f_locals.get("prewarm")
                if config not in runtime_configurations:
                    runtime_configurations.append(config)
        if frame.f_code.co_name != "run_once" or frame.f_code.co_filename != str(evaluator):
            return
        if event == "call":
            if delivery_observer is not None:
                prescenario_delivery.append(delivery_observer.take())
            if decision_observer is not None:
                prescenario_decisions.extend(decision_observer.rows)
                decision_observer.rows.clear()
            if current_evidence:
                prescenario_evidence.extend(current_evidence)
                current_evidence.clear()
            if quota_observer is not None:
                prescenario_quota.extend(quota_observer.rows)
                quota_observer.rows.clear()
            if transport_observer is not None:
                prescenario_transport.extend(transport_observer.rows)
                transport_observer.rows.clear()
            index = len(attempts) + 1
            scenario = frame.f_locals["scenario"]
            # Persist an entered attempt before execution; a killed process must
            # not make a started case disappear from the denominator.
            write_json(args.out / f"attempt-{index:03d}-{scenario['scenario_id']}.json",
                       {"attempt": index, "scenario_id": scenario["scenario_id"], "status": "started",
                        "trace": [], "score": None, "model_evidence": [], "transport_requests": []})
            return
        if event != "return":
            return
        local = frame.f_locals
        scenario = local["scenario"]
        index = len(attempts) + 1
        row = {"attempt": index, "scenario_id": scenario["scenario_id"],
                   "status": "returned" if isinstance(result, dict) else "aborted",
                   "official_limits": {name: local.get(name) for name in
                                       ("time_scale", "wall_cap_s", "setup_cap_s")},
                   "trace": local.get("trace") or [], "score": result,
                   "model_evidence": list(current_evidence),
                   "transport_requests": list(transport_observer.rows) if transport_observer is not None else [],
                   "http429_metadata": list(quota_observer.rows) if quota_observer is not None else []}
        if decision_observer is not None:
            row["decision_evidence"] = list(decision_observer.rows)
            decision_observer.rows.clear()
        if delivery_observer is not None:
            row["delivery_evidence"] = delivery_observer.take()
        if capped:
            row["request_budget"] = transport_observer.budget()
        current_evidence.clear()
        if quota_observer is not None:
            quota_observer.rows.clear()
        if transport_observer is not None:
            transport_observer.rows.clear()
        try:
            from harness.mock_env import TOOL_REGISTRY
            row["audit"] = audit_public(scenario, row["trace"], result or {}, TOOL_REGISTRY,
                                        row["model_evidence"] if args.mode == "real-provider" else None,
                                        args.kit)
            row["imports"] = {name: str(Path(module.__file__).resolve())
                              for name, module in list(sys.modules.items())
                              if name.startswith(("participant", "harness")) and getattr(module, "__file__", None)}
            row["import_sha256"] = {name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
                                    for name, path in row["imports"].items()}
        except Exception as exc:
            observer_errors.append(f"{type(exc).__name__}: {exc}")
            row["observer_error"] = f"{type(exc).__name__}: {exc}"
        finally:
            write_json(args.out / f"attempt-{index:03d}-{scenario['scenario_id']}.json", row)
            attempts.append({"attempt": index, "scenario_id": row["scenario_id"],
                             "score": result.get("total") if isinstance(result, dict) else None,
                             "task_complete": row.get("audit", {}).get("task_complete", False),
                             "accepted": row.get("audit", {}).get("accepted", False),
                             "failures": row.get("audit", {}).get("failures", ["observer_failed"])})

    exit_code = 0
    try:
        os.chdir(args.kit)
        sys.path.insert(0, str(args.submission))
        with contextlib.ExitStack() as stack:
            if args.mode == "real-provider":
                planner = importlib.import_module("participant.planner")
                module_path = Path(planner.__file__).resolve()
                if not module_path.is_relative_to(args.submission):
                    raise RuntimeError(f"Wrong participant import: {module_path}")
                trace_context = getattr(planner, "planner_trace", None)
                if trace_context is None:
                    raise RuntimeError("Real-provider run requires planner_trace evidence hook")
                stack.enter_context(trace_context(current_evidence.append))
                response_functions = {}
                for name, phase in (("_decide", "planning"), ("_perceive_audio", "acoustic"), ("_warmup", "warmup")):
                    method = getattr(planner.Planner, name, None)
                    if method is not None:
                        response_functions[method.__code__] = phase
                try:
                    embedding = importlib.import_module("participant.embedding")
                except ModuleNotFoundError as exc:
                    if exc.name != "participant.embedding":
                        raise
                else:
                    if not Path(embedding.__file__).resolve().is_relative_to(args.submission):
                        raise RuntimeError("Wrong participant embedding import")
                    response_functions[embedding.embed_image.__code__] = "embedding"
                quota_observer = QuotaObserver(response_functions)
                transport_observer = TransportObserver(caps, args.cap_generation_model)
                if args.delivery_evidence:
                    delivery_observer = DeliveryObserver(transport_observer)
                setup_code = planner.Planner.setup.__code__
                if args.decision_evidence:
                    agent = importlib.import_module("participant.agent")
                    if not Path(agent.__file__).resolve().is_relative_to(args.submission):
                        raise RuntimeError("Wrong participant agent import")
                    functions = {code: ("embedding_return" if phase == "embedding" else "provider_response", phase)
                                 for code, phase in response_functions.items()}
                    functions[planner.Planner.plan.__code__] = ("planner_return", "planning")
                    functions[agent.ParticipantAgent._apply.__code__] = ("controller_apply", "controller")
                    decision_observer = DecisionObserver(functions, [os.environ.get(name) for name in
                        ("SECRET_GEMINI_API_KEY", "THREAD_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")])
            logfile = stack.enter_context((args.out / "console.log").open("w", encoding="utf-8"))
            stack.enter_context(contextlib.redirect_stdout(Tee(sys.stdout, logfile)))
            stack.enter_context(contextlib.redirect_stderr(Tee(sys.stderr, logfile)))
            sys.argv = official_args
            sys.setprofile(observe)
            try:
                runpy.run_path(str(evaluator), run_name="__main__")
            except SystemExit as exc:
                exit_code = int(exc.code or 0) if isinstance(exc.code, (int, type(None))) else 1
            finally:
                sys.setprofile(None)
    except Exception as exc:
        exit_code = 1
        manifest["wrapper_error"] = f"{type(exc).__name__}: {exc}"
        print(manifest["wrapper_error"], file=sys.stderr)
    finally:
        sys.setprofile(None)
        sys.argv = original_argv
        os.chdir(original_cwd)
        stop_reason = ("quota_stopped" if manifest.get("quota_stopped") else
                       "request_cap_stopped" if manifest.get("request_cap_stopped") else
                       "delivery_observer_error" if manifest.get("delivery_observer_error") else None)
        if stop_reason:
            for path in sorted(args.out.glob("attempt-[0-9][0-9][0-9]-*.json")):
                row = json.loads(path.read_text(encoding="utf-8"))
                if row.get("status") != "started":
                    continue
                row.update(status=stop_reason, model_evidence=list(current_evidence),
                           transport_requests=list(transport_observer.rows),
                           http429_metadata=list(quota_observer.rows))
                if decision_observer is not None:
                    row["decision_evidence"] = list(decision_observer.rows)
                    decision_observer.rows.clear()
                if delivery_observer is not None:
                    row["delivery_evidence"] = delivery_observer.take()
                if capped:
                    row["request_budget"] = transport_observer.budget()
                write_json(path, row)
                attempts.append({"attempt": row["attempt"], "scenario_id": row["scenario_id"],
                                 "score": None, "task_complete": False, "accepted": False,
                                 "failures": [stop_reason]})
                current_evidence.clear()
                transport_observer.rows.clear()
                quota_observer.rows.clear()
        if capped:
            manifest["request_budget"] = transport_observer.budget() if transport_observer is not None else None
        if args.decision_evidence:
            manifest.update(prescenario_decision_evidence=prescenario_decisions,
                            unassociated_decision_evidence=decision_observer.rows if decision_observer is not None else [],
                            decision_observer_errors=decision_observer.errors if decision_observer is not None else [])
        if args.delivery_evidence:
            manifest.update(prescenario_delivery_evidence=prescenario_delivery,
                            unassociated_delivery_evidence=delivery_observer.take() if delivery_observer is not None else None,
                            delivery_observer_errors=delivery_observer.errors if delivery_observer is not None else [])
        if stop_reason:
            manifest["unrun_attempts"] = [{**row, "status": "unrun_after_" + stop_reason}
                                          for row in planned if row["attempt"] > len(attempts)]
        after = {"submission": fingerprint(args.submission), "kit": fingerprint(args.kit),
                 "reference_kit": fingerprint(args.reference_kit)}
        manifest.update({"finished_utc": datetime.now(timezone.utc).isoformat(),
                         "official_exit_code": exit_code, "observer_errors": observer_errors,
                         "fingerprints_after": after, "sources_unchanged": before == after,
                         "acceptance_source_sha256_after": fingerprint(Path(__file__).resolve().parent),
                         "attempts": attempts, "prescenario_model_evidence": prescenario_evidence,
                         "unassociated_model_evidence": current_evidence,
                         "effective_runtime_configurations": runtime_configurations,
                         "prescenario_transport_requests": prescenario_transport,
                         "unassociated_transport_requests": transport_observer.rows if transport_observer is not None else [],
                         "transport_observer_errors": transport_observer.errors if transport_observer is not None else [],
                         "prescenario_http429_metadata": prescenario_quota,
                         "unassociated_http429_metadata": quota_observer.rows if quota_observer is not None else [],
                         "quota_observer_errors": quota_observer.errors if quota_observer is not None else []})
        package_manifest = args.submission / "PACKAGE_MANIFEST.json"
        if package_manifest.is_file():
            # A frozen package may live inside an unrelated checkout. Its own
            # hashed manifest is the source identity; no git child is needed.
            manifest["git_head"] = json.loads(package_manifest.read_text(encoding="utf-8")).get("source_git_revision")
            manifest["git_head_source"] = "frozen_package_manifest"
        else:
            manifest["git_head_source"] = "unpackaged_checkout"
            try:
                manifest["git_head"] = subprocess.check_output(
                    ["git", "-C", str(args.submission), "rev-parse", "HEAD"], stderr=subprocess.DEVNULL,
                    text=True, timeout=5).strip()
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                manifest["git_head"] = None
        write_json(args.out / "manifest.json", manifest)
        write_json(args.out / "attempt-index.json", attempts)
        write_json(args.out / "evidence-sha256.json", {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(args.out.iterdir())
            if p.is_file() and p.name != "evidence-sha256.json"})
    if (observer_errors or manifest["quota_observer_errors"] or manifest["transport_observer_errors"]
            or manifest.get("delivery_observer_errors") or before != after):
        exit_code = exit_code or 2
    if not attempts and exit_code == 0:
        exit_code = 2
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
