"""Record reproducible oracle self-check evidence, never participant success."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

from .controls import negative_controls
from .generate import ROOT, all_cases, canon, runtime_fingerprint, validate_case
from .oracle import evaluate_case


def run(out):
    if out.exists():
        raise ValueError("Output already exists; preserve earlier evidence in a new directory.")
    out.mkdir(parents=True)
    defects, families, failures = Counter(), defaultdict(Counter), []
    positive = 0
    stimuli = set()
    with (out / "case-results.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for case, witness in all_cases():
            errors = validate_case(case, witness)
            mutants = []
            for defect, bad in negative_controls(case, witness):
                rejected = not evaluate_case(case, bad)["passed"]
                defects[defect] += 1
                families[case["family"]]["mutants_attempted"] += 1
                families[case["family"]]["mutants_rejected"] += int(rejected)
                mutants.append({"defect": defect, "rejected": rejected})
            okay = not errors and all(m["rejected"] for m in mutants)
            row = {"id": case["id"], "family": case["family"], "mode": case["mode"], "partition": case["partition"],
                   "synthetic_positive_accepted": not errors, "negative_controls": mutants, "errors": errors}
            handle.write(canon(row) + "\n")
            if not okay:
                failures.append(row)
            positive += int(not errors)
            families[case["family"]]["positive_witnesses"] += int(not errors)
            stimuli.add(runtime_fingerprint(case))
    report = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "command": sys.argv, "python": sys.version,
              "evidence_kind": "synthetic_oracle_selfcheck", "participant_executions": 0, "real_model_calls": 0,
              "media_semantics_executed": 0, "positive_witnesses_accepted": positive, "unique_runtime_stimuli": len(stimuli),
              "negative_controls_attempted": sum(defects.values()), "negative_control_counts": dict(defects),
              "failures": len(failures), "families": dict(families),
              "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in ("generate.py", "oracle.py", "controls.py", "selfcheck.py")},
              "frozen_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT / "frozen").iterdir()) if p.is_file()}}
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if failures:
        (out / "failures.json").write_text(json.dumps(failures, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"families", "source_sha256", "frozen_sha256", "python"}}, indent=2))
    return bool(failures)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.out))


if __name__ == "__main__":
    main()
