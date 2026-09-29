"""Supervise a recorder or independent adapter in a fresh subprocess.

Pass the selected worker's arguments after --. This does not authorize provider use; callers
must already own the provider slot. A timeout/failure remains a failed attempt.
"""
import argparse
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import subprocess
import sys
import time

from .record import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="new directory; records are under out/run")
    parser.add_argument("--worker", choices=("record", "adapter"), default="record")
    parser.add_argument("--wall-seconds", type=float, default=11700,
                        help="outer cap, leaving original per-case setup/wall limits unchanged")
    parser.add_argument("record_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.wall_seconds <= 0 or args.wall_seconds > 11700:
        parser.error("wall-seconds must be positive and at most 11700")
    extra = args.record_args[1:] if args.record_args[:1] == ["--"] else args.record_args
    if any(value == "--out" or value.startswith("--out=") for value in extra):
        parser.error("record output is owned by this supervisor")
    if args.worker == "adapter" and any(value == "--review-evidence" or value.startswith("--review-evidence=") for value in extra):
        parser.error("Supervise adapter execution only; review retained evidence separately")
    out = args.out.resolve()
    roots = argparse.ArgumentParser(add_help=False)
    for name in (("submission", "kit", "reference-kit") if args.worker == "record" else
                 ("candidate", "kit", "reference-kit", "bundle")):
        roots.add_argument("--" + name, type=Path, required=True)
    frozen, _ = roots.parse_known_args(extra)
    protected = list(vars(frozen).values())
    if args.worker == "adapter":
        protected.append(Path(__file__).resolve().parents[2])
    if any(out.is_relative_to(path.resolve()) for path in protected):
        parser.error("--out must be outside all frozen source and kit roots")
    out.mkdir(parents=True, exist_ok=False)
    evidence = out / "run"
    command = [sys.executable, "-B", "-m", "evaluation.samsung_acceptance." + args.worker,
               "--out", str(evidence), *extra]
    record = {"argv": command, "started_utc": datetime.now(timezone.utc).isoformat(),
              "wall_seconds": args.wall_seconds, "completed": False, "timed_out": False,
              "worker": args.worker,
              "scope": ("OS process running the unchanged evaluator through the read-only recorder"
                        if args.worker == "record" else "OS process running the independent frozen-bundle adapter")}
    started = time.monotonic()
    with (out / "process-console.log").open("x", encoding="utf-8") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                   cwd=Path(__file__).resolve().parents[2])
        try:
            record["pid"] = process.pid
            write_json(out / "process-status.json", record)
            process.wait(timeout=args.wall_seconds)
        except subprocess.TimeoutExpired:
            record["timed_out"] = True
            process.kill()
            process.wait()
        except BaseException:
            process.kill()
            process.wait()
            raise
        finally:
            record.update(completed=process.returncode is not None, exit_code=process.returncode,
                          elapsed_seconds=round(time.monotonic() - started, 3),
                          finished_utc=datetime.now(timezone.utc).isoformat())
            write_json(out / "process-status.json", record)
    evidence.mkdir(exist_ok=True)
    (evidence / "process-console.log").write_bytes((out / "process-console.log").read_bytes())
    write_json(evidence / "process-status.json", record)
    write_json(evidence / "evidence-sha256.json", {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(evidence.iterdir())
        if p.is_file() and p.name != "evidence-sha256.json"})
    print(f"Process exit={process.returncode}; timed_out={record['timed_out']}; evidence={evidence}")
    raise SystemExit(124 if record["timed_out"] else process.returncode)


if __name__ == "__main__":
    main()
