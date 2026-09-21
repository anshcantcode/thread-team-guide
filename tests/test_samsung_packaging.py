"""Focused package-boundary checks; no participant, model or provider execution."""
import importlib.util
from pathlib import Path
import tempfile
import unittest


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
                     TEMPLATE.replace(b"gemini-2.5-flash", b"gemini-different"), TEMPLATE + b"# extra\n"):
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
        for directory in package.KIT_DIRS:
            self.put("kit/" + directory + "/fixture.txt", ("original:" + directory).encode())
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


if __name__ == "__main__":
    unittest.main()
