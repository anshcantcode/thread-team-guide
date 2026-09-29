"""One-time development migration into a debug APK, then install the release APK.

Secrets travel only over adb stdin into app-private storage, are imported into
Android Keystore encrypted preferences, and the temporary file is deleted by
THREAD. Never use command arguments, intents, shared storage or logs for a key.
"""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
ADB = Path(os.environ['LOCALAPPDATA']) / 'Android/Sdk/platform-tools/adb.exe'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--replace-key', action='store_true', help='Replace an already configured phone key with the local .env key.')
    parser.add_argument('--migrate-notes', action='store_true', help='Copy the local notebook only if no phone notebook exists.')
    args = parser.parse_args()

    def adb(*words, payload=None, allow_failure=False):
        result = subprocess.run([str(ADB), '-s', args.serial, *words], input=payload, capture_output=True, timeout=40)
        if result.returncode and not allow_failure:
            raise RuntimeError('Phone provisioning command failed. Install the debug APK and check the USB connection.')
        return result

    package = adb('shell', 'dumpsys', 'package', 'com.thread.app').stdout.decode(errors='replace')
    if 'DEBUGGABLE' not in package: raise RuntimeError('Install the debug APK before provisioning. Release builds reject run-as.')
    config = dotenv_values(ROOT / '.env')
    key = config.get('THREAD_API_KEY', '')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{20,256}', key or ''): raise RuntimeError('A valid THREAD_API_KEY is required in the local .env.')
    values = {name: config[name] for name in ('THREAD_API_KEY', 'THREAD_MODEL', 'THREAD_LIVE_MODEL', 'THREAD_TIMEZONE', 'THREAD_LIVE_SEARCH') if config.get(name)}
    # Validate before touching the phone. Values never appear in diagnostic output.
    if any(len(value) > 256 or '\n' in value or '\r' in value for value in values.values()):
        raise RuntimeError('Invalid local phone configuration.')
    adb('shell', 'am', 'force-stop', 'com.thread.app')
    adb('shell', 'run-as', 'com.thread.app', 'mkdir', '-p', 'files/backend')
    existing = adb('shell', 'run-as', 'com.thread.app', 'test', '-f', 'shared_prefs/backend-credentials.xml', allow_failure=True).returncode == 0
    if not existing or args.replace_key:
        adb('shell', '-T', "run-as com.thread.app sh -c 'umask 077; cat > files/phone-config-import.json'", payload=json.dumps(values).encode())
        print('Configuration staged privately. Open THREAD to encrypt and consume it.')
    else:
        print('Existing phone credentials preserved.')
    local_notes = ROOT / 'data/notebook.sqlite3'
    phone_notes = adb('shell', 'run-as', 'com.thread.app', 'test', '-f', 'files/backend/notebook.sqlite3', allow_failure=True).returncode == 0
    if args.migrate_notes and local_notes.is_file() and not phone_notes:
        # SQLite backup API produces a consistent snapshot even if a WAL exists.
        with tempfile.TemporaryDirectory(prefix='thread-notes-') as directory:
            destination = Path(directory) / 'notebook.sqlite3'
            with closing(sqlite3.connect(local_notes.as_uri() + '?mode=ro', uri=True)) as source, closing(sqlite3.connect(destination)) as target:
                source.backup(target)
            adb('shell', '-T', "run-as com.thread.app sh -c 'umask 077; cat > files/backend/notebook-import.sqlite3'", payload=destination.read_bytes())
            adb('shell', 'run-as', 'com.thread.app', 'mv', '-n', 'files/backend/notebook-import.sqlite3', 'files/backend/notebook.sqlite3')
        print('Notebook copied into private phone storage; existing phone notebooks are never overwritten.')
    adb('shell', 'am', 'start', '-n', 'com.thread.app/.MainActivity')


if __name__ == '__main__': main()
