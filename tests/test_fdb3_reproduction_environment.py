"""Fresh reproduction may not reuse or overwrite an existing environment."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.fdb3_local_reproduce import environment_path


class ReproductionEnvironmentTests(unittest.TestCase):
    def test_new_environment_stays_inside_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            # Match the canonical production ROOT, including Windows 8.3 aliases.
            root=Path(directory).resolve()
            with patch('scripts.fdb3_local_reproduce.ROOT',root):
                self.assertEqual(environment_path(Path('.venv-fresh')),root/'.venv-fresh')
                self.assertEqual(environment_path(),root/'.venv-fdb3')
                for candidate in [root, root.parent/'outside', Path('../outside')]:
                    with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                        environment_path(candidate)

    def test_existing_environment_and_file_are_rejected_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve(); existing=root/'old';existing.mkdir()
            marker=existing/'owner.txt';marker.write_text('preserve')
            with patch('scripts.fdb3_local_reproduce.ROOT',root):
                for candidate in [existing,marker]:
                    with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                        environment_path(candidate)
            self.assertEqual(marker.read_text(),'preserve')
