"""Verify a saved diagnostic archive without running an agent or changing scores."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from thread_agent.fdb3_evidence import verify_tool_trace


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_manifest(root: Path, manifest: Path) -> dict:
    root = root.resolve()
    errors, listed = [], set()
    for line_number, line in enumerate(manifest.read_text(encoding="utf-8-sig").splitlines(), 1):
        match = re.fullmatch(r"([0-9a-fA-F]{64}) [ *](.+)", line)
        if not match:
            errors.append(f"invalid manifest line {line_number}")
            continue
        digest, relative = match.groups()
        path = (root / relative.replace("\\", "/")).resolve()
        if not path.is_relative_to(root):
            errors.append(f"path escapes archive: {relative}")
            continue
        key = path.relative_to(root).as_posix()
        if key in listed:
            errors.append(f"duplicate manifest path: {key}")
        listed.add(key)
        if not path.is_file():
            errors.append(f"missing file: {key}")
        elif sha256(path) != digest.lower():
            errors.append(f"hash mismatch: {key}")
    observed = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    errors.extend(f"unlisted file: {p}" for p in sorted(observed - listed))
    if not listed:
        errors.append("empty manifest")
    return {"valid": not errors, "manifest_sha256": sha256(manifest),
            "listed_files": len(listed), "observed_files": len(observed), "errors": errors}


def audit(root: Path, manifest: Path, expected: int = 100) -> dict:
    result = check_manifest(root, manifest)
    errors = result["errors"]
    read = lambda name: json.loads((root / name).read_text(encoding="utf-8"))
    report, identity, dataset = (read(name) for name in ("report.json", "identity.json", "dataset-manifest.json"))
    cases = report["cases"]
    recordings = {item["recording"]: item for item in dataset["recordings"]}
    names = [case["recording"] for case in cases]
    if report.get("expected") != expected or report.get("requested") != expected:
        errors.append("report expected/requested coverage mismatch")
    if len(names) != expected or len(set(names)) != expected or set(names) != set(recordings):
        errors.append("recording coverage/uniqueness does not match dataset")
    for key, name in (("identity_sha256", "identity.json"),):
        if report.get(key) != sha256(root / name):
            errors.append(f"report {key} mismatch")
    if identity.get("dataset_manifest_sha256") != sha256(root / "dataset-manifest.json"):
        errors.append("dataset manifest identity mismatch")
    for section, directory in (("source_hashes", "source"), ("evaluator_hashes", "evaluator")):
        if not identity.get(section):
            errors.append(f"empty {section} inventory")
        for relative, digest in identity[section].items():
            path = root / directory / relative.replace("\\", "/")
            if not path.is_file() or sha256(path) != digest:
                errors.append(f"snapshot mismatch: {directory}/{relative}")
    strict = window = complete = response_all = response_strict = missing_links = 0
    for index, case in enumerate(cases):
        directory = root / f"case-{index:03d}"
        evaluation = json.loads((directory / "evaluation.json").read_text(encoding="utf-8"))
        inference = json.loads((directory / "inference/result.json").read_text(encoding="utf-8"))
        if case.get("evaluation_sha256") != sha256(directory / "evaluation.json"):
            errors.append(f"case {index}: evaluation hash mismatch")
        if case.get("result_sha256") != sha256(directory / "inference/result.json"):
            errors.append(f"case {index}: inference hash mismatch")
        if sha256(directory / "input.wav") != recordings[case["recording"]]["sha256"]:
            errors.append(f"case {index}: audio hash mismatch")
        valid_case = (case.get("status") == "completed" and evaluation.get("status") == "completed"
                      and inference.get("status") == "completed" and not evaluation.get("infrastructure_error")
                      and not inference.get("errors"))
        if not valid_case:
            errors.append(f"case {index}: incomplete inference/evaluation or recorded infrastructure error")
        if inference.get("input_sha256") != recordings[case["recording"]]["sha256"]:
            errors.append(f"case {index}: inference input hash mismatch")
        try:
            verify_tool_trace(inference.get("actual_tool_calls"), directory / "inference/tool-calls.jsonl")
        except (ValueError, OSError) as error:
            errors.append(f"case {index}: {error}")
        requests = evaluation.get("judge_requests", [])
        if evaluation.get("judge_enabled") and (not requests or any(
                item.get("valid") is not True or item.get("status_code") != 200 for item in requests)):
            errors.append(f"case {index}: judge receipts missing or failed")
        if "inference_sha256" in evaluation:
            if evaluation["inference_sha256"] != sha256(directory / "inference/result.json"):
                errors.append(f"case {index}: evaluation inference hash mismatch")
        else:
            missing_links += 1
        passed = valid_case and evaluation.get("strict", {}).get("passed") is True
        if passed != case.get("strict_pass"):
            errors.append(f"case {index}: strict report disagrees with evaluation")
        complete += valid_case
        strict += passed
        window += case.get("window_strict_pass") is True
        score = evaluation.get("quality", {}).get("metrics", {}).get("response_qual", {}).get("score")
        response_all += score == 1
        response_strict += passed and score == 1
    for key, value in (("evaluated", complete), ("strict_pass", strict), ("window_strict_pass", window)):
        if report.get(key) != value:
            errors.append(f"recomputed {key} disagrees with report")
    result.update({"valid": not errors, "verified_at": datetime.now(timezone.utc).isoformat(),
                   "run_id": report["run_id"], "source_commit": identity["commit"],
                   "source_dirty": identity["dirty"], "upstream_commit": identity["upstream_commit"],
                   "expected": expected, "evaluated": complete, "strict_pass": strict,
                   "window_strict_pass": window, "infrastructure_errors": expected - complete,
                   "response_correct_all": response_all, "response_correct_among_strict": response_strict,
                   "historical_evaluations_without_direct_inference_hash": missing_links,
                   "judge": report["judge"], "qualification": False,
                   "scope": "Archive integrity and stored-evaluation consistency; no fresh inference or independent judge rerun."})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = audit(args.archive, args.manifest)
    except (OSError, ValueError, KeyError, TypeError) as error:
        result = {"valid": False, "errors": [f"{type(error).__name__}: {error}"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
