"""Package-evidence checks must reject private files at every archive depth."""
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
with patch.dict(os.environ, LOCALAPPDATA=os.environ.get('LOCALAPPDATA', '/tmp')):
    spec = importlib.util.spec_from_file_location('android_release_check', ROOT / 'scripts/check_android_release.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)


class AndroidPackageTests(unittest.TestCase):
    def package(self, path, private_name=None, nested=False, key=None):
        embedded = io.BytesIO()
        with zipfile.ZipFile(embedded, 'w') as archive:
            archive.writestr('thread_agent/android_backend.pyc', b'example code')
        with zipfile.ZipFile(path, 'w') as apk:
            apk.writestr('assets/chaquopy/app.imy', embedded.getvalue())
            if private_name:
                if nested:
                    data = io.BytesIO()
                    with zipfile.ZipFile(data, 'w') as archive: archive.writestr(private_name, b'private data')
                    apk.writestr('assets/chaquopy/requirements-common.imy', data.getvalue())
                else: apk.writestr(private_name, b'private data')
            if key: apk.writestr('classes.dex', key)

    def test_rejects_root_and_nested_private_files(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(checker, 'dotenv_values', return_value={'THREAD_API_KEY': 'test-key'}):
            path = Path(directory) / 'test.apk'
            for name in ('.env', 'notebook.sqlite3', 'notebook.sqlite3-wal', 'notebook.sqlite3-shm', 'phone-config-import.json', 'data/notebook.sqlite3'):
                for nested in (False, True):
                    self.package(path, name, nested)
                    with self.subTest(name=name, nested=nested), self.assertRaises(AssertionError): checker.verify_phone_package(path)

    def test_key_absence_is_unknown_without_reference_and_present_key_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.apk'
            self.package(path)
            with patch.object(checker, 'dotenv_values', return_value={}):
                self.assertIsNone(checker.verify_phone_package(path)['personal_key_absent'])
            with patch.object(checker, 'dotenv_values', return_value={'THREAD_API_KEY': 'test-key'}):
                self.assertTrue(checker.verify_phone_package(path)['personal_key_absent'])
                self.package(path, key=b'test-key')
                with self.assertRaises(AssertionError): checker.verify_phone_package(path)


if __name__ == '__main__': unittest.main()
