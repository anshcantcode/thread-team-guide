"""Offline setup failures must be actionable without exposing credentials."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.check_gemini_config import check


class GeminiConfigTests(unittest.TestCase):
    def run_check(self, profile, values, environ=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / ".env"
            path.write_text(values, encoding="utf-8")
            env = dict(environ or {})
            if profile == "participant":
                env.setdefault("PARTICIPANT_ENV_FILE", str(path))
            output = io.StringIO()
            with patch.dict("os.environ", env, clear=True), \
                    patch("socket.socket.connect", side_effect=AssertionError("network forbidden")), \
                    patch("socket.socket.connect_ex", side_effect=AssertionError("network forbidden")), \
                    patch("socket.getaddrinfo", side_effect=AssertionError("network forbidden")), \
                    contextlib.redirect_stdout(output):
                code = check(profile, env, root)
            return code, output.getvalue()

    def test_shared_file_works_without_printing_key(self):
        for profile in ("app", "participant"):
            with self.subTest(profile=profile):
                code, output = self.run_check(profile, "THREAD_API_KEY=fixture-secret-never-display\nTHREAD_MODEL=gemini-2.5-flash\n")
                self.assertEqual(code, 0, output)
                self.assertNotIn("fixture-secret-never-display", output)
                self.assertIn("No network requests made", output)

    def test_conflicting_aliases_fail_without_exposure(self):
        for values in ("THREAD_API_KEY=first-secret\nSECRET_GEMINI_API_KEY=second-secret\n",
                       "THREAD_API_KEY=first-secret\nTHREAD_MODEL=gemini-2.5-flash\nPARTICIPANT_MODEL=gemini-3.5-flash-lite\n"):
            code, output = self.run_check("participant", values)
            self.assertEqual(code, 1)
            self.assertIn("Conflicting", output)
            self.assertNotIn("first-secret", output)
            self.assertNotIn("second-secret", output)

    def test_blank_environment_shadows_file_key(self):
        for profile in ("app", "participant"):
            code, output = self.run_check(profile, "THREAD_API_KEY=file-secret\n", {"THREAD_API_KEY": ""})
            self.assertEqual(code, 1)
            self.assertIn("Process THREAD_API_KEY overrides", output)
            self.assertNotIn("file-secret", output)

    def test_sdk_alias_alone_does_not_pass(self):
        for profile in ("app", "participant"):
            code, output = self.run_check(profile, "GEMINI_API_KEY=unsupported-secret\n")
            self.assertEqual(code, 1)
            self.assertIn("SDK names", output)
            self.assertNotIn("unsupported-secret", output)

    def test_participant_does_not_automatically_load_root_env(self):
        code, output = self.run_check("participant", "THREAD_API_KEY=file-secret\n", {"PARTICIPANT_ENV_FILE": ""})
        self.assertEqual(code, 1)
        self.assertIn("process environment only", output)

    def test_invalid_model_value_and_paths_are_not_echoed(self):
        code, output = self.run_check("participant", "THREAD_API_KEY=fixture-secret\nTHREAD_MODEL=private-not-a-model\n")
        self.assertEqual(code, 1)
        self.assertNotIn("private-not-a-model", output)
        code, output = self.run_check("participant", "", {"PARTICIPANT_ENV_FILE": "missing/private-config-name/.env"})
        self.assertEqual(code, 1)
        self.assertNotIn("private-config-name", output)

    def test_app_rejects_live_model_as_planner_and_blank_live_override(self):
        for env in ({"THREAD_MODEL": "gemini-3.8-live"}, {"THREAD_LIVE_MODEL": ""}):
            code, output = self.run_check("app", "THREAD_API_KEY=fixture-secret\n", env)
            self.assertEqual(code, 1, output)

    def test_process_alias_group_takes_precedence_over_file(self):
        values = "THREAD_API_KEY=file-secret\nTHREAD_MODEL=gemini-3.5-flash-lite\n"
        code, output = self.run_check("participant", values, {
            "SECRET_GEMINI_API_KEY": "process-secret", "PARTICIPANT_MODEL": "gemini-2.5-flash"})
        self.assertEqual(code, 0, output)
        self.assertIn("entire SECRET_GEMINI_API_KEY / THREAD_API_KEY alias group", output)
        self.assertNotIn("process-secret", output)
        self.assertNotIn("file-secret", output)

    def test_blank_process_alias_suppresses_other_file_alias(self):
        code, output = self.run_check("participant", "THREAD_API_KEY=file-secret\n", {"SECRET_GEMINI_API_KEY": ""})
        self.assertEqual(code, 1, output)
        self.assertIn("No usable key", output)

    def test_conflicting_process_aliases_fail_even_when_file_is_valid(self):
        code, output = self.run_check("participant", "THREAD_API_KEY=file-secret\n", {
            "THREAD_API_KEY": "process-secret-one", "SECRET_GEMINI_API_KEY": "process-secret-two"})
        self.assertEqual(code, 1)
        self.assertIn("Conflicting", output)
        self.assertNotIn("process-secret-one", output)
        self.assertNotIn("process-secret-two", output)


if __name__ == "__main__":
    unittest.main()
