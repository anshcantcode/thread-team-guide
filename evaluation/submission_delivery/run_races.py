"""Run independent offline checks against an explicit candidate; retain failures."""
import argparse
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import sys
import unittest

from evaluation.samsung_acceptance.invalid_media_offline import offline_environment, write_new
from evaluation.samsung_acceptance.record import fingerprint


class Results(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rows = []

    def addSuccess(self, test):
        super().addSuccess(test)
        row = {"test": test.id(), "status": "passed"}
        if isinstance(getattr(test, "evidence", None), dict):
            row["evidence"] = test.evidence
        self.rows.append(row)

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.rows.append({"test": test.id(), "status": "failed", "detail": self._exc_info_to_string(err, test)})

    def addError(self, test, err):
        super().addError(test, err)
        self.rows.append({"test": test.id(), "status": "error", "detail": self._exc_info_to_string(err, test)})

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        self.rows.append({"test": subtest.id(), "status": "passed" if err is None else "failed",
                          "subtest": True, **({"detail": self._exc_info_to_string(err, subtest)} if err else {})})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--suite", choices=("races", "flight-chain", "audio-agreement", "audio-confirmation-role",
                                            "audio-single-call-reads"), default="races")
    args = parser.parse_args()
    candidate, out = args.candidate.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    before = fingerprint(candidate / "participant")
    network_attempts = []
    sys.path.insert(0, str(candidate))
    with offline_environment(network_attempts):
        module = {"races": "test_races", "flight-chain": "test_flight_chain", "audio-agreement": "test_audio_agreement",
                  "audio-confirmation-role": "test_audio_agreement",
                  "audio-single-call-reads": "test_audio_single_call_reads"}[args.suite]
        tests = importlib.import_module("evaluation.submission_delivery." + module)
        participant = importlib.import_module("participant.agent")
        if not Path(participant.__file__).resolve().is_relative_to(candidate):
            raise RuntimeError("Wrong candidate import")
        names = {"races": ("ControllerRaceTests", "PlannerBoundaryTests"),
                 "flight-chain": ("FlightCommandTests",), "audio-agreement": ("AudioAgreementTests",),
                 "audio-confirmation-role": ("AudioConfirmationRoleTests",),
                 "audio-single-call-reads": ("AudioSingleCallReadTests",)}[args.suite]
        classes = [getattr(tests, name) for name in names]
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls) for cls in classes)
        with (out / "unittest.log").open("x", encoding="utf-8", newline="\n") as log:
            result = unittest.TextTestRunner(stream=log, verbosity=2, resultclass=Results).run(suite)
    record = {"created_utc": datetime.now(timezone.utc).isoformat(), "argv": sys.argv,
              "candidate": str(candidate), "suite": args.suite, "python": sys.executable, "participant_source_sha256": before,
              "tests_source_sha256": fingerprint(Path(__file__).resolve().parent),
              "sources_unchanged": before == fingerprint(candidate / "participant"),
              "test_methods_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
              "skipped": len(result.skipped), "blocked_network_attempts": network_attempts,
              "provider_calls": 0, "results": result.rows,
              "limits": "Offline controller/planner checks with scripted results or mocked generation/HTTP, not model conversations; subtests are reported separately and not added to test_methods_run."}
    write_new(out / "results.json", record)
    print(json.dumps({key: record[key] for key in ("test_methods_run", "failures", "errors", "skipped", "sources_unchanged", "blocked_network_attempts")}))
    raise SystemExit(0 if result.wasSuccessful() and record["sources_unchanged"] and not network_attempts else 1)


if __name__ == "__main__":
    main()
