"""Exercise frozen original invalid-media fixtures with the actual participant, offline.

Run as ``python -B -m evaluation.samsung_acceptance.invalid_media_offline``. Required:
--candidate DIR --kit DIR --cases original/development.jsonl --cases original/holdout.jsonl
--case-mode e2e_audio|e2e_visual --bindings FILE --bindings-sha256 SHA --asset-root DIR --out NEW_DIR.

This is a real-clock invalid-media regression, not a provider/media-understanding gate.
Every HTTP request raises through MockTransport; socket connections are denied except
the OS socketpair used by asyncio. No decisions or response speeches are supplied.
The media-read profiler's overhead remains inside the measured execution.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
from unittest.mock import patch

import httpx

from .adapter import Driver
from .media_bindings import (assets_unchanged, invalid_media_attempts, load_bindings,
                             observe_media_reads, runtime_environment, stage_case)
from .record import fingerprint


MAX_ATTEMPTS = 32
OFFLINE_CONFIG = {"SECRET_GEMINI_API_KEY": "offline-invalid-media-nonsecret-sentinel",
                  "PARTICIPANT_PREWARM": "0", "PARTICIPANT_IMAGE_EMBEDDING": "0",
                  "THREAD_PROVIDER": "gemini"}
INVALID_STATES = {"expected_absent", "staged_corrupt"}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


@contextmanager
def offline_environment(attempts):
    """Verifier socket-guard pattern, restricted to the socketpair construction."""
    names = [name for name in os.environ if name.startswith(("PARTICIPANT_", "THREAD_"))
             or name in {"SECRET_GEMINI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"}]
    previous = {name: os.environ.pop(name) for name in names}
    original_pair, original_dns = socket.socketpair, socket.getaddrinfo
    pair_scope = threading.local()

    def deny(operation):
        attempts.append({"operation": operation})
        raise RuntimeError("Network disabled during offline invalid-media evaluation")

    def socketpair(*args, **kwargs):
        active = getattr(pair_scope, "active", False)
        pair_scope.active = True
        try:
            return original_pair(*args, **kwargs)
        finally:
            pair_scope.active = active

    def connect_guard(original, operation):
        def guarded(sock, address):
            if (getattr(pair_scope, "active", False) and isinstance(address, tuple)
                    and address[0] in {"127.0.0.1", "::1"}):
                return original(sock, address)
            return deny(operation)
        return guarded

    def dns(host, *args, **kwargs):
        if getattr(pair_scope, "active", False) and host in {"localhost", "127.0.0.1", "::1"}:
            return original_dns(host, *args, **kwargs)
        return deny("getaddrinfo")

    def datagram(*args, **kwargs):
        return deny("sendto_or_sendmsg")

    try:
        with ExitStack() as stack:
            for name in ("connect", "connect_ex"):
                stack.enter_context(patch.object(socket.socket, name,
                    connect_guard(getattr(socket.socket, name), name)))
            for name in ("sendto", "sendmsg"):
                if hasattr(socket.socket, name):
                    stack.enter_context(patch.object(socket.socket, name, datagram))
            stack.enter_context(patch.object(socket, "socketpair", socketpair))
            stack.enter_context(patch.object(socket, "getaddrinfo", dns))
            stack.enter_context(patch.dict(os.environ, OFFLINE_CONFIG))
            yield
    finally:
        os.environ.update(previous)


def frozen_cases(paths, mode):
    selected, seen, inputs, oracle_path = [], set(), {}, None
    for path in paths:
        raw = path.read_bytes()
        freeze_path = path.parent / "FREEZE.json"
        freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
        if (freeze.get("version") != "2026-09-21.1"
                or freeze["files"][path.name]["sha256"] != hashlib.sha256(raw).hexdigest()):
            raise ValueError("Cases must match the original authored freeze: " + str(path))
        source_oracle = (path.parent.parent / "oracle.py").resolve()
        if digest(source_oracle) != freeze["authoring_source_sha256"]["oracle.py"]:
            raise ValueError("Original oracle differs from its frozen identity")
        if oracle_path is not None and source_oracle != oracle_path:
            raise ValueError("All input files must share the same original oracle")
        oracle_path = source_oracle
        inputs.update({str(path): hashlib.sha256(raw).hexdigest(), str(freeze_path): digest(freeze_path)})
        for line_number, line in enumerate(raw.splitlines(), 1):
            if not line.strip():
                continue
            case = json.loads(line)
            if case["mode"] != mode or case["family"] not in {"media_missing", "media_corrupt"}:
                continue
            if case["id"] in seen:
                raise ValueError("Duplicate selected original case: " + case["id"])
            seen.add(case["id"])
            media = [r for r in case.get("requirements", []) if r.get("kind") == "media_asset"]
            operation = "ensure_absent" if case["family"] == "media_missing" else "write_bytes"
            if (case["version"] != freeze["version"] or case.get("injected_plans") or not media
                    or any(r.get("stage", {}).get("operation") != operation for r in media)):
                raise ValueError("Unexpected original invalid-media contract: " + case["id"])
            selected.append((case, hashlib.sha256(line).hexdigest(), str(path), line_number))
    if not selected:
        raise ValueError("No original invalid-media cases match --case-mode")
    return selected, inputs, oracle_path


def snapshot(args, inputs, oracle_path):
    return {"candidate": fingerprint(args.candidate), "kit": fingerprint(args.kit),
            "asset_root": fingerprint(args.asset_root),
            "inputs": {path: digest(path) for path in inputs},
            "bindings": digest(args.bindings), "oracle": digest(oracle_path),
            "tooling": {p.name: digest(p) for p in sorted(Path(__file__).parent.glob("*.py"))}}


def imported_sources(candidate, kit):
    found = {}
    for name, module in tuple(sys.modules.items()):
        if not name.startswith(("participant", "harness")) or not getattr(module, "__file__", None):
            continue
        path = Path(module.__file__).resolve()
        expected = candidate / "participant" if name.startswith("participant") else kit / "harness"
        if not path.is_relative_to(expected):
            raise RuntimeError("Wrong runtime import: " + name + " from " + str(path))
        found[name] = {"path": str(path), "sha256": digest(path)}
    return found


def rejecting_transport(requests):
    def reject(request):
        requests.append({"method": request.method, "scheme": request.url.scheme,
                         "host": request.url.host, "path": request.url.path})
        raise httpx.ConnectError("Every HTTP request is forbidden in this offline runner", request=request)
    return httpx.MockTransport(reject)


def assess(record, trace, verdict, requests, socket_attempts, constructions):
    access = invalid_media_attempts(record, trace)
    errors = {item["media_ref"] for item in trace if item.get("kind") == "media_access"
              and item.get("status") == "read_error"}
    calls = [item for item in trace if item.get("kind") == "action" and item.get("action") == "tool_call"]
    shutdown = [item for item in trace if item.get("kind") == "shutdown"]
    checks = {"original_oracle_pass": verdict["passed"], "invalid_media_attempts": access["passed"],
              "every_original_ref_has_read_error": bool(access["expected_refs"])
              and set(access["expected_refs"]) <= errors,
              "no_http_requests": not requests, "no_socket_attempts": not socket_attempts,
              "no_tool_calls": not calls, "assets_unchanged": assets_unchanged(record),
              "clean_shutdown": len(shutdown) == 1 and shutdown[0].get("pending_tasks") == 0
              and shutdown[0].get("planner_closed") is True
              and not any(item.get("kind") == "agent_exit" and not item.get("at_shutdown") for item in trace),
              "actual_participant_constructed_once": constructions == 1}
    return {"status": "passed" if all(checks.values()) else "failed", "checks": checks,
            "verdict": verdict, "invalid_media_attempts": access,
            "observed_read_error_refs": sorted(errors), "tool_calls": calls}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("candidate", "kit", "bindings", "asset-root", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--cases", type=Path, action="append", required=True)
    parser.add_argument("--case-mode", choices=("e2e_audio", "e2e_visual"), required=True)
    parser.add_argument("--bindings-sha256", required=True)
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    for name in ("candidate", "kit", "bindings", "asset_root", "out"):
        setattr(args, name, getattr(args, name).resolve())
    args.cases = [path.resolve() for path in args.cases]
    if args.out.exists():
        parser.error("--out exists; preserve every attempt in a new directory")
    protected = [args.candidate, args.kit, args.asset_root, *(path.parent for path in args.cases)]
    if any(args.out.is_relative_to(path) for path in protected):
        parser.error("--out must be outside candidate, kit, assets and frozen case directories")
    selected, inputs, oracle_path = frozen_cases(args.cases, args.case_mode)
    if digest(args.bindings) != args.bindings_sha256:
        raise ValueError("Bindings differ from the predeclared SHA-256")
    bindings = load_bindings(args.bindings)
    before = snapshot(args, inputs, oracle_path)
    if before["bindings"] != args.bindings_sha256 or before["inputs"] != inputs:
        raise ValueError("Inputs changed while preparing the run")
    args.out.mkdir(parents=True, exist_ok=False)
    manifest = {"started_utc": datetime.now(timezone.utc).isoformat(), "argv": sys.argv,
                "python": sys.executable, "python_version": sys.version, "httpx_version": httpx.__version__,
                "scope": "Authored original invalid-media offline regression; no model generation or full acceptance gate",
                "clock": "real monotonic clock; scale one; original events, delays and tail unchanged",
                "factory": "Actual ParticipantAgent(in_queue, out_queue, planner=actual Planner(transport=httpx.MockTransport(reject_every_request))); Driver injected=False",
                "observer": "Read-only candidate MediaLoader._read profiler; receipt timestamps; overhead included",
                "offline_config": OFFLINE_CONFIG, "case_mode": args.case_mode, "selected": len(selected),
                "maximum_attempts": MAX_ATTEMPTS, "candidate": str(args.candidate), "kit": str(args.kit),
                "asset_root": str(args.asset_root), "bindings": str(args.bindings), "oracle": str(oracle_path),
                "before": before}
    write_new(args.out / "inputs.json", manifest)
    prepared = []
    for case, line_sha, source, line_number in selected:
        binding = bindings.get(case["id"])
        assets = binding.get("assets", []) if binding else []
        eligible = (binding and binding.get("variant") in {"exact_original", "original-invalid"}
                    and assets and all(a.get("state") in INVALID_STATES for a in assets))
        if eligible:
            runtime_case, record = stage_case(case, line_sha, binding, args.asset_root,
                                              args.out / "media-staging", args.kit, "original")
        else:
            runtime_case, record = None, {"case_id": case["id"], "status": "blocked", "executed": False,
                "original_recipe": True, "reason": "Missing original expected_absent/staged_corrupt binding"}
        prepared.append((case, runtime_case, record, {"id": case["id"], "family": case["family"],
            "mode": case["mode"], "partition": case["partition"], "source": source, "source_line": line_number,
            "source_line_sha256": line_sha, "attempted": False, "asset_binding": record}))
    write_new(args.out / "asset-preflight.json", [item[2] for item in prepared])
    rows, network_attempts, imports_before = [], [], {}
    attempted, fatal_error, stop_reason = 0, None, None
    started = time.monotonic()
    with (args.out / "results.jsonl").open("x", encoding="utf-8", newline="\n") as logfile:
        def retain(row):
            logfile.write(json.dumps(row, ensure_ascii=False) + "\n")
            logfile.flush()
            rows.append(row)

        try:
            with offline_environment(network_attempts):
                sys.path.insert(0, str(args.candidate))
                sys.path.insert(1, str(args.kit))
                agent_module = importlib.import_module("participant.agent")
                planner_module = importlib.import_module("participant.planner")
                media_module = importlib.import_module("participant.media")
                protocol = importlib.import_module("harness.protocol")
                imports_before = imported_sources(args.candidate, args.kit)
                if network_attempts:
                    raise RuntimeError("Runtime import attempted socket access")
                spec = importlib.util.spec_from_file_location("invalid_media_original_oracle", oracle_path)
                oracle = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(oracle)
                for case, runtime_case, record, row in prepared:
                    if stop_reason or attempted >= MAX_ATTEMPTS or runtime_case is None:
                        row.update(status="blocked", reason=stop_reason or ("Hard attempt cap reached"
                                   if attempted >= MAX_ATTEMPTS else record["reason"]))
                        retain(row)
                        continue
                    if not assets_unchanged(record):
                        row.update(status="blocked", reason="Assets changed after staging; no participant attempt")
                        retain(row)
                        continue
                    attempted += 1
                    row["attempted"] = True
                    requests, evidence, instances = [], [], []
                    network_start = len(network_attempts)

                    def actual_agent(in_queue, out_queue):
                        planner = planner_module.Planner(transport=rejecting_transport(requests))
                        agent = agent_module.ParticipantAgent(in_queue, out_queue, planner=planner)
                        instances.append(agent)
                        return agent

                    driver = Driver(runtime_case, actual_agent, protocol.validate_action,
                                    settle_turns=40, clock_mode="real", injected=False)

                    async def run_native():
                        try:
                            return await driver.run()
                        finally:
                            # Driver cannot close an agent whose setup failed before its run-finally.
                            for agent in instances:
                                await agent.close()

                    try:
                        with runtime_environment(record), planner_module.planner_trace(evidence.append), \
                             observe_media_reads(driver, record, media_module.MediaLoader):
                            trace = asyncio.run(run_native())
                    except Exception as exc:
                        trace = driver.trace + [{"kind": "adapter_error", "t_ms": driver.now,
                                                "error": f"{type(exc).__name__}: {exc}"}]
                    record["executed"] = bool(instances)
                    row.update(trace=trace, model_evidence=evidence, http_requests=requests,
                               socket_attempts=network_attempts[network_start:])
                    verdict = oracle.evaluate_case(case, trace)
                    row.update(assess(record, trace, verdict, requests, network_attempts[network_start:], len(instances)))
                    retain(row)
                    if requests or len(network_attempts) > network_start:
                        stop_reason = "Unexecuted after forbidden HTTP/socket attempt; first failure retained"
        except Exception as exc:
            fatal_error = f"{type(exc).__name__}: {exc}"
            for _, _, _, row in prepared[len(rows):]:
                retain({**row, "status": "blocked" if not row["attempted"] else "failed", "reason": fatal_error})
    finalization_errors = []
    try:
        after = snapshot(args, inputs, oracle_path)
    except Exception as exc:
        after = {"snapshot_error": f"{type(exc).__name__}: {exc}"}
        finalization_errors.append(after["snapshot_error"])
    try:
        imports_after = imported_sources(args.candidate, args.kit)
    except Exception as exc:
        imports_after = {}
        finalization_errors.append(f"{type(exc).__name__}: {exc}")
    imports_unchanged = all(imports_after.get(name) == value for name, value in imports_before.items())
    for name, item in imports_after.items():
        category = "candidate" if name.startswith("participant") else "kit"
        root = args.candidate if category == "candidate" else args.kit
        imports_unchanged &= before[category].get(Path(item["path"]).relative_to(root).as_posix()) == item["sha256"]
    passed = (not fatal_error and not finalization_errors and not network_attempts and before == after and imports_unchanged
              and bool(rows) and all(row["status"] == "passed" for row in rows))
    manifest.update(finished_utc=datetime.now(timezone.utc).isoformat(), elapsed_s=time.monotonic() - started,
                    passed=passed, attempted=attempted, counts=dict(Counter(row["status"] for row in rows)),
                    provider_generations=0, http_request_attempts=sum(len(row.get("http_requests", [])) for row in rows),
                    socket_attempts=network_attempts, fatal_error=fatal_error, stop_reason=stop_reason,
                    finalization_errors=finalization_errors,
                    after=after, sources_unchanged=before == after,
                    imports_before=imports_before, imports_after=imports_after, imports_unchanged=imports_unchanged)
    write_new(args.out / "manifest.json", manifest)
    write_new(args.out / "summary.json", [{k: v for k, v in row.items() if k != "trace"} for row in rows])
    write_new(args.out / "evidence-sha256.json", {p.name: digest(p) for p in sorted(args.out.iterdir()) if p.is_file()})
    print(json.dumps({"passed": passed, "attempted": attempted, "counts": manifest["counts"],
                      "out": str(args.out), "provider_generations": 0}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
