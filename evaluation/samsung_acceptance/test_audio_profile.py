"""Focused recorder controls using existing authored fixtures and MockTransport.

No production participant, original scenario or private holdout is executed.
Requested and observed modes remain distinct, including mismatch/missing cases.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from . import decision_selfcheck, test_blind


REPO = Path(__file__).resolve().parents[2]
PROFILES = (
    ("default", None, "independent"),
    ("independent", "independent", "independent"),
    ("single_call_reads", "single_call_reads", "single_call_reads"),
    ("mismatch", "single_call_reads", "independent"),
    ("unobserved", "single_call_reads", None),
)


def planner_with_mode(source, observed):
    if observed is None:
        return source
    return source.replace("    async def setup(self):",
                          f"    async def setup(self):\n        self.audio_mode = {observed!r}")


def environment(requested):
    env = {name: os.environ[name] for name in ("SYSTEMROOT", "TEMP", "TMP") if name in os.environ}
    env.update(PATH=os.defpath, PYTHONIOENCODING="utf-8")
    if requested is not None:
        env["PARTICIPANT_AUDIO_MODE"] = requested
    return env


class AudioProfileControls(unittest.TestCase):
    def assert_profile(self, manifest, requested, observed):
        self.assertIn("PARTICIPANT_AUDIO_MODE", manifest["environment"])
        self.assertEqual(manifest["environment"]["PARTICIPANT_AUDIO_MODE"], requested)
        self.assertEqual(len(manifest["effective_runtime_configurations"]), 1)
        effective = manifest["effective_runtime_configurations"][0]
        self.assertIn("audio_mode", effective)
        self.assertEqual(effective["audio_mode"], observed)
        self.assertTrue(manifest["sources_unchanged"])

    def test_public_requested_and_observed_profiles_preserve_decisions(self):
        baseline = None
        with tempfile.TemporaryDirectory(prefix="public-audio-profile-") as directory:
            root = Path(directory)
            kit, candidate = root / "kit", root / "candidate"
            (kit / "harness").mkdir(parents=True)
            (kit / "scenarios").mkdir()
            (candidate / "participant").mkdir(parents=True)
            (kit / "harness/__init__.py").write_text("")
            (kit / "harness/mock_env.py").write_text("TOOL_REGISTRY = {}\n")
            (kit / "submission.yaml").write_text("authored profile fixture\n")
            (kit / "eval_submission.py").write_text(decision_selfcheck.EVALUATOR)
            (kit / "scenarios/profile.json").write_text(json.dumps({
                "scenario_id": "profile", "mode": "rejected", "revision": 1,
                "events": [], "ground_truth": {}}))
            (candidate / "participant/__init__.py").write_text("")
            (candidate / "PACKAGE_MANIFEST.json").write_text(
                '{"source_git_revision":"authored-audio-profile-fixture"}')
            for name, code in (("agent", decision_selfcheck.AGENT), ("embedding", decision_selfcheck.EMBEDDING)):
                (candidate / f"participant/{name}.py").write_text(code)
            for label, requested, observed in PROFILES:
                with self.subTest(profile=label):
                    (candidate / "participant/planner.py").write_text(
                        planner_with_mode(decision_selfcheck.PLANNER, observed))
                    out = root / label
                    process = subprocess.run([sys.executable, "-B", "-m", "evaluation.samsung_acceptance.record",
                        "--submission", str(candidate), "--kit", str(kit), "--reference-kit", str(kit),
                        "--out", str(out), "--mode", "real-provider", "--reps", "1", "--decision-evidence",
                        "--max-generation-requests", "1", "--max-embedding-requests", "0",
                        "--cap-generation-model", "gemini-3.5-flash-lite"], cwd=REPO,
                        env={**environment(requested), "THREAD_API_KEY": "OFFLINE-CREDENTIAL-SENTINEL"},
                        capture_output=True, text=True, timeout=20)
                    self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                    manifest = json.loads((out / "manifest.json").read_text())
                    self.assert_profile(manifest, requested, observed)
                    self.assertEqual(manifest["request_budget"]["admitted_starts"], {"generation": 1, "embedding": 0})
                    self.assertFalse(manifest["observer_errors"] or manifest["decision_observer_errors"])
                    row = json.loads((out / "attempt-001-profile.json").read_text())
                    self.assertEqual([q["transport"] for q in row["transport_requests"]], ["MockTransport"])
                    preserved = {key: row[key] for key in ("trace", "score", "decision_evidence", "transport_requests")}
                    if baseline is None:
                        baseline = preserved
                    self.assertEqual(preserved, baseline)

    def test_blind_profiles_preserve_cap_stop_and_missing_values(self):
        request_hash = None
        for label, requested, observed in PROFILES:
            with self.subTest(profile=label), tempfile.TemporaryDirectory(prefix="blind-audio-profile-") as directory:
                root = Path(directory)
                with patch.object(test_blind, "PLANNER", planner_with_mode(test_blind.PLANNER, observed)):
                    args = test_blind.fixture(root)
                out = root / "out"
                command = test_blind.BlindControls.command(SimpleNamespace(args=args), out, cap=1)
                process = subprocess.run(command, cwd=REPO,
                    env={**environment(requested), "FIXTURE_CLOSED": str(root / "closed.txt")},
                    capture_output=True, text=True, timeout=30)
                self.assertNotEqual(process.returncode, 0)
                evidence = out / "run"
                manifest = json.loads((evidence / "manifest.json").read_text())
                self.assert_profile(manifest, requested, observed)
                self.assertEqual(manifest["stop_reason"], "request_cap_stopped")
                self.assertEqual(manifest["request_budget"]["admitted_starts"], {"generation": 1, "embedding": 0})
                self.assertFalse(any(manifest["observer_errors"].values()))
                self.assertEqual([q["status"] for q in manifest["attempts"]], ["request_cap_stopped"] + ["unrun"] * 17)
                row = json.loads((evidence / "attempt-001.json").read_text())
                self.assertEqual([q["transport"] for q in row["transport_requests"]], ["MockTransport"])
                current_hash = row["transport_requests"][0]["body_sha256"]
                if request_hash is None:
                    request_hash = current_hash
                self.assertEqual(current_hash, request_hash)
                self.assertTrue(json.loads((evidence / "process-status.json").read_text())["completed"])


if __name__ == "__main__":
    unittest.main()
