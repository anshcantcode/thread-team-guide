import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

_spec = importlib.util.spec_from_file_location("archive_audit", Path(__file__).resolve().parents[1] / "scripts/fdb3_audit_archive.py")
audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audit)


class ArchiveAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "archive"
        self.root.mkdir()
        self.file = self.root / "evidence.json"
        self.file.write_text('{"passed": false}\n', encoding="utf-8")
        self.manifest = self.base / "SHA256SUMS"
        self.manifest.write_text(f"{audit.sha256(self.file)} *./evidence.json\n", encoding="utf-8")

    def test_complete_manifest_and_tamper(self):
        self.assertTrue(audit.check_manifest(self.root, self.manifest)["valid"])
        self.file.write_text('{"passed": true}\n', encoding="utf-8")
        self.assertIn("hash mismatch: evidence.json", audit.check_manifest(self.root, self.manifest)["errors"])

    def test_missing_and_unlisted_files(self):
        self.file.unlink()
        (self.root / "substitute.json").write_text("{}", encoding="utf-8")
        errors = audit.check_manifest(self.root, self.manifest)["errors"]
        self.assertIn("missing file: evidence.json", errors)
        self.assertIn("unlisted file: substitute.json", errors)

    def test_duplicate_and_traversal_entries_rejected(self):
        line = self.manifest.read_text(encoding="utf-8")
        self.manifest.write_text(line + line + "0" * 64 + " *../outside.json\n", encoding="utf-8")
        errors = audit.check_manifest(self.root, self.manifest)["errors"]
        self.assertIn("duplicate manifest path: evidence.json", errors)
        self.assertIn("path escapes archive: ../outside.json", errors)

    def test_empty_manifest_rejected(self):
        self.file.unlink()
        self.manifest.write_text("", encoding="utf-8")
        self.assertFalse(audit.check_manifest(self.root, self.manifest)["valid"])

    def test_hashed_failed_inference_and_judge_cannot_be_a_valid_pass(self):
        def write(name, value):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value), encoding="utf-8")
            return audit.sha256(path)
        audio_hash = write("case-000/input.wav", "fixture")
        dataset_hash = write("dataset-manifest.json", {"recordings": [{"recording": "authored", "sha256": audio_hash}]})
        identity_hash = write("identity.json", {"dataset_manifest_sha256": dataset_hash,
            "source_hashes": {}, "evaluator_hashes": {}, "commit": "frozen", "dirty": False, "upstream_commit": "pinned"})
        inference_hash = write("case-000/inference/result.json", {"status": "infrastructure_error", "actual_tool_calls": None})
        evaluation_hash = write("case-000/evaluation.json", {"status": "completed", "strict": {"passed": True},
            "infrastructure_error": "judge failed"})
        write("report.json", {"run_id": "negative-control", "expected": 1, "requested": 1,
            "identity_sha256": identity_hash, "evaluated": 1, "strict_pass": 1, "window_strict_pass": 1,
            "judge": "local", "cases": [{"recording": "authored", "status": "completed", "strict_pass": True,
                "window_strict_pass": True, "evaluation_sha256": evaluation_hash, "result_sha256": inference_hash}]})
        self.manifest.write_text("".join(f"{audit.sha256(p)} *./{p.relative_to(self.root).as_posix()}\n"
                                         for p in self.root.rglob("*") if p.is_file()), encoding="utf-8")
        result = audit.audit(self.root, self.manifest, expected=1)
        self.assertFalse(result["valid"])
        self.assertEqual(result["evaluated"], 0)
        self.assertEqual(result["strict_pass"], 0)
        self.assertIn("empty source_hashes inventory", result["errors"])
