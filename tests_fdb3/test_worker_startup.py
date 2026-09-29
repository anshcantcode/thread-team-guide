import argparse
import json
from pathlib import Path
import tempfile
import unittest
import wave

from scripts.fdb3_audio_worker import run


class StartupEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_contract_records_failure_before_loading_speech_or_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root/'authored.wav'
            with wave.open(str(audio),'wb') as handle:
                handle.setparams((1,2,24000,0,'NONE','not compressed'))
                handle.writeframes(b'\0\0'*240)
            output = root/'result'
            args = argparse.Namespace(output=str(output),audio=str(audio),manual=False,
                unpaced=False,room=False,endpoint='http://127.0.0.1:9/v1',model='unused',
                contract=str(root/'absent-contract'),whisper='unused')
            with self.assertRaises(FileNotFoundError):
                await run(args)
            body = json.loads((output/'result.json').read_text())
            self.assertEqual(body['status'],'infrastructure_error')
            self.assertEqual(body['error_type'],'FileNotFoundError')
            self.assertEqual(body['actual_tool_calls'],[])
            self.assertEqual(body['model_requests'],[])
