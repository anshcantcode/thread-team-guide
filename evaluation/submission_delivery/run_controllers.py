"""Run the existing frozen controller corpus, offline, without editing its adapter."""
import argparse
from pathlib import Path
import sys

from evaluation.samsung_acceptance.adapter import main as run_adapter
from evaluation.samsung_acceptance.invalid_media_offline import offline_environment, write_new


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--partition", choices=("development", "holdout"), required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Output exists; preserve every attempt")
    root = Path(__file__).resolve().parents[2]
    corpus = root / "evaluation/samsung_challenge"
    # The existing adapter uses production clocks for missing-result watchdogs.
    # All other rows use its documented virtual ordering, never timing evidence.
    sys.argv = ["evaluation.samsung_acceptance.adapter", "--candidate", str(args.candidate),
                "--kit", str(args.kit), "--cases", str(corpus / "frozen" / (args.partition + ".jsonl")),
                "--oracle", str(corpus / "oracle.py"), "--out", str(args.out),
                "--partition", args.partition, "--case-mode", "controller_injected",
                "--execution", "controller", "--clock", "auto", "--settle-turns", "40"]
    network_attempts = []
    code = 1
    try:
        with offline_environment(network_attempts):
            run_adapter()
    except SystemExit as exc:
        code = exc.code
    finally:
        if (args.out / "manifest.json").is_file():
            write_new(args.out / "offline-guard.json", {"blocked_network_attempts": network_attempts,
                                                       "adapter_exit_code": code})
    raise SystemExit(code or bool(network_attempts))


if __name__ == "__main__":
    main()
