"""Focused package-boundary checks; no participant, model or provider execution."""
import asyncio
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


package = load("package_samsung_submission")
verify = load("verify_samsung_submission")
TEMPLATE = (ROOT / "tests/fixtures/submission/gemini.env.example").read_bytes().replace(b"\r\n", b"\n")


class PackageBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="samsung-package-boundary-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()

    def put(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_only_reviewed_template_content_accepts_lf_or_crlf(self):
        self.assertEqual(package.digest(TEMPLATE), package.ENV_TEMPLATE_SHA256)
        for data in (TEMPLATE, TEMPLATE.replace(b"\n", b"\r\n")):
            with self.subTest(line_endings="CRLF" if b"\r" in data else "LF"):
                path = self.put(".env.example", data)
                self.assertEqual(package.read_member(self.root, path), (".env.example", data))
        for data in (TEMPLATE.replace(b"THREAD_API_KEY=\n", b"THREAD_API_KEY=filled-key\n"),
                     TEMPLATE.replace(b"gemini-3.5-flash-lite", b"gemini-different"), TEMPLATE + b"# extra\n"):
            with self.subTest(changed_content=True):
                with self.assertRaisesRegex(ValueError, "reviewed blank template"):
                    package.read_member(self.root, self.put(".env.example", data))

    def test_template_exception_does_not_allow_other_env_paths(self):
        for name in (".env", ".env.local", ".env.example.backup", "nested/.env.example", ".env.folder/example.txt"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "private/runtime"):
                package.read_member(self.root, self.put(name, TEMPLATE))

    def test_existing_credential_detector_still_rejects_ordinary_files(self):
        for value in (b"AIza" + b"A" * 35, b"-----BEGIN PRIVATE KEY-----"):
            with self.subTest(pattern=value[:4]), self.assertRaisesRegex(ValueError, "credential-shaped"):
                package.read_member(self.root, self.put("participant/sample.py", value))

    def make_source_and_kit(self):
        source, kit = self.root / "source", self.root / "kit"
        for name in package.SOURCE_FILES:
            self.put("source/" + name, TEMPLATE if name == ".env.example" else ("source:" + name).encode())
        for name in package.REQUIRED_RUNTIME:
            self.put("source/participant/" + name, b"# fixture only\n")
        self.put("source/docs/submission/GEMINI_QUICKSTART.md", b"fixture quickstart")
        for name in package.KIT_FILES:
            self.put("kit/" + name, ("original:" + name).encode())
        return source, kit

    def test_collect_includes_onboarding_and_preserves_official_bytes(self):
        source, kit = self.make_source_and_kit()
        payload, record = package.collect(kit, source)
        for name in (".env.example", "scripts/check_gemini_config.py", "docs/GEMINI_SETUP.md", "docs/submission/GEMINI_QUICKSTART.md"):
            self.assertEqual(payload[name], (source / name).read_bytes())
        for name, digest in record["official_kit_files"].items():
            self.assertEqual(payload[name], (kit / name).read_bytes())
            self.assertEqual(package.digest(payload[name]), digest)
        self.assertEqual(record["original_submission_yaml_sha256"], package.digest((kit / "submission.yaml").read_bytes()))
        self.put("kit/docs/GEMINI_SETUP.md", b"existing official document")
        with self.assertRaisesRegex(ValueError, "replace official files"):
            package.collect(kit, source)

    def test_unlisted_runtime_documents_tests_and_private_files_stay_out(self):
        source, kit = self.make_source_and_kit()
        for name in ("participant/private_probe.py", "participant/weights.bin",
                     "docs/submission/private-notes.md", "evaluation/submission_delivery/answers.json",
                     ".runtime/secret.txt", ".env", "tests/holdout.py"):
            self.put("source/" + name, b"private fixture must never be copied")
        self.put("kit/docs/local-notes.md", b"unreviewed kit addition")
        payload, record = package.collect(kit, source)
        self.assertEqual(set(payload), set(package.KIT_FILES) | set(package.SOURCE_FILES) |
                         {"participant/" + name for name in package.REQUIRED_RUNTIME} | {"PACKAGE_MANIFEST.json"})
        self.assertEqual(len(record["official_kit_files"]), len(package.KIT_FILES) - 1)

    def test_verifier_rejects_changed_official_and_unmanifested_candidate_files(self):
        source, kit = self.make_source_and_kit()
        payload, _ = package.collect(kit, source)
        candidate = self.root / "candidate"
        for name, data in payload.items():
            self.put("candidate/" + name, data)
        self.assertTrue(verify.verify_manifest(candidate, kit)["present"])
        extra = self.put("candidate/.env", b"private fixture")
        with self.assertRaisesRegex(RuntimeError, "unmanifested"):
            verify.verify_manifest(candidate, kit)
        extra.unlink()
        self.put("kit/harness/scorer.py", b"changed scorer")
        with self.assertRaisesRegex(RuntimeError, "official kit hash mismatch"):
            verify.verify_manifest(candidate, kit)

    def prepare_doctor(self, content):
        self.put(".env.example", TEMPLATE)
        self.put("docs/GEMINI_SETUP.md", b"fixture setup")
        self.put("docs/submission/GEMINI_QUICKSTART.md", b"fixture quickstart")
        self.put("scripts/check_gemini_config.py", content)

    def test_verifier_delivers_doctor_help_without_loading_key_or_participant(self):
        self.prepare_doctor(b"import argparse\np=argparse.ArgumentParser()\np.add_argument('--profile', choices=['app','participant'])\np.parse_args()\nraise AssertionError('configuration must not run for help')\n")
        with verify.offline_environment() as attempts:
            result = verify.verify_onboarding(self.root)
        self.assertEqual(result["doctor_help"], "passed")
        self.assertEqual(attempts, [])
        (self.root / "docs/GEMINI_SETUP.md").unlink()
        with self.assertRaisesRegex(RuntimeError, "missing onboarding file"):
            verify.verify_onboarding(self.root)

    def test_doctor_help_remains_inside_external_network_guard(self):
        self.prepare_doctor(b"import socket\nsocket.getaddrinfo('example.invalid', 443)\n")
        with verify.offline_environment() as attempts:
            with self.assertRaisesRegex(RuntimeError, "external DNS disabled"):
                verify.verify_onboarding(self.root)
        self.assertEqual(attempts, ["dns"])

    def test_selected_profile_matches_real_runtime_without_setup_requests(self):
        for selected in verify.AUDIO_MODES:
            with self.subTest(audio_mode=selected), verify.offline_environment() as attempts:
                result = asyncio.run(verify.verify_configuration(ROOT, selected))
            self.assertEqual(attempts, [])
            self.assertEqual(result["mocked_setup_requests"], 0)
            self.assertEqual(result["key_only_setup"], "passed")
            self.assertEqual(result["explicit_process_setup"], "passed")
            self.assertEqual(result["explicit_file_setup"], "passed")
            self.assertEqual(result["selected_profile"]["PARTICIPANT_AUDIO_MODE"], selected)
            self.assertEqual(result["effective_audio_modes"], {
                "key_only": "independent", "explicit_process": selected, "explicit_file": selected})
            self.assertEqual(result["experimental_audio_mode"], selected == "single_call_reads")

    def test_verifier_rejects_invalid_audio_mode_before_setup(self):
        with verify.offline_environment() as attempts:
            with self.assertRaisesRegex(RuntimeError, "unsupported audio mode"):
                asyncio.run(verify.verify_configuration(ROOT, "invalid-private-mode"))
            output = io.StringIO()
            with patch.object(sys, "argv", ["verify_samsung_submission.py", "--kit", str(self.root),
                                           "--audio-mode", "INVALID"]), contextlib.redirect_stderr(output):
                with self.assertRaises(SystemExit) as result:
                    verify.main()
            self.assertEqual(result.exception.code, 2)
        self.assertEqual(attempts, [])

    def test_profile_drift_in_quickstart_is_rejected(self):
        self.prepare_doctor((ROOT / "scripts/check_gemini_config.py").read_bytes())
        with verify.offline_environment() as attempts:
            with self.assertRaisesRegex(RuntimeError, "quickstart differs"):
                asyncio.run(verify.verify_configuration(self.root))
        self.assertEqual(attempts, [])


if __name__ == "__main__":
    unittest.main()
