"""Recompute strict full-batch gates from retained evidence, without executing agents.

Official scores and original traces remain immutable. Delivery-relative timing is
diagnostic only; it never replaces the official nominal-timestamp requirement.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import zipfile

from .audit import SPOKEN, audit_public, text
from .record import fingerprint


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def coverage(rows, scenario_ids, reps=3):
    return (len(scenario_ids) == 9 and len(set(scenario_ids)) == 9
            and Counter(r["scenario_id"] for r in rows) == Counter({sid: reps for sid in scenario_ids})
            and [r["attempt"] for r in rows] == list(range(1, len(scenario_ids) * reps + 1)))


def imports_match(row, manifest):
    def normal(path):
        value = str(path).replace("\\", "/").rstrip("/")
        return value.casefold() if ":" in value[:3] else value
    imports = row.get("imports", {})
    return "participant.agent" in imports and "participant.planner" in imports and all(
        normal(path).startswith(normal(manifest["submission" if name.startswith("participant") else "kit"]) + "/"
                                + ("participant" if name.startswith("participant") else "harness") + "/")
        for name, path in imports.items())


def import_hashes_match(row, manifest):
    hashes = row.get("import_sha256", {})
    if not hashes or set(hashes) != set(row.get("imports", {})):
        return False
    for name, path in row["imports"].items():
        root = "submission" if name.startswith("participant") else "kit"
        prefix = str(manifest[root]).replace("\\", "/").rstrip("/") + "/"
        relative = str(path).replace("\\", "/")[len(prefix):]
        if hashes[name] != manifest["fingerprints_before"][root].get(relative):
            return False
    return True


def evidence_hashes_match(evidence, attempt_paths):
    index = read(evidence / "evidence-sha256.json") if (evidence / "evidence-sha256.json").is_file() else {}
    required = {"manifest.json", "official-report.json", "attempt-index.json", "console.log",
                "process-status.json", "process-console.log"}
    required.update(path.name for path in attempt_paths)
    return required <= set(index) and all(
        Path(name).name == name and (evidence / name).is_file() and sha(evidence / name) == digest
        for name, digest in index.items())


def package_identity(candidate, reference):
    manifest = read(candidate / "PACKAGE_MANIFEST.json")
    archive = candidate.with_name(candidate.name + ".zip")
    expected = {**manifest["files"], "PACKAGE_MANIFEST.json": sha(candidate / "PACKAGE_MANIFEST.json")}
    reference_files = {k: v for k, v in fingerprint(reference).items() if k != "submission.yaml"}
    with zipfile.ZipFile(archive) as zipped:
        archive_valid = (len(zipped.namelist()) == len(expected) and set(zipped.namelist()) == set(expected)
                         and zipped.testzip() is None and all(
                             hashlib.sha256(zipped.read(k)).hexdigest() == v for k, v in expected.items()))
    checks = {"archive_matches_manifest": archive_valid,
              "extracted_matches_manifest": fingerprint(candidate) == expected,
              "original_submission_yaml_provenance": manifest.get("original_submission_yaml_sha256")
              == sha(reference / "submission.yaml"),
              "official_files_unchanged": manifest["official_kit_files"] == reference_files
              and all(expected.get(k) == v for k, v in reference_files.items())}
    return {"archive_sha256": sha(archive), "manifest_sha256": expected["PACKAGE_MANIFEST.json"],
            "runtime_sha256": {k: v for k, v in expected.items() if k.startswith("participant/")},
            "checks": checks, "valid": all(checks.values())}


def timing_diagnostics(scenario, trace):
    deliveries = [(i, e) for i, e in enumerate(trace) if e.get("kind") == "event"
                  and e.get("event_type") not in {"tool_manifest", "scenario_end"}]
    result = []
    for requirement in scenario.get("ground_truth", {}).get("latency", {}).get("respond_to", []):
        n = requirement["event_index"]
        if n >= len(deliveries):
            continue
        index, event = deliveries[n]
        speech = next((e for e in trace[index + 1:] if e.get("kind") == "action"
                       and e.get("action") in SPOKEN and len(text(e)) >= 3
                       and sum(c.isalpha() for c in text(e)) / len(text(e)) >= .5), None)
        nominal = scenario["events"][n]["timestamp_ms"]
        result.append({"event_index": n, "nominal_ms": nominal, "delivered_ms": event["t_ms"],
                       "first_following_speech_ms": speech["t_ms"] if speech else None,
                       "delivery_relative_ms": speech["t_ms"] - event["t_ms"] if speech else None,
                       "speech_before_nominal": bool(speech and speech["t_ms"] < nominal),
                       "changes_official_or_strict_gate": False})
    return result


def review_batch(evidence, candidate, reference, registry):
    manifest = read(evidence / "manifest.json")
    official = read(evidence / "official-report.json") if (evidence / "official-report.json").exists() else {}
    process = read(evidence / "process-status.json") if (evidence / "process-status.json").exists() else {}
    index = read(evidence / "attempt-index.json") if (evidence / "attempt-index.json").exists() else []
    scenarios = {s["scenario_id"]: s for p in sorted((reference / "scenarios").glob("*.json"))
                 for s in [read(p)]}
    paths = sorted(evidence.glob("attempt-[0-9][0-9][0-9]-*.json"))
    rows = [read(p) for p in paths]
    audits = [audit_public(scenarios[r["scenario_id"]], r["trace"], r.get("score") or {}, registry,
                           r.get("model_evidence"), candidate) for r in rows]
    checks = {"complete_kit9x3": coverage(rows, list(scenarios)),
              "actual_participant_scale1": manifest.get("mode") == "real-provider"
              and manifest.get("reps") == official.get("reps") == 3
              and manifest.get("time_scale") == official.get("time_scale") == 1,
              "official_exit_success": manifest.get("official_exit_code") == 0,
              "official_process_success": process.get("completed") is True
              and process.get("exit_code") == 0 and process.get("timed_out") is False,
              "original_scenarios_selected": manifest.get("selected_scenarios") == {
                  p.name: sha(p) for p in sorted((reference / "scenarios").glob("*.json"))},
              "official_limits_preserved": bool(rows) and all(r.get("official_limits") == {
                  "time_scale": 1, "wall_cap_s": 120, "setup_cap_s": 300} for r in rows),
              "observers_clean": not manifest.get("observer_errors") and not manifest.get("quota_observer_errors")
              and not manifest.get("transport_observer_errors"),
              "sources_unchanged": manifest.get("sources_unchanged") is True
              and manifest.get("fingerprints_before") == manifest.get("fingerprints_after"),
              "frozen_candidate_matches_run": manifest["fingerprints_before"]["submission"] == fingerprint(candidate),
              "recorded_imports_match_frozen_roots": all(imports_match(r, manifest) for r in rows),
              "imported_bytes_match_frozen_sources": all(import_hashes_match(r, manifest) for r in rows),
              "acceptance_tooling_unchanged": manifest.get("acceptance_source_sha256")
              == manifest.get("acceptance_source_sha256_after") and bool(manifest.get("acceptance_source_sha256")),
              "runtime_configuration_recorded": len(manifest.get("effective_runtime_configurations", [])) == 1,
              "transport_attempts_recorded": bool(rows) and all(isinstance(r.get("transport_requests"), list) for r in rows),
              "all_attempts_finished_and_indexed": [r.get("attempt") for r in index] == [r["attempt"] for r in rows]
              and index == manifest.get("attempts") and all(r.get("status") == "returned" for r in rows),
              "original_audits_reproduce": all(r.get("audit") == a for r, a in zip(rows, audits)),
              "official_report_matches_attempts": Counter(s["scenario_id"] for s in official.get("scenarios", []))
              == Counter(scenarios.keys()) and all(
                  s["rep_totals"] == [(r.get("score") or {}).get("total") for r in rows if r["scenario_id"] == s["scenario_id"]]
                  for s in official.get("scenarios", []))}
    media_rows = [r for r in rows if any(
        key in event.get("payload", {}) for event in scenarios[r["scenario_id"]]["events"]
        for key in ("audio_ref", "image_ref"))]
    checks["real_generation_transport_for_media"] = bool(media_rows) and all(any(
        t.get("status") == 200 and t.get("transport") == "AsyncHTTPTransport"
        and t.get("host") == "generativelanguage.googleapis.com"
        and t.get("path", "").endswith(":generateContent")
        for t in r.get("transport_requests", [])) for r in media_rows)
    visual = [(r, a) for r, a in zip(rows, audits) if r["scenario_id"] == "pub_07_visual_port_lookup"]
    checks["genuine_current_image_embedding"] = len(visual) == 3 and all(any(
        c["id"] == "submitted_embedding_requires_computation_evidence" and c["status"] == "pass"
        for c in a["checks"]) and any(t.get("status") == 200 and t.get("transport") == "AsyncHTTPTransport"
            and t.get("host") == "generativelanguage.googleapis.com" and t.get("path", "").endswith(":embedContent")
            for t in r.get("transport_requests", [])) for r, a in visual)
    checks["all_required_evidence_hashed_and_unchanged"] = evidence_hashes_match(evidence, paths)
    identity = package_identity(candidate, reference)
    checks["package_identity_valid"] = identity["valid"]
    completed = sum(a["task_complete"] for a in audits)
    accepted = sum(a["accepted"] for a in audits)
    return {"evidence": str(evidence), "identity": identity, "checks": checks,
            "comparison_configuration": {"environment": {k: v for k, v in manifest.get("environment", {}).items()
                                                         if k != "PARTICIPANT_MEDIA_ROOT"},
                                         "acceptance_source_sha256": manifest["acceptance_source_sha256"]},
            "effective_runtime_configurations": manifest.get("effective_runtime_configurations", []),
            "provider_transport_attempts": sum(len(r.get("transport_requests", [])) for r in rows)
            + len(manifest.get("prescenario_transport_requests", [])) + len(manifest.get("unassociated_transport_requests", [])),
            "evidence_valid": all(checks.values()), "official_summary_unchanged": official.get("summary"),
            "admission": {"official_validation_and_smoke_completed": checks["official_exit_success"],
                          "clean_offline_verifiers": "separate evidence; not inferred"},
            "attempts": len(rows), "required_completions": completed, "full_acceptances": accepted,
            "strict_complete_batch_gate": all(checks.values()) and completed == accepted == 27,
            "attempt_results": [{"attempt": r["attempt"], "scenario_id": r["scenario_id"],
                                 "official_score": (r.get("score") or {}).get("total"), "task_complete": a["task_complete"],
                                 "accepted": a["accepted"], "failures": a["failures"],
                                 "timing_diagnostics": timing_diagnostics(scenarios[r["scenario_id"]], r["trace"])}
                                for r, a in zip(rows, audits)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, action="append", required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--reference-kit", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Preserve earlier reviews; --out must be new")
    sys.path.insert(0, str(args.reference_kit.resolve()))
    from harness.mock_env import TOOL_REGISTRY
    batches = []
    for path in args.evidence:
        try:
            batches.append(review_batch(path.resolve(), args.candidate.resolve(), args.reference_kit.resolve(), TOOL_REGISTRY))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            batches.append({"evidence": str(path.resolve()), "evidence_valid": False,
                            "strict_complete_batch_gate": False, "attempts": None,
                            "required_completions": None, "full_acceptances": None,
                            "review_error": f"{type(exc).__name__}: {exc}"})
    distinct = len({p.resolve() for p in args.evidence}) == len(batches)
    record = {"version": "submission-delivery-gate-v4", "reviewed_utc": datetime.now(timezone.utc).isoformat(),
              "gate_source_sha256": sha(Path(__file__)), "batches": batches,
              "fresh_repeated_batch_gate": len(batches) >= 2 and distinct
              and all(b["strict_complete_batch_gate"] for b in batches)
              and len({read(p / 'manifest.json').get('started_utc') for p in args.evidence}) == len(batches)
              and all(b["comparison_configuration"] == batches[0]["comparison_configuration"] for b in batches)
              and all(b["effective_runtime_configurations"] == batches[0]["effective_runtime_configurations"] for b in batches),
              "scope": "Read-only recomputation; no new participant execution or provider requests"}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"batches": [{k: b[k] for k in ("attempts", "required_completions", "full_acceptances",
                                                     "evidence_valid", "strict_complete_batch_gate")} for b in batches],
                      "fresh_repeated_batch_gate": record["fresh_repeated_batch_gate"], "out": str(args.out)}))
    raise SystemExit(0 if record["fresh_repeated_batch_gate"] else 1)


if __name__ == "__main__":
    main()
