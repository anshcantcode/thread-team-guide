"""Account for every released recording after an upstream FDB-v3 run.

Reads the upstream per-recording result_<provider>.json files and the
evaluate_pass_rate.py report. Exit 2: incomplete inference or judging (missing,
failed or unevaluated recordings are never dropped from the denominator);
exit 1: complete accounting but not every recording passes; exit 0: all pass.
Writes a JSON summary; never edits upstream outputs.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def recording_dirs(root):
    return sorted(path for path in Path(root).iterdir() if path.is_dir() and (path / "input.wav").is_file())


def summarize(results_dir, provider, pass_report=None, expected=100, judge_receipts=None):
    rows, incomplete = [], []
    for directory in recording_dirs(results_dir):
        path = directory / f"result_{provider}.json"
        if not path.is_file():
            incomplete.append({"recording": directory.name, "reason": "no result file"})
            continue
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            incomplete.append({"recording": directory.name, "reason": "unreadable result"})
            continue
        if result.get("status") != "completed":
            incomplete.append({"recording": directory.name, "reason": "status " + str(result.get("status"))})
        rows.append({"recording": directory.name, "status": result.get("status"),
                     "calls": len(result.get("actual_tool_calls") or [])})
    summary = {"provider": provider, "expected": expected, "found": len(recording_dirs(results_dir)),
               "completed_inference": sum(row["status"] == "completed" for row in rows), "incomplete": incomplete}
    passed = None
    if pass_report and Path(pass_report).is_file():
        report = json.loads(Path(pass_report).read_text(encoding="utf-8"))
        summary["pass_report"] = str(pass_report)
        for key in ("passed", "num_passed", "pass_count"):
            if isinstance(report.get(key), int):
                passed = report[key]
        if passed is None and isinstance(report.get("results"), list):
            passed = sum(1 for row in report["results"] if row.get("passed") is True)
        summary["evaluated"] = (report.get("total_scenarios") if isinstance(report.get("total_scenarios"), int)
                                else len(report["results"]) if isinstance(report.get("results"), list) else None)
    summary["strict_passed"] = passed
    summary["qualification_eligible"] = False
    summary["judge_verified"] = False
    if judge_receipts is not None:
        checked_scripts = set()
        inference_hashes = {p.relative_to(results_dir).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in Path(results_dir).rglob(f"result_{provider}.json")}
        for receipt_path in judge_receipts:
            try:
                receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
                script = receipt["evaluator_script"]
                output = Path(receipt["output_path"])
                requests = receipt["judge_requests"]
                valid = (receipt.get("status") == "completed" and not receipt.get("infrastructure_error")
                         and receipt.get("upstream_exit_code") == 0 and requests
                         and all(row.get("outcome") == "success" for row in requests)
                         and receipt.get("inference_sha256") == inference_hashes
                         and receipt.get("output_sha256") == hashlib.sha256(output.read_bytes()).hexdigest())
                if script == "evaluate_pass_rate" and output.resolve() != Path(pass_report).resolve():
                    valid = False
                if script in checked_scripts or not valid:
                    raise ValueError("incomplete, duplicate or mismatched judge evidence")
                checked_scripts.add(script)
            except (OSError, ValueError, KeyError, TypeError) as error:
                incomplete.append({"recording": "judge", "reason": f"{Path(receipt_path).name}: {error}"})
        summary["judge_verified"] = checked_scripts == {"evaluate_pass_rate", "evaluate_tool_calls"} and not incomplete
        if not summary["judge_verified"]:
            incomplete.append({"recording": "judge", "reason": "Both checked upstream evaluator stages are required"})
    else:
        summary["scope"] = "Recording/count accounting only; judge execution unverified"
    complete = (summary["found"] == expected and not incomplete and passed is not None
                and summary.get("evaluated") == expected)
    summary["complete"] = complete
    summary["exit_code"] = 2 if not complete else (0 if passed == expected else 1)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", required=True, type=Path)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--pass-report", type=Path)
    parser.add_argument("--expected", type=int, default=100)
    parser.add_argument("--judge-receipts", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = summarize(args.results_dir, args.provider, args.pass_report, args.expected, args.judge_receipts)
    args.output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({key: summary[key] for key in ("found", "completed_inference", "strict_passed", "complete", "exit_code")}))
    return summary["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
