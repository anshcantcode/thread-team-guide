"""Offline configuration contract for the optional audio admission profile."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from participant.planner import Planner, PlannerError


class AudioModeConfigTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        environment = patch.dict(os.environ, {'SECRET_GEMINI_API_KEY': 'offline-only',
            'PARTICIPANT_MEDIA_ROOT': str(self.root), 'PARTICIPANT_PREWARM': '0'}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def planner(self):
        def reject(request):
            self.fail('Configuration must not make provider requests.')
        planner = Planner(transport=httpx.MockTransport(reject))
        self.addAsyncCleanup(planner.close)
        return planner

    async def test_default_and_explicit_profiles(self):
        self.assertEqual(self.planner().audio_mode, 'independent')
        for setting in (None, '', 'independent', 'single_call_reads'):
            with self.subTest(setting=setting):
                if setting is None:
                    os.environ.pop('PARTICIPANT_AUDIO_MODE', None)
                else:
                    os.environ['PARTICIPANT_AUDIO_MODE'] = setting
                planner = self.planner()
                await planner.setup()
                self.assertEqual(planner.audio_mode, setting or 'independent')
                self.assertEqual((planner.timeout, planner.acoustic_timeout), (4.5, 3.5))

    async def test_process_overrides_generated_mode_file_including_blank(self):
        path = self.root / 'mode.env'
        # This generated file contains a mode only, never real credentials.
        path.write_text('PARTICIPANT_AUDIO_MODE=single_call_reads\n', encoding='utf-8')
        os.environ['PARTICIPANT_ENV_FILE'] = str(path)
        for setting, expected in ((None, 'single_call_reads'), ('independent', 'independent'), ('', 'independent')):
            with self.subTest(setting=setting):
                if setting is None:
                    os.environ.pop('PARTICIPANT_AUDIO_MODE', None)
                else:
                    os.environ['PARTICIPANT_AUDIO_MODE'] = setting
                planner = self.planner()
                await planner.setup()
                self.assertEqual(planner.audio_mode, expected)

    async def test_unknown_profiles_fail_before_client_creation(self):
        for setting in ('joint', 'INDEPENDENT', ' single_call_reads', '0'):
            with self.subTest(setting=setting):
                os.environ['PARTICIPANT_AUDIO_MODE'] = setting
                planner = self.planner()
                with self.assertRaisesRegex(PlannerError, 'PARTICIPANT_AUDIO_MODE'):
                    await planner.setup()
                self.assertIsNone(planner.client)


if __name__ == '__main__':
    unittest.main()
