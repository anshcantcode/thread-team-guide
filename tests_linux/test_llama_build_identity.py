"""Archive builds need recorded hashes, not caller-authored version claims."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import fdb3_config


class LlamaBuildIdentityTests(unittest.TestCase):
    def test_unknown_build_is_rejected_even_when_the_caller_supplies_a_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "llama-server"
            binary.write_bytes(b"unrecorded build")
            (Path(directory) / "build-identity.json").write_text(json.dumps({
                "llama_source_commit": fdb3_config.load_config()["llama"]["commit"],
                "llama_binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            }))
            with self.assertRaisesRegex(ValueError, "exact recorded"):
                fdb3_config.verify_llama(binary, "version: 0.4.0-dev (build 0, commit unknown)")

    def test_recorded_archive_requires_exact_binary_and_source_pins(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "llama-server"
            binary.write_bytes(b"recorded test build")
            sha = hashlib.sha256(binary.read_bytes()).hexdigest()
            config = Path(directory) / "build.json"
            receipt = {"source_commit": fdb3_config.load_config()["llama"]["commit"],
                       "source_archive_sha256": "test-source-archive-sha"}
            build = {"llama_source_sha256": "test-source-archive-sha",
                     "archive_build_receipts": {sha: receipt}}
            config.write_text(json.dumps(build))
            with patch.object(fdb3_config, "LINUX_BUILD_CONFIG", config):
                identity = fdb3_config.verify_llama(binary, "commit unknown")
                self.assertEqual(identity["binary_sha256"], sha)
                self.assertEqual(identity["verified_by"], "recorded_archive_build")
                for field in ("source_commit", "source_archive_sha256"):
                    previous = receipt[field]
                    receipt[field] = "wrong"
                    config.write_text(json.dumps(build))
                    with self.subTest(field=field), self.assertRaises(ValueError):
                        fdb3_config.verify_llama(binary, "commit unknown")
                    receipt[field] = previous
                config.write_text(json.dumps(build))
                binary.write_bytes(b"changed test build")
                with self.assertRaises(ValueError):
                    fdb3_config.verify_llama(binary, "commit unknown")

    def test_normal_git_build_still_requires_the_pinned_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "llama-server"
            binary.write_bytes(b"git build")
            commit = fdb3_config.load_config()["llama"]["commit"]
            identity = fdb3_config.verify_llama(binary, f"build 10930, commit {commit[:9]}")
            self.assertEqual(identity["verified_by"], "commit_version")
            with self.assertRaises(ValueError):
                fdb3_config.verify_llama(binary, "build 10930, commit 000000000")


if __name__ == "__main__":
    unittest.main()
