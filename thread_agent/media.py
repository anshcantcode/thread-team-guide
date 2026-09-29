"""Shared WAV/image validation; independent of the HTTP application."""
import base64
import binascii
import io
import wave
from PIL import Image, UnidentifiedImageError


def validate_media(event):
    if event.type not in ('audio', 'frame'): return
    encoded = event.data.get('base64', '')
    if not isinstance(encoded, str) or len(encoded) > 8_000_000:
        raise ValueError('Media must be a base64 file smaller than 6 MB.')
    try: raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error): raise ValueError('Invalid base64 media.') from None
    if event.type == 'audio':
        if event.data.get('mime') not in ('audio/wav', 'audio/x-wav'):
            raise ValueError('Upload a WAV clip. The microphone records WAV automatically.')
        try:
            with wave.open(io.BytesIO(raw), 'rb') as wav:
                seconds = wav.getnframes() / wav.getframerate()
                if not 0.1 <= seconds <= 30 or wav.getsampwidth() != 2 or wav.getnchannels() > 2:
                    raise ValueError('Use a 0.1–30 second, 16-bit PCM WAV clip with one or two channels.')
                frames = wav.readframes(wav.getnframes())
                if len(frames) != wav.getnframes() * wav.getnchannels() * 2:
                    raise ValueError('The WAV payload is truncated; its header does not match the audio frames.')
        except (wave.Error, EOFError, ZeroDivisionError):
            raise ValueError('This is not a readable PCM WAV file.') from None
        event.data['mime'] = 'audio/wav'
    else:
        try:
            with Image.open(io.BytesIO(raw)) as im:
                if im.width * im.height > 12_000_000: raise ValueError('Image must be at most 12 megapixels.')
                if im.format not in ('PNG', 'JPEG', 'WEBP'): raise ValueError('Use a PNG, JPEG, or WebP image.')
                im = im.convert('RGB')
                im.thumbnail((1280, 1280))
                buffer = io.BytesIO()
                im.save(buffer, format='PNG')
                event.data['base64'] = base64.b64encode(buffer.getvalue()).decode()
                event.data['mime'] = 'image/png'
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise ValueError('The image could not be decoded safely.') from None


def digital_silence(data):
    """Only exact zero PCM is classified here; quiet/noisy speech goes to perception."""
    with wave.open(io.BytesIO(base64.b64decode(data['base64'], validate=True)), 'rb') as wav:
        frames = wav.readframes(wav.getnframes())
        return bool(frames) and not any(frames)
