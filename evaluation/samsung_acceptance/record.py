"""Run the unchanged official evaluator, retaining every score and trace.

Uses read-only Python return observers on eval_submission.run_once and candidate
HTTP response frames. No official or participant code/globals are patched.
Only allowlisted metadata is retained from already-buffered HTTP 429 responses.
Files are written after the harness stops; profiling/parsing adds overhead.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib
import importlib.metadata
import json
import os
import platform
import runpy
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .audit import audit_public
from .quota import QuotaObserver


def write_json(path: Path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def fingerprint(root: Path) -> dict[str, str]:
    found = {}
    excluded = {".git", ".venv", ".runtime", "__pycache__", ".pytest_cache", "node_modules"}
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in excluded)
        for name in sorted(files):
            path = Path(directory) / name
            if name == ".env" or name.startswith(".env.") or path.suffix in {".pyc", ".pyo"}:
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
    args = parser.parse_args()
    for name in ("submission", "kit", "reference_kit", "out"):
        setattr(args, name, getattr(args, name).resolve())
    if args.reps < 1 or args.time_scale <= 0:
        parser.error("positive repetitions and time scale required")
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file.resolve(), override=False)
    if args.out.exists():
        parser.error("--out already exists; every attempt must be preserved")
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
        "python_executable": sys.executable, "python_version": sys.version,
        "platform": platform.platform(),
        "packages": sorted({f"{d.metadata['Name']}=={d.version}" for d in importlib.metadata.distributions()}),
        "environment": {name: os.environ.get(name) for name in
                        ("PARTICIPANT_MODEL", "PARTICIPANT_MEDIA_ROOT", "PARTICIPANT_THINKING_LEVEL",
                         "PARTICIPANT_IMAGE_EMBEDDING", "PARTICIPANT_PREWARM", "PARTICIPANT_TIMEOUT_SECONDS",
                         "THREAD_MODEL", "THREAD_PROVIDER")},
        "credential_presence": {name: bool(os.environ.get(name)) for name in
                                ("SECRET_GEMINI_API_KEY", "THREAD_API_KEY", "GEMINI_API_KEY")},
        "fingerprints_before": before, "official_mismatches": mismatch,
        "acceptance_source_sha256": fingerprint(Path(__file__).resolve().parent),
        "observer": "Read-only sys.setprofile return observer; no code/global patches. Allowlisted metadata from already-buffered candidate HTTP 429 responses only. Adds profiling/parsing overhead; no requests, retries, stream reads or clock changes.",
        "limitations": ["Windows local evidence only; no Linux/A6000 claim.",
                        "Official deterministic score only; no LLM quality multiplier or hidden-set result."],
    }
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
    attempts, current_evidence, observer_errors, prescenario_evidence = [], [], [], []
    quota_observer, prescenario_quota = None, []

    def observe(frame, event, result):
        if event == "return" and quota_observer is not None:
            quota_observer.capture(frame)
        if frame.f_code.co_name != "run_once" or frame.f_code.co_filename != str(evaluator):
            return
        if event == "call":
            if current_evidence:
                prescenario_evidence.extend(current_evidence)
                current_evidence.clear()
            if quota_observer is not None:
                prescenario_quota.extend(quota_observer.rows)
                quota_observer.rows.clear()
            return
        if event != "return":
            return
        try:
            local = frame.f_locals
            scenario = local["scenario"]
            index = len(attempts) + 1
            row = {"attempt": index, "scenario_id": scenario["scenario_id"],
                   "trace": local.get("trace") or [], "score": result,
                   "model_evidence": list(current_evidence),
                   "http429_metadata": list(quota_observer.rows) if quota_observer is not None else []}
            current_evidence.clear()
            if quota_observer is not None:
                quota_observer.rows.clear()
            from harness.mock_env import TOOL_REGISTRY
            row["audit"] = audit_public(scenario, row["trace"], result, TOOL_REGISTRY,
                                        row["model_evidence"] if args.mode == "real-provider" else None,
                                        args.kit)
            row["imports"] = {name: str(Path(module.__file__).resolve())
                              for name, module in list(sys.modules.items())
                              if name.startswith(("participant", "harness")) and getattr(module, "__file__", None)}
            write_json(args.out / f"attempt-{index:03d}-{scenario['scenario_id']}.json", row)
            attempts.append({"attempt": index, "scenario_id": row["scenario_id"],
                             "score": result.get("total"), "task_complete": row["audit"]["task_complete"],
                             "accepted": row["audit"]["accepted"], "failures": row["audit"]["failures"]})
        except Exception as exc:
            observer_errors.append(f"{type(exc).__name__}: {exc}")

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
        after = {"submission": fingerprint(args.submission), "kit": fingerprint(args.kit),
                 "reference_kit": fingerprint(args.reference_kit)}
        manifest.update({"finished_utc": datetime.now(timezone.utc).isoformat(),
                         "official_exit_code": exit_code, "observer_errors": observer_errors,
                         "fingerprints_after": after, "sources_unchanged": before == after,
                         "attempts": attempts, "prescenario_model_evidence": prescenario_evidence,
                         "unassociated_model_evidence": current_evidence,
                         "prescenario_http429_metadata": prescenario_quota,
                         "unassociated_http429_metadata": quota_observer.rows if quota_observer is not None else [],
                         "quota_observer_errors": quota_observer.errors if quota_observer is not None else []})
        try:
            manifest["git_head"] = subprocess.check_output(
                ["git", "-C", str(args.submission), "rev-parse", "HEAD"], stderr=subprocess.DEVNULL,
                text=True).strip()
        except (OSError, subprocess.CalledProcessError):
            manifest["git_head"] = None
        write_json(args.out / "manifest.json", manifest)
        write_json(args.out / "attempt-index.json", attempts)
        write_json(args.out / "evidence-sha256.json", {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(args.out.iterdir())
            if p.is_file() and p.name != "evidence-sha256.json"})
    if observer_errors or manifest["quota_observer_errors"] or before != after:
        exit_code = exit_code or 2
    if not attempts and exit_code == 0:
        exit_code = 2
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
