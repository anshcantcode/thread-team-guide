"""Offline setup failures must be actionable without exposing credentials."""
import contextlib
import asyncio
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.check_gemini_config import check, PARTICIPANT_DEFAULTS


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
                code, output = self.run_check(profile, "THREAD_API_KEY=fixture-secret-never-display\nTHREAD_MODEL=gemini-3.5-flash-lite\n")
                self.assertEqual(code, 0, output)
                self.assertNotIn("fixture-secret-never-display", output)
                self.assertIn("No network requests made", output)

    def test_conflicting_aliases_fail_without_exposure(self):
        for values in ("THREAD_API_KEY=first-secret\nSECRET_GEMINI_API_KEY=second-secret\n",
                       "THREAD_API_KEY=first-secret\nTHREAD_MODEL=gemini-3.8-flash\nPARTICIPANT_MODEL=gemini-3.5-flash-lite\n"):
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
        values = "THREAD_API_KEY=file-secret\nTHREAD_MODEL=gemini-3.8-flash\n"
        code, output = self.run_check("participant", values, {
            "SECRET_GEMINI_API_KEY": "process-secret", "PARTICIPANT_MODEL": "gemini-3.5-flash-lite"})
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

    def test_selected_profile_and_key_only_configuration_pass(self):
        for values in ("", "\n".join(f"{name}={value}" for name, value in PARTICIPANT_DEFAULTS.items())):
            code, output = self.run_check("participant", values, {"SECRET_GEMINI_API_KEY": "synthetic-secret"})
            self.assertEqual(code, 0, output)
            self.assertNotIn("synthetic-secret", output)

    def test_invalid_or_different_profile_settings_fail_without_values(self):
        cases = {
            "PARTICIPANT_THINKING_LEVEL": ("invalid-private-level", "high"),
            "PARTICIPANT_THINKING_BUDGET": ("0", "private-budget"),
            "PARTICIPANT_TIMEOUT_SECONDS": ("nan", "inf", "-1", "0", "5.6", "private-timeout"),
            "PARTICIPANT_PREWARM": ("true", "1"),
            "PARTICIPANT_IMAGE_EMBEDDING": ("false", "0"),
            "PARTICIPANT_MODEL": ("gemini-2.5-flash", "gemini-3.8-flash"),
            "PARTICIPANT_MEDIA_ROOT": ("missing/private-media-folder",),
        }
        for name, values in cases.items():
            for value in values:
                with self.subTest(name=name, value=value):
                    code, output = self.run_check("participant", "THREAD_API_KEY=synthetic-secret\n",
                                                   {name: value})
                    self.assertEqual(code, 1, output)
                    self.assertNotIn("synthetic-secret", output)
                    self.assertNotIn("private-", output)

    def test_real_planner_alias_tiers_match_offline_doctor(self):
        import httpx
        from participant.planner import Planner, PlannerError
        from scripts.verify_samsung_submission import offline_environment

        with tempfile.TemporaryDirectory() as folder:
            env_file = Path(folder) / "settings.env"
            env_file.write_text("THREAD_API_KEY=file-secret\nTHREAD_MODEL=gemini-3.8-flash\n"
                                "PARTICIPANT_PREWARM=0\n", encoding="utf-8")

            async def exercise():
                def reject(_):
                    self.fail("setup must not call any provider")
                planner = Planner(transport=httpx.MockTransport(reject))
                try:
                    await planner.setup()
                    return planner._key, planner.model
                finally:
                    await planner.close()

            for overrides, key, error in (
                ({"SECRET_GEMINI_API_KEY": "process-secret"}, "process-secret", False),
                ({"SECRET_GEMINI_API_KEY": "process-secret", "PARTICIPANT_MODEL": ""}, "process-secret", False),
                ({"SECRET_GEMINI_API_KEY": "process-secret", "THREAD_API_KEY": "process-secret"}, "process-secret", False),
                ({"SECRET_GEMINI_API_KEY": ""}, "", False),
                ({"SECRET_GEMINI_API_KEY": "one-secret", "THREAD_API_KEY": "another-secret"}, None, True),
            ):
                env = {"PARTICIPANT_ENV_FILE": str(env_file),
                       "PARTICIPANT_MODEL": PARTICIPANT_DEFAULTS["THREAD_MODEL"], **overrides}
                with offline_environment() as network_attempts, patch.dict("os.environ", env), \
                        contextlib.redirect_stdout(io.StringIO()):
                    code = check("participant", env, Path(folder))
                    if error:
                        with self.assertRaises(PlannerError):
                            asyncio.run(exercise())
                    else:
                        loaded_key, model = asyncio.run(exercise())
                        self.assertEqual(loaded_key, key)
                        self.assertEqual(model, PARTICIPANT_DEFAULTS["THREAD_MODEL"])
                    self.assertEqual(code, 1 if error or not key else 0)
                    self.assertEqual(network_attempts, [])

    def test_audio_mode_doctor_matches_real_resolver(self):
        import httpx
        from participant.planner import Planner, PlannerError
        from scripts.verify_samsung_submission import offline_environment

        cases = (
            (None, None, "independent"),
            ("", None, "independent"),
            (None, "", "independent"),
            (None, "independent", "independent"),
            ("single_call_reads", None, "single_call_reads"),
            (None, "single_call_reads", "single_call_reads"),
            ("single_call_reads", "", "independent"),
            ("single_call_reads", "independent", "independent"),
            ("independent", "single_call_reads", "single_call_reads"),
            ("private-invalid-mode", "independent", "independent"),
            ("private-invalid-mode", None, None),
            ("independent", "private-invalid-mode", None),
            (None, "INDEPENDENT", None),
            (None, " independent ", None),
            (" ", None, None),
        )
        with tempfile.TemporaryDirectory() as folder:
            env_file = Path(folder) / "settings.env"
            for file_mode, process_mode, expected in cases:
                with self.subTest(file=file_mode, process=process_mode):
                    values = "THREAD_API_KEY=synthetic-secret\n"
                    if file_mode is not None:
                        values += "PARTICIPANT_AUDIO_MODE=" + json.dumps(file_mode) + "\n"
                    env_file.write_text(values, encoding="utf-8")
                    env = {"PARTICIPANT_ENV_FILE": str(env_file)}
                    if process_mode is not None:
                        env["PARTICIPANT_AUDIO_MODE"] = process_mode
                    output = io.StringIO()

                    async def exercise():
                        def reject(_):
                            self.fail("audio mode configuration must not contact a provider")
                        planner = Planner(transport=httpx.MockTransport(reject))
                        try:
                            if expected is None:
                                with self.assertRaises(PlannerError):
                                    await planner.setup()
                                self.assertIsNone(planner.client)
                            else:
                                await planner.setup()
                                self.assertEqual(planner.audio_mode, expected)
                        finally:
                            await planner.close()

                    with offline_environment() as attempts, patch.dict("os.environ", env), \
                            contextlib.redirect_stdout(output):
                        code = check("participant", env, Path(folder))
                        asyncio.run(exercise())
                    self.assertEqual(code, 1 if expected is None else 0, output.getvalue())
                    self.assertEqual(attempts, [])
                    self.assertNotIn("synthetic-secret", output.getvalue())
                    self.assertNotIn("private-invalid-mode", output.getvalue())
                    self.assertEqual("Experimental audio mode" in output.getvalue(), expected == "single_call_reads")


if __name__ == "__main__":
    unittest.main()
