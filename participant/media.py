"""Read only referenced media beneath an explicit root; never discover fixtures."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
from pathlib import Path
import wave

from PIL import Image, UnidentifiedImageError


_MAX_AUDIO_SECONDS = 120


class MediaError(ValueError):
    """A supplied media reference cannot provide trustworthy input."""


def _synchsafe(raw: bytes) -> int:
    if len(raw) != 4 or any(value & 0x80 for value in raw):
        raise MediaError('The MP3 contains an invalid ID3 size.')
    return sum(value << shift for value, shift in zip(raw, (21, 14, 7, 0)))


def _id3_end(raw: bytes, start: int, limit: int) -> int:
    """Validate an ID3v2 envelope and its frame boundaries, without decoding tags."""
    header = raw[start:start + 10]
    if len(header) != 10 or start + 10 > limit:
        raise MediaError('The MP3 ID3 header is truncated.')
    version, revision, flags = header[3:6]
    allowed = {2: 0xc0, 3: 0xe0, 4: 0xf0}
    if version not in allowed or revision == 255 or flags & ~allowed[version]:
        raise MediaError('The MP3 ID3 version or flags are unsupported.')
    if version == 2 and flags & 0x40:
        raise MediaError('Compressed ID3v2.2 tags are unsupported.')
    end = start + 10 + _synchsafe(header[6:10])
    footer = version == 4 and bool(flags & 0x10)
    if end + (10 if footer else 0) > limit:
        raise MediaError('The MP3 ID3 tag is truncated.')
    if footer and raw[end:end + 10] != b'3DI' + header[3:]:
        raise MediaError('The MP3 ID3 footer does not match its header.')
    body = raw[start + 10:end]
    # v2.2/2.3 unsynchronise the whole tag; v2.4 frame sizes include their
    # encoded data, so their boundaries must be read before unsynchronisation.
    if version < 4 and flags & 0x80:
        body = body.replace(b'\xff\x00', b'\xff')
    cursor = 0
    if version >= 3 and flags & 0x40:
        if len(body) < 6:
            raise MediaError('The MP3 ID3 extended header is truncated.')
        if version == 3:
            size = int.from_bytes(body[:4], 'big')
            ext_flags = int.from_bytes(body[4:6], 'big')
            if ext_flags & ~0x8000 or size != (10 if ext_flags else 6):
                raise MediaError('The MP3 ID3 extended header is invalid.')
            cursor = size + 4
        else:
            cursor = _synchsafe(body[:4])
            if cursor < 6 or body[4] != 1 or body[5] & ~0x70:
                raise MediaError('The MP3 ID3 extended header is invalid.')
            field = 6
            for flag, size in ((0x40, 0), (0x20, 5), (0x10, 1)):
                if body[5] & flag:
                    if field >= len(body) or body[field] != size:
                        raise MediaError('The MP3 ID3 extended field is invalid.')
                    field += 1 + size
            if field != cursor:
                raise MediaError('The MP3 ID3 extended size is invalid.')
        if cursor > len(body):
            raise MediaError('The MP3 ID3 extended header is truncated.')
    while cursor < len(body):
        if body[cursor] == 0:
            if footer or any(body[cursor:]):
                raise MediaError('The MP3 ID3 padding is invalid.')
            break
        width, header_size = (3, 6) if version == 2 else (4, 10)
        if cursor + header_size > len(body):
            raise MediaError('The MP3 ID3 frame header is truncated.')
        frame_id = body[cursor:cursor + width]
        if any(not (65 <= value <= 90 or 48 <= value <= 57) for value in frame_id):
            raise MediaError('The MP3 ID3 frame identifier is invalid.')
        size_bytes = body[cursor + width:cursor + width * 2]
        size = _synchsafe(size_bytes) if version == 4 else int.from_bytes(size_bytes, 'big')
        if version >= 3:
            status, encoding = body[cursor + 8:cursor + 10]
            if (version == 3 and (status & ~0xe0 or encoding & ~0xe0)
                    or version == 4 and (status & ~0x70 or encoding & ~0x4f)):
                raise MediaError('The MP3 ID3 frame flags are invalid.')
        cursor += header_size + size
        if not size or cursor > len(body):
            raise MediaError('The MP3 ID3 frame is empty or truncated.')
    return end + (10 if footer else 0)


def _validate_mp3(raw: bytes) -> None:
    """Bounded structural validation; encoded audio is neither repaired nor transcoded.

    Every byte must belong to complete ID3 tags or contiguous MPEG Layer III
    frames. This is not a Huffman decoder or an assertion about audible speech.
    Free-format MPEG and non-ID3 trailers are explicitly unsupported.
    """
    end = len(raw) - 128 if len(raw) >= 128 and raw[-128:-125] == b'TAG' else len(raw)
    cursor = frames = samples = 0
    stream = None
    while cursor < end and raw[cursor:cursor + 3] == b'ID3':
        cursor = _id3_end(raw, cursor, end)
    while cursor < end and raw[cursor:cursor + 3] != b'ID3':
        if cursor + 4 > end:
            raise MediaError('The MPEG audio frame header is truncated.')
        header = int.from_bytes(raw[cursor:cursor + 4], 'big')
        version, layer = (header >> 19) & 3, (header >> 17) & 3
        bitrate_index, rate_index = (header >> 12) & 15, (header >> 10) & 3
        if (header & 0xffe00000 != 0xffe00000 or version == 1 or layer != 1
                or not 1 <= bitrate_index <= 14 or rate_index == 3 or header & 3 == 2):
            raise MediaError('The file contains an invalid or unsupported MPEG audio header.')
        rates = (32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320) if version == 3 else (
            8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)
        sample_rate = (44100, 48000, 32000)[rate_index] >> (0 if version == 3 else 1 if version == 2 else 2)
        identity = version, sample_rate
        if stream is not None and identity != stream:
            raise MediaError('The MPEG audio stream changes its version or sample rate.')
        stream = identity
        size = (144000 if version == 3 else 72000) * rates[bitrate_index - 1] // sample_rate + ((header >> 9) & 1)
        mono = (header >> 6) & 3 == 3
        side_size = (17 if mono else 32) if version == 3 else (9 if mono else 17)
        prefix = 4 + (0 if header & 0x10000 else 2) + side_size
        if size <= prefix or cursor + size > end:
            raise MediaError('The MPEG audio frame is truncated.')
        samples += 1152 if version == 3 else 576
        if samples > _MAX_AUDIO_SECONDS * sample_rate:
            raise MediaError('The audio length is not supported.')
        cursor += size
        frames += 1
    while cursor < end and raw[cursor:cursor + 3] == b'ID3':
        cursor = _id3_end(raw, cursor, end)
    if not frames or cursor != end:
        raise MediaError('The MP3 has no complete audio frames or contains trailing invalid data.')


class MediaLoader:
    MAX_BYTES = 8_000_000
    MAX_TOTAL_BYTES = 12_000_000
    MIME_TYPES = {'.mp3': 'audio/mpeg', '.wav': 'audio/wav',
                  '.png': 'image/png', '.jpg': 'image/jpeg',
                  '.jpeg': 'image/jpeg', '.webp': 'image/webp'}

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def _read(self, reference: str, kind: str) -> tuple[bytes, str]:
        if not isinstance(reference, str) or not reference or '\x00' in reference:
            raise MediaError('The media reference is missing or invalid.')
        # Backslash is also a separator in kit references copied from Windows.
        reference = reference.replace('\\', '/')
        if '://' in reference or reference.startswith('//'):
            raise MediaError('Media references must be local files beneath the media root.')
        path = (self.root / reference).resolve()
        if not path.is_relative_to(self.root):
            raise MediaError('The media reference is outside the configured media root.')
        mime = self.MIME_TYPES.get(path.suffix.lower(), '')
        if not mime.startswith(kind + '/'):
            raise MediaError('The reference does not name a supported media file.')
        try:
            if not path.is_file() or path.stat().st_size > self.MAX_BYTES:
                raise MediaError('The media file is missing or too large.')
            with path.open('rb') as source:
                raw = source.read(self.MAX_BYTES + 1)
        except (OSError, ValueError):
            raise MediaError('The media file could not be read.') from None
        if not raw or len(raw) > self.MAX_BYTES:
            raise MediaError('The media file is empty or too large.')
        try:
            if kind == 'image':
                with Image.open(io.BytesIO(raw)) as image:
                    if image.width * image.height > 12_000_000:
                        raise MediaError('The image exceeds the supported pixel limit.')
                    if Image.MIME.get(image.format) != mime:
                        raise MediaError('The image format does not match its reference.')
                    image.verify()
            elif mime == 'audio/wav':
                with wave.open(io.BytesIO(raw), 'rb') as audio:
                    if not 0 < audio.getnframes() / audio.getframerate() <= _MAX_AUDIO_SECONDS:
                        raise MediaError('The audio length is not supported.')
                    frames = audio.readframes(audio.getnframes())
                    if len(frames) != audio.getnframes() * audio.getnchannels() * audio.getsampwidth():
                        raise MediaError('The audio file is truncated.')
            else:
                _validate_mp3(raw)
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError, EOFError, wave.Error, ZeroDivisionError):
            raise MediaError('The media file is corrupt or unsupported.') from None
        return raw, mime

    async def prepare(self, messages: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
        """Return clean messages, labeled inline media parts, and redacted provenance.

        All audio chunks retain their order. Only the latest image is attached.
        Paths never enter the model's textual context; they are transport only.
        """
        latest_frame = next((i for i in range(len(messages) - 1, -1, -1)
                             if messages[i].get('event_type') == 'video_frame'), None)
        clean, parts, evidence = [], [], []
        total = 0
        for index, message in enumerate(messages):
            kind = message.get('event_type')
            if kind not in ('user_speech_chunk', 'user_audio_chunk', 'interruption', 'video_frame'):
                continue
            if kind == 'video_frame' and index != latest_frame:
                continue
            payload = message.get('payload', {})
            message_index = message.get('message_index', index)
            if type(message_index) is not int or message_index < 0 or not isinstance(payload, dict):
                raise MediaError('The media event metadata is invalid.')
            entry = {'message_index': message_index, 'event_type': kind,
                     'payload': {k: payload[k] for k in ('text', 'end_of_turn', 'frame_id', 'device_hint') if k in payload}}
            if 'revision' in message:
                entry['revision'] = message['revision']
            clean.append(entry)
            if kind not in ('user_audio_chunk', 'video_frame'):
                continue
            media_kind = 'audio' if kind == 'user_audio_chunk' else 'image'
            ref_key = 'audio_ref' if media_kind == 'audio' else 'image_ref'
            try:
                raw, mime = await asyncio.to_thread(self._read, payload.get(ref_key), media_kind)
            except MediaError:
                if media_kind != 'image':
                    raise
                entry['payload']['image_unavailable'] = True
                continue
            total += len(raw)
            if total > self.MAX_TOTAL_BYTES:
                raise MediaError('The combined media exceeds the supported request size.')
            parts.extend([{'text': f'Current {media_kind} evidence for message_index={message_index}; ordered as in messages:'},
                          {'inlineData': {'mimeType': mime, 'data': base64.b64encode(raw).decode('ascii')}}])
            evidence.append({'message_index': message_index, 'sha256': hashlib.sha256(raw).hexdigest(),
                             'bytes': len(raw), 'mime_type': mime})
        return clean, parts, evidence
