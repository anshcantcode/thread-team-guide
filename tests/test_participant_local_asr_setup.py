"""Offline setup checks for the opt-in CUDA acoustic provider."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from participant.local_asr import ASRUnavailableError
from participant.planner import Planner, PlannerError


class LocalASRSetupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        environment = patch.dict(os.environ, {
            'SECRET_GEMINI_API_KEY': 'offline-only',
            'PARTICIPANT_MEDIA_ROOT': str(self.root),
            'PARTICIPANT_PREWARM': '0',
        }, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def planner(self):
        planner = Planner(transport=httpx.MockTransport(
            lambda _: self.fail('Setup must not contact Gemini.')))
        self.addAsyncCleanup(planner.close)
        return planner

    async def test_default_never_constructs_local_asr(self):
        with patch('participant.local_asr.LocalASR') as local_asr:
            planner = self.planner()
            await planner.setup()

        local_asr.assert_not_called()
        self.assertEqual(planner.acoustic_provider, 'gemini')
        self.assertIsNone(planner._local_asr)

    async def test_cuda_opt_in_prewarm_runs_once(self):
        os.environ['PARTICIPANT_ACOUSTIC_PROVIDER'] = 'local_whisper_cuda'
        with patch('participant.local_asr.LocalASR') as local_asr:
            planner = self.planner()
            await planner.setup()
            await planner.setup()

        local_asr.assert_called_once_with(device='cuda', compute_type='float16')
        local_asr.return_value.prewarm.assert_called_once_with()
        self.assertIs(planner._local_asr, local_asr.return_value)

    async def test_unavailable_cuda_provider_fails_without_fallback(self):
        os.environ['PARTICIPANT_ACOUSTIC_PROVIDER'] = 'local_whisper_cuda'
        with patch('participant.local_asr.LocalASR') as local_asr:
            local_asr.return_value.prewarm.side_effect = ASRUnavailableError(
                'The pinned local speech model is unavailable.')
            planner = self.planner()
            with self.assertRaisesRegex(
                PlannerError,
                r'local_whisper_cuda failed to prewarm: The pinned local speech model is unavailable\.; no fallback was selected',
            ):
                await planner.setup()

        self.assertIsNone(planner.client)
        self.assertIsNone(planner._local_asr)


if __name__ == '__main__':
    unittest.main()
