import hashlib
import io
import sys
import threading
import types
import unittest
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from participant import local_asr
from participant.local_asr import (
    ASREmptyAudioError,
    ASREmptyTranscriptError,
    ASRInputError,
    ASRTimeoutError,
    ASRUnavailableError,
    LocalASR,
)


def wav_bytes():
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        audio.writeframes(bytes(320))
    return output.getvalue()


class FakeModel:
    def __init__(self, texts=('hello',)):
        self.texts = texts
        self.seen_bytes = None
        self.options = None
        self.path = None

    def transcribe(self, path, **options):
        self.path = Path(path)
        self.seen_bytes = self.path.read_bytes()
        self.options = options
        return (SimpleNamespace(text=text) for text in self.texts), SimpleNamespace(language='en')


class LocalASRTests(unittest.TestCase):
    def test_injected_model_returns_unmodified_transcript_and_source_evidence(self):
        raw = wav_bytes()
        model = FakeModel(('  keep ', 'every byte.\n'))
        result = LocalASR(model).transcribe(raw, 'audio/wav')

        self.assertEqual(result['transcript'], '  keep every byte.\n')
        self.assertEqual(model.seen_bytes, raw)
        self.assertEqual(model.options['task'], 'transcribe')
        self.assertFalse(model.options['condition_on_previous_text'])
        self.assertEqual(result['evidence'], {
            'model': local_asr.MODEL_ID,
            'revision': local_asr.MODEL_REVISION,
            'sha256': hashlib.sha256(raw).hexdigest(),
            'bytes': len(raw),
            'mime_type': 'audio/wav',
            'language': 'en',
        })
        self.assertFalse(model.path.exists())

    def test_explicit_path_is_snapshotted_and_extension_must_match_mime(self):
        raw = wav_bytes()
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'clip.wav'
            path.write_bytes(raw)
            model = FakeModel(('spoken words',))
            result = LocalASR(model).transcribe(path, 'audio/wav')
            self.assertEqual(model.seen_bytes, raw)
            self.assertEqual(result['evidence']['sha256'], hashlib.sha256(raw).hexdigest())
            with self.assertRaises(ASRInputError):
                LocalASR(FakeModel()).transcribe(path, 'audio/mpeg')

    def test_model_load_is_lazy_cached_and_offline_pinned(self):
        model = FakeModel()
        with patch('participant.local_asr._load_model', return_value=model) as load:
            adapter = LocalASR()
            load.assert_not_called()
            adapter.transcribe(wav_bytes(), 'audio/wav')
            adapter.transcribe(wav_bytes(), 'audio/wav')
            load.assert_called_once_with()

        calls = []
        def whisper_model(*args, **kwargs):
            calls.append((args, kwargs))
            return model
        with patch.dict(sys.modules, {'faster_whisper': types.SimpleNamespace(WhisperModel=whisper_model)}):
            self.assertIs(local_asr._load_model(), model)
        args, kwargs = calls[0]
        self.assertEqual(args, (local_asr.MODEL_ID,))
        self.assertEqual(kwargs['revision'], local_asr.MODEL_REVISION)
        self.assertTrue(kwargs['local_files_only'])
        self.assertEqual(kwargs['device'], 'cpu')

    def test_empty_audio_transcript_and_missing_model_have_typed_sanitized_errors(self):
        model = FakeModel()
        with self.assertRaises(ASREmptyAudioError):
            LocalASR(model).transcribe(b'', 'audio/wav')
        self.assertIsNone(model.seen_bytes)

        with self.assertRaises(ASREmptyTranscriptError):
            LocalASR(FakeModel(())).transcribe(wav_bytes(), 'audio/wav')

        with patch('participant.local_asr._load_model', side_effect=RuntimeError('secret / raw audio')):
            with self.assertRaises(ASRUnavailableError) as error:
                LocalASR().transcribe(wav_bytes(), 'audio/wav')
        self.assertNotIn('secret', str(error.exception))
        self.assertNotIn('raw audio', str(error.exception))

    def test_timeout_is_typed_and_prevents_a_second_inflight_call(self):
        started, release, completed = threading.Event(), threading.Event(), threading.Event()
        class SlowModel(FakeModel):
            def transcribe(self, path, **options):
                self.path = Path(path)
                self.seen_bytes = self.path.read_bytes()
                started.set()
                release.wait()
                completed.set()
                return iter((SimpleNamespace(text='late'),)), SimpleNamespace(language='en')

        adapter = LocalASR(SlowModel())
        try:
            with self.assertRaises(ASRTimeoutError):
                adapter.transcribe(wav_bytes(), 'audio/wav', timeout=0.01)
            self.assertTrue(started.wait(1))
            with self.assertRaises(ASRUnavailableError):
                adapter.transcribe(wav_bytes(), 'audio/wav')
        finally:
            release.set()
        self.assertTrue(completed.wait(1))

    def test_unsupported_mime_and_timeout_values_fail_before_model_use(self):
        model = FakeModel()
        adapter = LocalASR(model)
        with self.assertRaises(ASRInputError):
            adapter.transcribe(wav_bytes(), 'application/octet-stream')
        with self.assertRaises(ASRTimeoutError):
            adapter.transcribe(wav_bytes(), 'audio/wav', timeout=0)
        self.assertIsNone(model.seen_bytes)


if __name__ == '__main__':
    unittest.main()
