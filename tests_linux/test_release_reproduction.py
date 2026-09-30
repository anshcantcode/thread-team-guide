"""Release packaging and deterministic launch controls; no providers or models."""
import hashlib
import json
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import fdb3_config
from scripts.fdb3_local_reproduce import model_arguments

ROOT = Path(__file__).resolve().parents[1]


class ReleaseReproductionTests(unittest.TestCase):
    def test_linux_and_windows_launches_use_the_declared_nonrandom_seed(self):
        config = fdb3_config.load_config(environ={})
        emitted = fdb3_config.shell_config()
        array = next(line for line in emitted.splitlines() if line.startswith('LLAMA_ARGS=('))
        linux = shlex.split(array[len('LLAMA_ARGS=('):-1])
        windows = model_arguments({'model_file': 'local-model.gguf', 'gpu_layers': 0})
        for args in (linux, windows):
            self.assertEqual(args.count('--seed'), 1)
            self.assertEqual(args[args.index('--seed') + 1], str(config['llama']['seed']))
        self.assertEqual(config['llama']['seed'], 42)
        self.assertIsNone(config['llama']['historical_windows_seed'])
        for invalid in (None, 43, 42.0, True):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'seed'):
                model_arguments({'model_file': 'local-model.gguf', 'seed': invalid})

    def test_inconsistent_or_random_seed_manifest_fails_before_launch(self):
        original = json.loads((ROOT / 'config/fdb3-candidate.json').read_text())
        for value, arguments in (
            (None, original['llama']['args']),
            (4294967295, ['--seed', '4294967295']),
            (42, ['--seed', '41']),
            (42, ['--seed', '42', '--seed', '42']),
            (42, ['--seed']),
            (42, []),
        ):
            with self.subTest(value=value, arguments=arguments), tempfile.TemporaryDirectory() as directory:
                config = json.loads(json.dumps(original))
                config['llama'].update(seed=value, args=arguments)
                manifest = Path(directory) / 'candidate.json'
                manifest.write_text(json.dumps(config))
                with patch.object(fdb3_config, 'CONFIG', manifest), self.assertRaisesRegex(ValueError, 'seed'):
                    fdb3_config.load_config(environ={})

    def test_clean_source_export_snapshots_without_borrowing_parent_git_identity(self):
        # Deliberately place the export inside this checkout. A naive git call
        # would falsely assign the parent repository's commit to these bytes.
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            export = Path(directory) / 'export'
            for folder in ('participant', 'thread_agent', 'scripts', 'config'):
                (export / folder).mkdir(parents=True)
            for relative in ('scripts/fdb3_config.py', 'config/fdb3-candidate.json',
                             'requirements-fdb3.lock', 'requirements-fdb3-bench.txt',
                             'requirements-fdb3-bench.lock', 'requirements-fdb3-cuda.txt'):
                shutil.copyfile(ROOT / relative, export / relative)
            output = Path(directory) / 'snapshot'
            child = subprocess.run([sys.executable, str(export / 'scripts/fdb3_config.py'),
                                    '--snapshot', str(output)], cwd=export,
                                   capture_output=True, text=True, timeout=15)
            self.assertEqual(child.returncode, 0, child.stderr)
            identity = json.loads(child.stdout)
            self.assertEqual(identity['source_kind'], 'source_archive')
            self.assertIsNone(identity['source_commit'])
            self.assertIsNone(identity['dirty'])
            required = 'requirements-fdb3-bench.lock'
            self.assertIn(required, identity['source_hashes'])
            self.assertEqual(identity['source_hashes'][required], hashlib.sha256((ROOT / required).read_bytes()).hexdigest())
            self.assertEqual((output / required).read_bytes(), (ROOT / required).read_bytes())

    def test_evaluator_install_consumes_the_hashed_transitive_lock(self):
        launcher = (ROOT / 'scripts/reproduce_fdb3_linux.sh').read_text()
        install = next(line for line in launcher.splitlines() if 'venv-bench/bin/pip" install' in line)
        self.assertIn('--require-hashes', install)
        self.assertIn('requirements-fdb3-bench.lock', install)
        lock = (ROOT / 'requirements-fdb3-bench.lock').read_text()
        requirements = []
        for line in lock.splitlines():
            if line and not line.startswith(('#', ' ')):
                requirements.append(line)
                self.assertRegex(line, r'^[A-Za-z0-9_.-]+==[^ ]+ \\$', line)
        self.assertGreater(len(requirements), 100)
        for logical in lock.split('\n'):
            if logical.startswith('--index-url') or logical.startswith('--extra-index-url'):
                self.fail('The portable evaluator lock must not inherit a private package index')


if __name__ == '__main__':
    unittest.main()
