"""Linux shell entrypoint failure controls; no providers, network, or GPU work.

Run in Linux, or under Windows with Git Bash (never the WSL bash shim).
Git Bash results check shell guards only, not Linux runtime compatibility.
"""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/reproduce_fdb3_linux.sh"
BASH = str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/usr/bin/bash.exe") if os.name == "nt" else "bash"


def shell_path(path):
    value = Path(path).absolute().as_posix()
    if os.name == "nt":
        return "/" + value[0].lower() + value[2:]
    return value


class LinuxReproductionGuards(unittest.TestCase):
    def invoke(self, *args, **values):
        env = {key: value for key, value in os.environ.items()
               if not key.startswith("THREAD_") and not key.startswith("OPENAI_")}
        env.update(values)
        for key in ("THREAD_WORK", "THREAD_PYTHON"):
            if key in values and Path(values[key]).is_absolute():
                env[key] = shell_path(values[key])
        return subprocess.run([BASH, shell_path(SCRIPT), *args], env=env,
                              text=True, capture_output=True, timeout=15)

    def test_shell_syntax(self):
        subprocess.run([BASH, "-n", shell_path(SCRIPT)], check=True, timeout=5)

    def test_help_never_creates_work_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / "work"
            result = self.invoke("--help", THREAD_WORK=str(work))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("PREPARED_ONLY", result.stdout)
            self.assertFalse(work.exists())

    def test_unknown_option_is_failure_without_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / "work"
            result = self.invoke("--pretend-pass", THREAD_WORK=str(work))
            self.assertEqual(result.returncode, 2)
            self.assertFalse(work.exists())

    def test_existing_evidence_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "verification.json"
            marker.write_text('{"owner": "other-campaign"}')
            result = self.invoke("--prepare-only", THREAD_WORK=directory)
            self.assertEqual(result.returncode, 2)
            self.assertIn("new directory", result.stderr)
            self.assertEqual(marker.read_text(), '{"owner": "other-campaign"}')
            self.assertEqual(list(Path(directory).iterdir()), [marker])

    def test_build_parallelism_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / "work"
            result = self.invoke("--prepare-only", THREAD_WORK=str(work), THREAD_BUILD_JOBS="8")
            self.assertEqual(result.returncode, 2)
            self.assertIn("must be 1 or 2", result.stderr)
            self.assertFalse(work.exists())

    def test_cloud_key_does_not_authorize_hosted_judge(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / "work"
            result = self.invoke(THREAD_WORK=str(work), THREAD_FDB3_JUDGE_MODE="hosted",
                                 OPENAI_API_KEY="test-only-not-a-real-key")
            self.assertEqual(result.returncode, 2)
            self.assertIn("explicit authorization", result.stderr)
            self.assertFalse(work.exists())

    def test_missing_python_is_incomplete_not_perfect(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / "work"
            result = self.invoke("--prepare-only", THREAD_WORK=str(work),
                                 THREAD_PYTHON="thread-no-such-python-command")
            self.assertEqual(result.returncode, 2)
            self.assertIn("missing thread-no-such-python-command", result.stderr)
            self.assertFalse((work / "preparation.json").exists())

    def test_failed_prerequisite_is_incomplete_not_an_imperfect_complete_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            python = root / "failing-python"
            python.write_text("#!/bin/sh\nexit 37\n", newline="\n")
            python.chmod(0o700)
            result = self.invoke("--prepare-only", THREAD_WORK=str(root / "work"),
                                 THREAD_PYTHON=str(python))
            self.assertEqual(result.returncode, 2)
            self.assertIn("evidence is incomplete", result.stderr)

    def test_invalid_provider_cannot_escape_result_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / "work"
            result = self.invoke("--prepare-only", THREAD_WORK=str(work),
                                 THREAD_PROVIDER_LABEL="../../old-results")
            self.assertEqual(result.returncode, 2)
            self.assertFalse(work.exists())


if __name__ == "__main__":
    unittest.main()
