"""Diagnostic screening options of scripts/fdb3_run.py fail closed before any campaign starts."""
import subprocess
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def run(*extra):
    return subprocess.run([sys.executable, str(ROOT / "scripts/fdb3_run.py"), "--assets", "missing", "--upstream",
                           "missing", "--whisper", "missing", "--model-file", "missing", *extra],
                          capture_output=True, text=True, cwd=ROOT, timeout=120)


class ScreeningOptionTests(unittest.TestCase):
    def test_only_rejects_out_of_range_and_non_integers(self):
        for value in ("100", "-1", "3,x", ","):
            with self.subTest(value=value):
                child = run("--only", value)
                self.assertEqual(child.returncode, 2)
                self.assertIn("--only", child.stderr)

    def test_only_cannot_be_combined_with_limit(self):
        child = run("--only", "3,5", "--limit", "10")
        self.assertEqual(child.returncode, 2)
        self.assertIn("cannot be combined with --limit", child.stderr)

    def test_skip_latency_is_a_flag(self):
        child = run("--skip-latency", "--limit", "0")
        self.assertEqual(child.returncode, 2)
        self.assertIn("Limit must be between 1 and 100", child.stderr)


if __name__ == "__main__":
    unittest.main()
