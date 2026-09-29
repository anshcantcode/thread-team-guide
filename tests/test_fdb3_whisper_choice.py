"""CPU-only recognizer selection/pinning controls; synthetic bytes, no downloads."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts import fdb3_config, setup_speech


MODEL_ENV = "THREAD_FDB3_WHISPER_MODEL"
NAMES = ("base.en", "small.en")
FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")


def authored_model(name):
    config = fdb3_config.load_config({MODEL_ENV: name})
    contents = {file: ("authored-" + (name if file in FILES[:2] else "shared") + file).encode()
                for file in FILES}
    config["whisper"]["sha256"] = {file: hashlib.sha256(data).hexdigest()
                                    for file, data in contents.items()}
    return config, contents


def write_assets(directory, contents):
    directory.mkdir(parents=True, exist_ok=True)
    for file, data in contents.items():
        (directory / file).write_bytes(data)


class WhisperSelectionTests(unittest.TestCase):
    def test_unset_uses_only_the_catalog_default(self):
        catalog = json.loads(fdb3_config.CONFIG.read_text())["whisper"]
        self.assertEqual(fdb3_config.load_config({})["whisper"]["name"], catalog["default_model"])

    def test_explicit_choices_resolve_all_identity_fields(self):
        catalog = json.loads(fdb3_config.CONFIG.read_text())["whisper"]
        for name in NAMES:
            with self.subTest(name=name):
                config = fdb3_config.load_config({MODEL_ENV: name})
                self.assertEqual(config["whisper"], {"name": name, **catalog["models"][name]})
                self.assertEqual(config["environment"][MODEL_ENV], name)

    def test_invalid_empty_case_and_path_choices_fail_closed(self):
        for value in ("", "small", "small.EN", " small.en", "small.en ", "../small.en", "main"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, MODEL_ENV):
                fdb3_config.load_config({MODEL_ENV: value})

    def test_explicit_environ_does_not_leak_process_choice(self):
        with patch.dict(os.environ, {MODEL_ENV: "invalid"}):
            self.assertEqual(fdb3_config.load_config({MODEL_ENV: "small.en"})["whisper"]["name"], "small.en")
            self.assertIn(fdb3_config.load_config({})["whisper"]["name"], NAMES)

    def test_changing_one_default_updates_config_environment_and_shell(self):
        original = json.loads(fdb3_config.CONFIG.read_text())
        for name in NAMES:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                config = copy.deepcopy(original)
                config["whisper"]["default_model"] = name
                path = Path(directory) / "candidate.json"
                path.write_text(json.dumps(config))
                with patch.object(fdb3_config, "CONFIG", path), patch.dict(os.environ, {}, clear=True):
                    self.assertEqual(fdb3_config.load_config()["whisper"]["name"], name)
                    self.assertEqual(fdb3_config.candidate_environment()[MODEL_ENV], name)
                    self.assertIn(f"export {MODEL_ENV}={name}", fdb3_config.shell_config())

    def test_choice_is_independent_of_device_profile(self):
        for name in NAMES:
            for profile, device in (("candidate", "cuda"), ("cpu-component", "cpu")):
                with self.subTest(name=name, profile=profile):
                    values = fdb3_config.candidate_environment(profile, {MODEL_ENV: name})
                    self.assertEqual(values[MODEL_ENV], name)
                    self.assertEqual(values["THREAD_FDB3_WHISPER_DEVICE"], device)

    def test_shell_exports_selected_repo_revision_and_every_hash(self):
        for name in NAMES:
            with self.subTest(name=name), patch.dict(os.environ, {MODEL_ENV: name}, clear=True):
                selected = fdb3_config.load_config()["whisper"]
                shell = fdb3_config.shell_config()
                self.assertIn("WHISPER_REPO=" + selected["repo"], shell)
                self.assertIn("WHISPER_REV=" + selected["revision"], shell)
                for file, sha in selected["sha256"].items():
                    self.assertIn(f"[{file}]={sha}", shell)

    def test_revisions_and_four_full_sha256_pins_are_immutable(self):
        expected = {
            "base.en": ("3d3d5dee26484f91867d81cb899cfcf72b96be6c",
                        "2a166925539a16005f14ff328359f9b9adb9dc4fb631bb3b227526862e93e2ef",
                        "f3bc3821e9fc76a27bae538e11ae5b677dcdd352b4600429ce7951d398569aeb"),
            "small.en": ("d1d751a5f8271d482d14ca55d9e2deeebbae577f",
                         "62b2a45b05ee59acb4a5341b33ee35e041395d378d418a18acfe4c9e768ee37a",
                         "666a9605530ac1f61fa8177f3702b4dacec9966749e42610839fcc32661d5fae"),
        }
        for name, (revision, model, config) in expected.items():
            with self.subTest(name=name):
                pins = fdb3_config.load_config({MODEL_ENV: name})["whisper"]
                self.assertEqual(pins["repo"], "Systran/faster-whisper-" + name)
                self.assertEqual(pins["revision"], revision)
                self.assertEqual(pins["sha256"], {
                    "model.bin": model, "config.json": config,
                    "tokenizer.json": "929c5252409436dce1b38a75d1abbcb5e132d170d8e324e4e04ed915fa2d22df",
                    "vocabulary.txt": "ff77588746d3a2595d32ab5b69ffd7b95ce2441ac57533cb66fc3eb575a115cf"})


class WhisperHashTests(unittest.TestCase):
    def test_complete_selected_assets_return_exact_identity(self):
        for name in NAMES:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                config, contents = authored_model(name)
                write_assets(Path(directory), contents)
                self.assertEqual(fdb3_config.verify_whisper(directory, config=config), config["whisper"])

    def test_each_missing_file_is_rejected_for_each_choice(self):
        for name in NAMES:
            for missing in FILES:
                with self.subTest(name=name, missing=missing), tempfile.TemporaryDirectory() as directory:
                    config, contents = authored_model(name)
                    write_assets(Path(directory), {f: b for f, b in contents.items() if f != missing})
                    with self.assertRaisesRegex(ValueError, "Missing .*" + missing):
                        fdb3_config.verify_whisper(directory, config=config)

    def test_each_corrupt_file_is_rejected_and_preserved(self):
        for name in NAMES:
            for corrupt in FILES:
                with self.subTest(name=name, corrupt=corrupt), tempfile.TemporaryDirectory() as directory:
                    config, contents = authored_model(name)
                    contents[corrupt] += b"corrupt"
                    write_assets(Path(directory), contents)
                    with self.assertRaisesRegex(ValueError, "SHA-256 mismatch.*" + corrupt):
                        fdb3_config.verify_whisper(directory, config=config)
                    self.assertEqual((Path(directory) / corrupt).read_bytes(), contents[corrupt])

    def test_base_and_small_are_not_interchangeable(self):
        for selected, installed in (("small.en", "base.en"), ("base.en", "small.en")):
            with self.subTest(selected=selected), tempfile.TemporaryDirectory() as directory:
                config, _ = authored_model(selected)
                _, contents = authored_model(installed)
                write_assets(Path(directory), contents)
                with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                    fdb3_config.verify_whisper(directory, config=config)


class SpeechSetupTests(unittest.TestCase):
    def setUp(self):
        self.download = Mock()
        self.model = Mock()
        modules = {"huggingface_hub": SimpleNamespace(snapshot_download=self.download),
                   "faster_whisper": SimpleNamespace(WhisperModel=self.model)}
        stub = patch.dict(sys.modules, modules)
        stub.start()
        self.addCleanup(stub.stop)

    def test_download_is_revision_pinned_limited_and_verified_for_both_choices(self):
        for name in NAMES:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                config, contents = authored_model(name)
                target = Path(directory) / "model"
                self.download.reset_mock()
                self.download.side_effect = lambda *a, **kw: write_assets(Path(kw["local_dir"]), contents)
                with patch.object(setup_speech, "load_config", return_value=config):
                    identity = setup_speech.prepare_model(target, download_only=True)
                self.download.assert_called_once_with(config["whisper"]["repo"],
                    revision=config["whisper"]["revision"], allow_patterns=list(config["whisper"]["sha256"]),
                    local_dir=str(target), token=False)
                self.assertEqual(identity["sha256"], config["whisper"]["sha256"])
                self.assertEqual(identity["name"], name)
        self.model.assert_not_called()

    def test_bad_download_never_loads_a_model(self):
        with tempfile.TemporaryDirectory() as directory:
            config, contents = authored_model("small.en")
            contents["model.bin"] = b"wrong download"
            self.download.side_effect = lambda *a, **kw: write_assets(Path(kw["local_dir"]), contents)
            with patch.object(setup_speech, "load_config", return_value=config), \
                 self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                setup_speech.prepare_model(Path(directory) / "model")
        self.model.assert_not_called()

    def test_default_directory_follows_the_resolved_choice(self):
        for name in NAMES:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                config, contents = authored_model(name)
                root = Path(directory)
                target = root / ".runtime" / ("whisper-" + name.replace(".", "-"))
                self.download.side_effect = lambda *a, **kw: write_assets(Path(kw["local_dir"]), contents)
                with patch.object(setup_speech, "load_config", return_value=config), \
                     patch.object(setup_speech, "ROOT", root):
                    identity = setup_speech.prepare_model(download_only=True)
                self.assertEqual(identity["directory"], str(target.resolve()))
                self.assertFalse(identity["warmup_performed"])
        self.model.assert_not_called()

    def test_warmup_is_cpu_local_only_even_with_cuda_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            config, contents = authored_model("small.en")
            write_assets(Path(directory), contents)
            with patch.object(setup_speech, "load_config", return_value=config), \
                 patch.dict(os.environ, {"THREAD_FDB3_WHISPER_DEVICE": "cuda"}):
                identity = setup_speech.prepare_model(directory)
            self.model.assert_called_once_with(directory, device="cpu", compute_type="int8",
                cpu_threads=2, num_workers=1, local_files_only=True)
            self.assertEqual(identity["status"], "CPU_READY")
        self.download.assert_not_called()

    def test_check_only_verifies_without_download_or_model_import(self):
        with tempfile.TemporaryDirectory() as directory:
            config, contents = authored_model("small.en")
            write_assets(Path(directory), contents)
            with patch.object(setup_speech, "load_config", return_value=config):
                self.assertEqual(setup_speech.prepare_model(directory, check_only=True)["status"], "VERIFIED")
        self.download.assert_not_called()
        self.model.assert_not_called()

    def test_missing_check_only_does_not_create_a_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "absent"
            with self.assertRaisesRegex(ValueError, "Missing"):
                setup_speech.prepare_model(target, check_only=True)
            self.assertFalse(target.exists())
        self.download.assert_not_called()
        self.model.assert_not_called()

    def test_existing_wrong_or_partial_assets_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "model.bin"
            marker.write_bytes(b"owner bytes")
            with self.assertRaises(ValueError):
                setup_speech.prepare_model(directory)
            self.assertEqual(marker.read_bytes(), b"owner bytes")
        self.download.assert_not_called()
        self.model.assert_not_called()

    def test_cli_invalid_choice_fails_before_download(self):
        result = subprocess.run([sys.executable, str(Path(setup_speech.__file__)), "--download-only"],
            env=dict(os.environ, **{MODEL_ENV: "wrong", "PYTHONDONTWRITEBYTECODE": "1"}),
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn(MODEL_ENV + " must be base.en or small.en", result.stderr)

    def test_config_cli_offline_check_rejects_missing_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in NAMES:
                with self.subTest(name=name):
                    result = subprocess.run([sys.executable, str(Path(fdb3_config.__file__)),
                        "--verify-whisper", directory],
                        env=dict(os.environ, **{MODEL_ENV: name, "PYTHONDONTWRITEBYTECODE": "1"}),
                        capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("Missing " + name, result.stderr)


if __name__ == "__main__":
    unittest.main()
