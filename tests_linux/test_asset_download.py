"""Exercise interrupted transfers and fail-closed hash/publication behavior."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from tests_linux.test_reproduce_fdb3_linux import BASH, ROOT, shell_path


FAKE_CURL = """#!/usr/bin/env bash
while [ "$#" -gt 0 ]; do
  if [ "$1" = -o ]; then output="$2"; shift; fi
  shift
done
printf 'call\\n' >> "$CALL_LOG"
if [ "$MODE" = retry ] && [ ! -e "$CALL_LOG.once" ]; then
  touch "$CALL_LOG.once"
  printf partial > "$output"
  exit 92
fi
if [ "$MODE" = failure ]; then printf partial > "$output"; exit 92; fi
if [ "$MODE" = corrupt ]; then printf wrong > "$output"; else printf verified > "$output"; fi
"""


class AssetDownloadTests(unittest.TestCase):
    def run_download(self, root, mode):
        binary = root / "bin"
        binary.mkdir(exist_ok=True)
        curl = binary / "curl"
        curl.write_text(FAKE_CURL, newline="\n")
        curl.chmod(0o700)
        env = dict(os.environ, MODE=mode, CALL_LOG=shell_path(root / "calls"))
        env["PATH"] = str(binary) + os.pathsep + env["PATH"]
        return subprocess.run([BASH, shell_path(ROOT / "scripts/fdb3_download_linux.sh"),
                               "https://invalid.example/test", shell_path(root / "asset"),
                               hashlib.sha256(b"verified").hexdigest()],
                              env=env, capture_output=True, text=True, timeout=15)

    def test_http2_interruption_retries_and_retains_partial_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_download(root, "retry")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / "asset").read_bytes(), b"verified")
            self.assertEqual((root / "asset.attempt-1").read_bytes(), b"partial")
            self.assertEqual((root / "calls").read_text().splitlines(), ["call", "call"])
            self.assertIn("curl exit 92", result.stderr)

    def test_successful_transfer_with_bad_hash_is_never_published(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_download(root, "corrupt")
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertFalse((root / "asset").exists())
            self.assertEqual((root / "asset.attempt-1").read_bytes(), b"wrong")
            self.assertEqual((root / "calls").read_text().splitlines(), ["call"])

    def test_retries_are_bounded_and_all_failed_transfers_remain(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_download(root, "failure")
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertFalse((root / "asset").exists())
            self.assertEqual((root / "calls").read_text().splitlines(), ["call"] * 3)
            self.assertEqual([p.read_bytes() for p in sorted(root.glob("asset.attempt-*"))], [b"partial"] * 3)

    def test_existing_output_or_transfer_is_never_overwritten(self):
        for name in ("asset", "asset.attempt-1"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / name).write_bytes(b"previous evidence")
                result = self.run_download(root, "success")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual((root / name).read_bytes(), b"previous evidence")
                self.assertFalse((root / "calls").exists())


if __name__ == "__main__":
    unittest.main()
