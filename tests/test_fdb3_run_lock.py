import os
from pathlib import Path
import tempfile
import unittest

from scripts.fdb3_run import campaign_lock


class CampaignLockTests(unittest.TestCase):
    def test_preparation_failure_releases_owned_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "preparation"):
                with campaign_lock(root):
                    self.assertEqual((root / "campaign.lock").read_text(), str(os.getpid()))
                    raise ValueError("preparation failed before report creation")
            self.assertFalse((root / "campaign.lock").exists())

    def test_existing_owner_is_not_changed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = root / "campaign.lock"
            lock.write_text("other owner")
            with self.assertRaises(FileExistsError):
                with campaign_lock(root):
                    self.fail("Entered a concurrent campaign")
            self.assertEqual(lock.read_text(), "other owner")

    def test_replaced_lock_is_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with campaign_lock(root):
                (root / "campaign.lock").write_text("new owner")
            self.assertEqual((root / "campaign.lock").read_text(), "new owner")
