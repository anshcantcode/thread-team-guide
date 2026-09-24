"""Optional, offline-only faster-whisper adapter for validated audio."""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from hashlib import sha256
import math
import os
from pathlib import Path
import tempfile
from threading import Lock


MODEL_ID = 'dropbox-dash/faster-whisper-large-v3-turbo'
MODEL_REVISION = '0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf'
MAX_AUDIO_BYTES = 8_000_000
_MIME_SUFFIX = {'audio/mpeg': '.mp3', 'audio/wav': '.wav'}


class LocalASRError(RuntimeError):
    """Sanitized local recognition failure."""


class ASRInputError(LocalASRError):
    """The supplied audio source or MIME type is unsupported."""


class ASREmptyAudioError(ASRInputError):
    """The supplied audio source has no bytes."""


class ASREmptyTranscriptError(LocalASRError):
    """Recognition completed without any transcript text."""


class ASRUnavailableError(LocalASRError):
    """The optional package, pinned model, or inference runtime is unavailable."""


class ASRTimeoutError(LocalASRError):
    """Recognition did not finish before its deadline."""


def _load_model():
    """Load only the pinned cached model; never fetch model files at runtime."""
    from faster_whisper import WhisperModel

    return WhisperModel(
        MODEL_ID, device='cpu', compute_type='int8',
        local_files_only=True, revision=MODEL_REVISION,
    )


class LocalASR:
    """Transcribe caller-validated WAV/MP3 audio without network access.

    ``audio`` may be validated bytes or an explicit file path. Bytes and paths
    are snapshotted to a private temporary file, so the recorded digest names
    exactly the data passed to faster-whisper. A model can be injected for tests.
    """

    def __init__(self, model=None):
        self._model = model
        self._state_lock = Lock()
        self._future: Future | None = None

    def transcribe(self, audio: bytes | bytearray | memoryview | str | os.PathLike,
                   mime_type: str, *, timeout: float = 60.0) -> dict:
        """Return verbatim text and source/model evidence, or a typed failure."""
        mime_type = mime_type.strip().lower() if isinstance(mime_type, str) else ''
        if mime_type not in _MIME_SUFFIX:
            raise ASRInputError('The audio MIME type is unsupported.')
        if not isinstance(audio, (bytes, bytearray, memoryview, str, os.PathLike)):
            raise ASRInputError('Audio must be validated bytes or an explicit path.')
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ASRTimeoutError('Local recognition timed out.')
        if isinstance(audio, (bytes, bytearray, memoryview)):
            if not audio:
                raise ASREmptyAudioError('The audio input is empty.')
            if len(audio) > MAX_AUDIO_BYTES:
                raise ASRInputError('The audio input is too large.')
            source = bytes(audio)
        else:
            try:
                source = os.fspath(audio)
            except TypeError:
                raise ASRInputError('The explicit audio path is invalid.') from None
            if not isinstance(source, str):
                raise ASRInputError('The explicit audio path is invalid.')

        with self._state_lock:
            if self._future is not None:
                if not self._future.done():
                    raise ASRUnavailableError('Local recognition is still processing another clip.')
                self._future = None
            executor = None
            try:
                executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='participant-local-asr')
                future = executor.submit(self._transcribe, source, mime_type)
            except Exception:
                if executor is not None:
                    executor.shutdown(wait=False, cancel_futures=True)
                raise ASRUnavailableError('Local recognition could not start.') from None
            self._future = future
        future.add_done_callback(lambda done: self._release(done, executor))

        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            future.cancel()
            raise ASRTimeoutError('Local recognition timed out.') from None
        except LocalASRError:
            raise
        except Exception:
            raise ASRUnavailableError('Local recognition could not complete.') from None

    def _release(self, future: Future, executor: ThreadPoolExecutor) -> None:
        with self._state_lock:
            if self._future is future:
                self._future = None
        executor.shutdown(wait=False, cancel_futures=True)

    def _get_model(self):
        if self._model is None:
            try:
                self._model = _load_model()
            except Exception:
                raise ASRUnavailableError('The pinned local speech model is unavailable.') from None
        return self._model

    def _transcribe(self, source: bytes | str, mime_type: str) -> dict:
        raw = self._read(source, mime_type)
        if not raw:
            raise ASREmptyAudioError('The audio input is empty.')
        if len(raw) > MAX_AUDIO_BYTES:
            raise ASRInputError('The audio input is too large.')

        digest = sha256(raw).hexdigest()
        path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=_MIME_SUFFIX[mime_type], delete=False) as stream:
                path = stream.name
                stream.write(raw)
            segments, info = self._get_model().transcribe(
                path, task='transcribe', language='en', beam_size=5, temperature=0.0,
                word_timestamps=True,
                condition_on_previous_text=False,
            )
            transcript = ''.join(segment.text for segment in segments)
        except LocalASRError:
            raise
        except Exception:
            raise ASRUnavailableError('Local recognition could not process this audio.') from None
        finally:
            if path is not None:
                try:
                    Path(path).unlink()
                except OSError:
                    pass

        if not transcript.strip():
            raise ASREmptyTranscriptError('No transcript text was recognized.')
        return {
            'transcript': transcript,
            'evidence': {
                'model': MODEL_ID,
                'revision': MODEL_REVISION,
                'sha256': digest,
                'bytes': len(raw),
                'mime_type': mime_type,
                'language': getattr(info, 'language', None),
            },
        }

    @staticmethod
    def _read(source: bytes | str, mime_type: str) -> bytes:
        if isinstance(source, bytes):
            return source
        path = Path(source)
        if path.suffix.lower() != _MIME_SUFFIX[mime_type]:
            raise ASRInputError('The audio path extension does not match its MIME type.')
        try:
            with path.open('rb') as stream:
                raw = stream.read(MAX_AUDIO_BYTES + 1)
        except OSError:
            raise ASRInputError('The explicit audio path could not be read.') from None
        if len(raw) > MAX_AUDIO_BYTES:
            raise ASRInputError('The audio input is too large.')
        return raw
