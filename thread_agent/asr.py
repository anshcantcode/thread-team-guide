"""Isolated local perception worker. One PCM clip, no transcript cache or tools."""
import base64
import io
import json
from pathlib import Path
import sys


def transcribe(encoded):
    from faster_whisper import WhisperModel
    root = Path(__file__).resolve().parents[1]
    model = WhisperModel('base.en', device='cpu', compute_type='int8', cpu_threads=4,
                         download_root=str(root/'.runtime/whisper'), local_files_only=True)
    segments, _ = model.transcribe(io.BytesIO(base64.b64decode(encoded, validate=True)),
        language='en', beam_size=3, vad_filter=True, condition_on_previous_text=False)
    segments = list(segments)
    if not segments or all(s.avg_logprob < -1.2 for s in segments):
        return ''
    return ' '.join(s.text.strip() for s in segments).strip()


if __name__ == '__main__':
    try:
        raw = sys.stdin.buffer.read(8_000_001)
        if len(raw) > 8_000_000: raise ValueError('Clip too large')
        result = {'ok': True, 'transcript': transcribe(raw.decode('ascii'))}
    except Exception:
        result = {'ok': False, 'error': 'Local speech recognition is unavailable. Run the local setup or use text input.'}
    print(json.dumps(result), flush=True)
