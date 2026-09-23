"""Private frozen-bundle route for the existing independent adapter.

This worker is not an allocation/approval launcher or the public acceptance gate.
Outputs contain private traces; stdout contains counts only. No case rewriting,
selection, retries, planner injection or automatic factual qualification occurs.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import re
import sys
import threading

from .adapter import Driver
from .decisions import DecisionObserver
from .gate import import_hashes_match, imports_match, package_identity, read, sha
from .media_bindings import media_evidence, media_read_observer, runtime_environment
from .quota import QuotaObserver, RequestCapStop, TransportObserver
from .record import fingerprint, write_json
from evaluation.submission_delivery.holdouts import evaluate, load_bundle, relative_file


class QuotaStop(SystemExit):
    pass


class ObserverStop(SystemExit):
    pass


def media_record(case, bundle, freeze):
    assets = {}
    for step in case["steps"]:
        for key, mime in (("audio_ref", "audio/mpeg"), ("image_ref", "image/png")):
            ref = step["event"]["payload"].get(key)
            if ref is not None:
                info = freeze["files"][ref]
                assets[ref] = {"original_ref": ref, "staged": str(relative_file(bundle, ref)),
                               "sha256": info["sha256"], "bytes": info["bytes"],
                               "mime_type": mime, "state": "materialized"}
    return {"assets": list(assets.values()), "media_root": str(bundle), "cwd": str(bundle)}


@contextmanager
def profiles(observe, media):
    if sys.getprofile() is not None or threading.getprofile() is not None:
        raise RuntimeError("Bundle observers refuse to replace an existing profiler")
    threading.setprofile(media)
    sys.setprofile(observe)
    try:
        yield
    finally:
        sys.setprofile(None)
        threading.setprofile(None)


def imported_sources():
    paths = {name: str(Path(module.__file__).resolve()) for name, module in list(sys.modules.items())
             if name.startswith(("participant.", "harness.")) and getattr(module, "__file__", None)}
    return {"imports": paths, "import_sha256": {name: sha(Path(path)) for name, path in paths.items()}}


def source_state(args, freeze):
    return {"submission": fingerprint(args.candidate), "kit": fingerprint(args.kit),
            "reference_kit": fingerprint(args.reference_kit),
            "bundle": {name: sha(relative_file(args.bundle, name))
                       for name in ("FREEZE.json", *freeze["files"])},
            "tooling": fingerprint(Path(__file__).resolve().parents[1])}


def record_cases(args, cases, freeze, runtime):
    """One Driver, actual input only, per case; one transport budget per batch."""
    planner, agent, embedding, media, protocol = runtime
    responses = {getattr(planner.Planner, name).__code__: phase for name, phase in
                 (("_decide", "planning"), ("_perceive_audio", "acoustic"), ("_warmup", "warmup"))}
    responses[embedding.embed_image.__code__] = "embedding"
    functions = {code: ("embedding_return" if phase == "embedding" else "provider_response", phase)
                 for code, phase in responses.items()}
    functions[planner.Planner.plan.__code__] = ("planner_return", "planning")
    functions[agent.ParticipantAgent._apply.__code__] = ("controller_apply", "controller")
    transport = TransportObserver({"generation": args.max_generation_requests,
                                   "embedding": args.max_embedding_requests}, args.cap_generation_model)
    quota = QuotaObserver(responses)
    decisions = DecisionObserver(functions, [os.environ.get(name) for name in
        ("SECRET_GEMINI_API_KEY", "THREAD_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")])
    configurations, media_errors, stop = [], [], None
    rows = [read(args.out / f"attempt-{index:03d}.json") for index in range(1, len(cases) + 1)]
    for case, row in zip(cases, rows):
        path = args.out / f"attempt-{row['attempt']:03d}.json"
        if stop:
            row["reason"] = "unrun_after_" + stop
            write_json(path, row)
            continue
        binding = media_record(case, args.bundle, freeze)
        driver = Driver(case, agent.ParticipantAgent, protocol.validate_action,
                        args.settle_turns, clock_mode="real", injected=False)
        media_capture = media_read_observer(driver, binding, media.MediaLoader)
        model_evidence = []

        def media_observe(frame, event, result):
            if event != "return" or frame.f_code is not media.MediaLoader._read.__code__:
                return
            previous = len(driver.trace)
            media_capture(frame, event, result)
            if any(row.get("kind") == "adapter_error" for row in driver.trace[previous:]):
                # Worker threads signal the main profiler before its next event;
                # raising only in a thread would not reliably stop new dispatch.
                media_errors.append({"attempt": row["attempt"], "error_type": "media_capture_failed"})

        def observer_failed():
            return decisions.errors or quota.errors or media_errors

        def observe(frame, event, result):
            if observer_failed():
                raise ObserverStop(77)
            decisions.capture(frame, event, result)
            if decisions.errors:
                raise ObserverStop(77)
            transport.capture(frame, event, result)
            if event == "return":
                quota.capture(frame)
                if quota.errors:
                    raise ObserverStop(77)
                if quota.rows:
                    raise QuotaStop(75)
                if frame.f_code is planner.Planner.setup.__code__:
                    instance = frame.f_locals.get("self")
                    if instance is not None and instance.client is not None:
                        config = {name: getattr(instance, name, None) for name in
                                  ("model", "thinking", "thinking_budget", "image_embedding", "timeout", "audio_mode")}
                        config["prewarm"] = frame.f_locals.get("prewarm")
                        if config not in configurations:
                            configurations.append(config)
            media_observe(frame, event, result)
            if media_errors:
                raise ObserverStop(77)

        # An independent outer bound; authored event times/tail are unchanged.
        limit = 305 + (max(s["at_ms"] for s in case["steps"]) + case.get("tail_ms", 6000)) / 1000

        async def bounded():
            return await asyncio.wait_for(driver.run(), timeout=limit)

        row.update(status="started", case_wall_seconds=limit)
        write_json(path, row)  # Persist entry before setup, media reads or transport.
        try:
            with runtime_environment(binding), planner.planner_trace(model_evidence.append), profiles(observe, media_observe):
                asyncio.run(bounded())
            if observer_failed():
                raise ObserverStop(77)
            row["status"] = "returned"
        except RequestCapStop:
            row["status"] = stop = "request_cap_stopped"
        except QuotaStop:
            row["status"] = stop = "quota_stopped"
        except ObserverStop:
            row["status"] = stop = "observer_stopped"
        except (Exception, SystemExit) as exc:
            row.update(status="execution_error", error_type=type(exc).__name__)
            stop = "execution_error"
        finally:
            row.update(trace=driver.trace, model_evidence=model_evidence,
                       transport_requests=list(transport.rows), http429_metadata=list(quota.rows),
                       decision_evidence=list(decisions.rows), request_budget=transport.budget(),
                       observer_errors={"decisions": list(decisions.errors), "quota": list(quota.errors),
                                        "media": list(media_errors)},
                       **imported_sources())
            write_json(path, row)
            transport.rows.clear()
            quota.rows.clear()
            decisions.rows.clear()
    return {"attempts": [{key: row[key] for key in ("attempt", "id", "mode", "status")} for row in rows],
            "stop_reason": stop, "request_budget": transport.budget(),
            "effective_runtime_configurations": configurations,
            "observer_errors": {"transport": transport.errors, "quota": quota.errors,
                                "decisions": decisions.errors, "media": media_errors}}


def execute(args):
    identity = package_identity(args.candidate, args.reference_kit)
    if not identity["valid"] or identity["archive_sha256"] != args.archive_sha256:
        raise ValueError("Candidate package does not match its separately reviewed archive")
    cases, answers, freeze = load_bundle(args.bundle, args.freeze_sha256)
    del answers  # The participant/Driver never receives expectations; review loads them separately.
    if len(cases) > args.provider_case_limit:
        raise ValueError("Frozen bundle exceeds the declared case limit; no subset is selected")
    before = source_state(args, freeze)
    official = {name: digest for name, digest in before["reference_kit"].items() if name != "submission.yaml"}
    if any(before["kit"].get(name) != digest for name, digest in official.items()):
        raise ValueError("Runtime kit differs from original kit")
    args.out.mkdir(parents=True, exist_ok=False)
    manifest = {"kind": "independent-frozen-bundle-v1", "argv": sys.argv,
                "started_utc": datetime.now(timezone.utc).isoformat(),
                "submission": str(args.candidate), "kit": str(args.kit),
                "reference_kit": str(args.reference_kit), "bundle": str(args.bundle),
                "freeze_sha256": args.freeze_sha256, "package_identity": identity,
                "fingerprints_before": before, "python_version": sys.version, "platform": sys.platform,
                "selected": [{"id": case["id"], "mode": case["mode"]} for case in cases],
                "request_caps": {"generation": args.max_generation_requests, "embedding": args.max_embedding_requests},
                "cap_generation_model": args.cap_generation_model,
                "clock": "real", "injected": False, "settle_turns": args.settle_turns,
                "environment": {name: os.environ.get(name) for name in
                    ("PARTICIPANT_MODEL", "PARTICIPANT_THINKING_LEVEL", "PARTICIPANT_THINKING_BUDGET",
                     "PARTICIPANT_IMAGE_EMBEDDING", "PARTICIPANT_PREWARM", "PARTICIPANT_TIMEOUT_SECONDS",
                     "PARTICIPANT_AUDIO_MODE")},
                "limitations": ["Synthetic authored media; no human-recording/photo robustness claim.",
                    "Read-only profilers and hashing add overhead; event times are not scaled.",
                    "Private expectations are never passed to Driver; shared-host isolation is procedural.",
                    "Separate approved allocation/freezer/one-use launcher is required before live use.",
                    "Execution completion is not an oracle pass or factual qualification."]}
    write_json(args.out / "manifest.json", manifest)
    for index, case in enumerate(cases, 1):
        write_json(args.out / f"attempt-{index:03d}.json", {
            "attempt": index, "id": case["id"], "mode": case["mode"], "status": "unrun",
            "clock": "real", "injected": False, "trace": []})
    try:
        if args.env_file:
            from dotenv import load_dotenv
            load_dotenv(args.env_file.resolve(), override=False)
            manifest["environment"] = {name: os.environ.get(name) for name in manifest["environment"]}
        sys.path[:0] = [str(args.candidate), str(args.kit)]
        runtime = [importlib.import_module(name) for name in
                   ("participant.planner", "participant.agent", "participant.embedding", "participant.media", "harness.protocol")]
        imports = imported_sources()
        if not imports_match(imports, manifest) or not import_hashes_match(imports, manifest):
            raise ValueError("Imported participant or harness differs from pinned source")
        manifest.update(record_cases(args, cases, freeze, runtime))
    except (Exception, SystemExit) as exc:
        manifest.update(stop_reason="worker_error", error_type=type(exc).__name__)
    finally:
        manifest["attempts"] = [{key: row[key] for key in ("attempt", "id", "mode", "status")}
            for index in range(1, len(cases) + 1) for row in [read(args.out / f"attempt-{index:03d}.json")]]
        try:
            after = source_state(args, freeze)
        except (OSError, ValueError):
            after = None
        manifest.update(fingerprints_after=after, sources_unchanged=before == after,
                        finished_utc=datetime.now(timezone.utc).isoformat())
        write_json(args.out / "manifest.json", manifest)
        write_json(args.out / "attempt-index.json", manifest.get("attempts", []))
        write_json(args.out / "evidence-sha256.json", {p.name: sha(p) for p in args.out.iterdir()
                                                      if p.is_file() and p.name != "evidence-sha256.json"})
    passed = (not manifest.get("stop_reason") and manifest["sources_unchanged"]
              and len(manifest.get("attempts", [])) == len(cases)
              and not any(manifest.get("observer_errors", {"missing": True}).values()))
    return {"execution_complete": passed, "statuses": dict(Counter(r["status"] for r in manifest.get("attempts", []))),
            "semantic_qualification": False, "request_budget": manifest.get("request_budget")}


def embedding_matches(row, binding):
    """Submitted vectors must match buffered native values and actual transport."""
    images = {a["original_ref"]: a for a in binding["assets"] if a["mime_type"].startswith("image/")}
    current = None
    for event in row["trace"]:
        if event.get("kind") == "event" and event.get("event_type") == "video_frame":
            current = images.get(event.get("payload", {}).get("image_ref"))
        if event.get("action") != "tool_call" or "image_embedding" not in (event.get("args") or {}):
            continue
        vector = event["args"]["image_embedding"]
        if not current or not isinstance(vector, list) or not vector or not any(vector):
            return False
        if not any(d.get("stage") == "embedding_return"
                   and d.get("provider_response", {}).get("http_status") == 200
                   and d.get("provider_response", {}).get("embedding_values") == vector
                   and (d.get("value") or {}).get("values") == vector
                   and d.get("runtime_metadata", {}).get("input_sha256") == current["sha256"]
                   and d.get("runtime_metadata", {}).get("input_bytes") == current["bytes"]
                   and any(t.get("body_sha256") == d.get("request_body_sha256") and real_transport(t, ":embedContent")
                           for t in row.get("transport_requests", [])) for d in row.get("decision_evidence", [])):
            return False
    return True


def real_transport(row, suffix):
    return (row.get("status") == 200 and row.get("transport") == "AsyncHTTPTransport"
            and row.get("host") == "generativelanguage.googleapis.com" and row.get("path", "").endswith(suffix))


def local_text_outcome(case, row, verdict):
    """A returned/applied local plan and trace obligations, never absence of calls."""
    if (case["mode"] != "e2e_text" or not verdict["passed"] or row.get("status") != "returned"
            or any(key in step["event"]["payload"] for step in case["steps"] for key in ("audio_ref", "image_ref"))
            or any(event.get("kind") in {"adapter_error", "protocol_error", "agent_crash"} for event in row["trace"])):
        return False
    evidence = row.get("decision_evidence", [])
    applied = [(i, d) for i, d in enumerate(evidence) if d.get("stage") == "controller_apply"]
    returns = [(i, d) for i, d in enumerate(evidence) if d.get("stage") == "planner_return"]
    planning = [e for e in row.get("model_evidence", []) if e.get("phase") in {"local_planning", "planning"}]
    if not applied or not returns or not planning or not isinstance(applied[-1][1].get("decision"), dict):
        return False
    apply_index, last = applied[-1]
    return_index, returned = returns[-1]
    terminal = planning[-1]
    revision = last.get("revision")
    # Tool-result continuations may keep the same revision. Only the terminal
    # planning record/return can establish provenance for the final apply;
    # older local markers and later unapplied returns are insufficient.
    return (type(revision) is int and terminal.get("phase") == "local_planning"
            and terminal.get("status") == "local" and terminal.get("revision") == revision
            and terminal.get("input_media") == [] and return_index < apply_index
            and returned.get("return_state") == "returned" and returned.get("revision") == revision
            and returned.get("value") == last["decision"])


def review(args):
    cases, answers, freeze = load_bundle(args.bundle, args.freeze_sha256)
    evidence = args.review_evidence
    manifest = read(evidence / "manifest.json")
    rows = [read(evidence / f"attempt-{i:03d}.json") for i in range(1, len(cases) + 1)]
    index = read(evidence / "evidence-sha256.json")
    process = read(evidence / "process-status.json")
    required = {"manifest.json", "attempt-index.json", "process-status.json", "process-console.log"}
    required.update(f"attempt-{i:03d}.json" for i in range(1, len(cases) + 1))
    identity = package_identity(args.candidate, args.reference_kit)
    checks = {
        "frozen_identity": manifest.get("freeze_sha256") == args.freeze_sha256,
        "package_identity": identity["valid"] and identity["archive_sha256"] == args.archive_sha256
        and identity == manifest.get("package_identity"),
        "complete_unchanged_order": manifest.get("selected") == [{"id": c["id"], "mode": c["mode"]} for c in cases]
        and [(r["attempt"], r["id"], r["mode"]) for r in rows] == [(i, c["id"], c["mode"]) for i, c in enumerate(cases, 1)],
        "all_returned": all(r["status"] == "returned" and r.get("clock") == "real" and r.get("injected") is False for r in rows),
        "index_complete": read(evidence / "attempt-index.json") == manifest.get("attempts")
        == [{key: row[key] for key in ("attempt", "id", "mode", "status")} for row in rows],
        "sources_unchanged": manifest.get("sources_unchanged") is True and manifest.get("fingerprints_before")
        == manifest.get("fingerprints_after") == source_state(args, freeze),
        "imports_pinned": all(imports_match(r, manifest) and import_hashes_match(r, manifest) for r in rows),
        "observers_clean": not any(manifest.get("observer_errors", {"missing": True}).values()),
        "runtime_configuration": len(manifest.get("effective_runtime_configurations", [])) == 1
        and manifest["effective_runtime_configurations"][0].get("model") == manifest.get("cap_generation_model"),
        "supervised_completion": process.get("worker") == "adapter" and process.get("completed") is True
        and process.get("timed_out") is False and process.get("exit_code") == 0,
        "hashed_receipts": required <= set(index) and all(Path(name).name == name and
            (evidence / name).is_file() and sha(evidence / name) == digest for name, digest in index.items()),
    }
    budget = manifest.get("request_budget") or {}
    caps = manifest.get("request_caps") or {}
    checks["bounded_requests"] = (set(caps) == {"generation", "embedding"} and budget.get("limits") == caps
        and not budget.get("blocked_before_transport") and not manifest.get("stop_reason")
        and all(type(caps[k]) is int and type(budget.get("admitted_starts", {}).get(k)) is int
                and 0 <= budget["admitted_starts"][k] <= caps[k] for k in caps)
        and sum(budget.get("admitted_starts", {}).values()) == sum(len(r.get("transport_requests", [])) for r in rows))
    results = []
    for case, row in zip(cases, rows):
        binding = media_record(case, args.bundle, freeze)
        verdict = evaluate(case, answers[case["id"]], row["trace"])
        generation = any(real_transport(t, ":generateContent") for t in row.get("transport_requests", []))
        native = any(d.get("stage") == "provider_response" and d.get("phase") == "planning"
                     and d.get("provider_response", {}).get("http_status") == 200
                     and any(t.get("body_sha256") == d.get("request_body_sha256") and real_transport(t, ":generateContent")
                             for t in row.get("transport_requests", [])) for d in row.get("decision_evidence", []))
        local = local_text_outcome(case, row, verdict)
        execution_evidence = (("local_text_with_native_history" if native else "local_text_no_native") if local else
                              "native_planning_observed" if generation and native else "no_verified_local_or_native_outcome")
        results.append({"attempt": row["attempt"], "oracle": verdict,
                        "media": media_evidence(case, binding, row.get("model_evidence", [])),
                        "real_generation": generation, "native_planning": native,
                        "execution_evidence": execution_evidence, "local_text_outcome": local,
                        "execution_evidence_valid": local or generation and native,
                        "embedding_values_match": embedding_matches(row, binding)})
    checks["actual_provider_media_and_decisions"] = all(r["media"]["passed"] and r["execution_evidence_valid"]
        and r["embedding_values_match"] for r in results)
    return {"evidence_valid": all(checks.values()), "checks": checks, "attempts": results,
            "oracle_passes": sum(r["oracle"]["passed"] for r in results), "authored_cases": len(cases),
            "semantic_qualification": False,
            "required_review": "Private factual review of the actual answer, unsupported extra claims and useful task completion remains required."}


def main(args, parser):
    if args.cases or args.oracle or args.partition or args.family or args.case_mode or args.first_per_family or args.limit or args.block_family:
        parser.error("--bundle preserves the entire frozen input order; legacy cases/oracle/selectors are forbidden")
    if not args.reference_kit or not all(re.fullmatch(r"[0-9a-f]{64}", value or "")
                                         for value in (args.freeze_sha256, args.archive_sha256)):
        parser.error("--bundle requires --reference-kit and separately reviewed --freeze-sha256/--archive-sha256")
    if args.settle_turns < 20 or not 1 <= args.provider_case_limit <= 60:
        parser.error("Invalid settle turns or case limit")
    if not args.review_evidence and (sys.version_info[:2] != (3, 11) or args.execution != "real-provider" or args.clock != "real"
        or any(type(n) is not int or n < 0 for n in (args.max_generation_requests, args.max_embedding_requests))
        or not re.fullmatch(r"gemini-[A-Za-z0-9._-]{1,80}", args.cap_generation_model or "")):
        parser.error("Bundle execution requires Python 3.11, real-provider/real clock, both request caps and an exact generation model")
    if args.review_evidence and args.env_file:
        parser.error("Read-only review does not load credentials")
    for name in ("candidate", "kit", "reference_kit", "bundle", "out", "review_evidence"):
        if getattr(args, name) is not None:
            setattr(args, name, getattr(args, name).resolve())
    roots = (args.candidate, args.kit, args.reference_kit, args.bundle, Path(__file__).resolve().parents[2])
    if args.out.exists() or any(args.out.is_relative_to(root) for root in roots) or (
            args.review_evidence and args.out.is_relative_to(args.review_evidence)):
        parser.error("--out must be new and outside frozen roots, tooling and prior evidence")
    sys.dont_write_bytecode = True
    if args.review_evidence:
        result = review(args)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, ensure_ascii=False)
        print(json.dumps({key: result[key] for key in ("evidence_valid", "oracle_passes", "authored_cases", "semantic_qualification")}))
        raise SystemExit(0 if result["evidence_valid"] else 1)
    result = execute(args)
    print(json.dumps(result))
    raise SystemExit(0 if result["execution_complete"] else 1)
