import asyncio
import base64
import hashlib
import io
import os
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import httpx
from PIL import Image

from participant.media import MediaError, MediaLoader
from participant.planner import Planner, PlannerError


MP3_FIXTURES = Path(__file__).parent / 'fixtures' / 'mp3'
MP3_BYTES = (MP3_FIXTURES / 'tone-cbr.mp3').read_bytes()
OTHER_MP3_BYTES = (MP3_FIXTURES / 'tone-vbr.mp3').read_bytes()
THIRD_MP3_BYTES = (MP3_FIXTURES / 'tone-mpeg25.mp3').read_bytes()
MPEG48_FRAME = (MP3_FIXTURES / 'tone-48k.mp3').read_bytes()[:96]
MPEG_FRAMES = MP3_BYTES[10 + sum(value * 128 ** (3 - i) for i, value in enumerate(MP3_BYTES[6:10])):]


def id3_tag(version, body=b'', flags=0):
    size = bytes((len(body) >> shift) & 127 for shift in (21, 14, 7, 0))
    header = b'ID3' + bytes((version, 0, flags)) + size
    return header + body + (b'3DI' + header[3:] if version == 4 and flags & 0x10 else b'')


class MediaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.loader = MediaLoader(self.root)

    async def test_exact_bytes_order_and_latest_frame_without_reference_text(self):
        first, second = MP3_BYTES, OTHER_MP3_BYTES
        (self.root / 'first.mp3').write_bytes(first)
        (self.root / 'second.mp3').write_bytes(second)
        Image.new('RGB', (5, 5), 'red').save(self.root / 'current.png')
        messages = [
            {'event_type': 'video_frame', 'payload': {'image_ref': 'missing-old.png'}},
            {'message_index': 8, 'event_type': 'user_audio_chunk', 'payload': {'audio_ref': 'first.mp3', '_reference_text': 'do not transmit', 'duration_ms': 1, 'end_of_turn': False}},
            {'message_index': 9, 'event_type': 'user_audio_chunk', 'payload': {'audio_ref': 'second.mp3', 'end_of_turn': True}},
            {'message_index': 10, 'event_type': 'video_frame', 'payload': {'image_ref': 'current.png', '_reference_image': 'do not transmit'}},
        ]
        clean, parts, evidence = await self.loader.prepare(messages)
        self.assertEqual([m['message_index'] for m in clean], [8, 9, 10])
        encoded = [p['inlineData'] for p in parts if 'inlineData' in p]
        self.assertEqual(base64.b64decode(encoded[0]['data']), first)
        self.assertEqual(base64.b64decode(encoded[1]['data']), second)
        self.assertEqual(evidence[0]['sha256'], hashlib.sha256(first).hexdigest())
        self.assertEqual(evidence[2]['mime_type'], 'image/png')
        self.assertNotIn('reference', repr(clean))
        self.assertNotIn('first.mp3', repr(clean) + repr(parts))

    async def test_opt_in_audio_bytes_match_message_and_sha256_provenance(self):
        first, second = MP3_BYTES, OTHER_MP3_BYTES
        (self.root / 'first.mp3').write_bytes(first)
        (self.root / 'second.mp3').write_bytes(second)
        messages = [
            {'message_index': 21, 'event_type': 'user_audio_chunk', 'payload': {'audio_ref': 'first.mp3'}},
            {'message_index': 22, 'event_type': 'user_audio_chunk', 'payload': {'audio_ref': 'second.mp3'}},
        ]

        default_result = await self.loader.prepare(messages)
        self.assertEqual(len(default_result), 3)
        clean, parts, evidence, audio = await self.loader.prepare(messages, include_audio_bytes=True)

        self.assertEqual((clean, parts, evidence), default_result)
        self.assertEqual([item['message_index'] for item in audio], [21, 22])
        self.assertEqual([item['audio_bytes'] for item in audio], [first, second])
        self.assertEqual([item['sha256'] for item in audio], [item['sha256'] for item in evidence])
        self.assertEqual([item['sha256'] for item in audio],
                         [hashlib.sha256(raw).hexdigest() for raw in (first, second)])
        self.assertTrue(all('audio_bytes' not in item for item in evidence))

    async def test_reject_missing_corrupt_nonmedia_and_escape(self):
        (self.root / 'bad.png').write_bytes(b'not an image')
        (self.root / 'bad.mp3').write_bytes(b'not audio')
        (self.root / 'scenario.json').write_text('{"ground_truth":42}')
        for path, kind in [('missing.mp3', 'audio'), ('bad.png', 'image'), ('bad.mp3', 'audio'),
                           ('scenario.json', 'audio'), ('../answer.mp3', 'audio'),
                           ('https://example.test/a.mp3', 'audio'), ('//host/share/a.mp3', 'audio')]:
            with self.subTest(path=path), self.assertRaises(MediaError):
                await asyncio.to_thread(self.loader._read, path, kind)

    async def test_root_is_explicit_and_absolute_paths_confined(self):
        (self.root / 'audio').mkdir()
        path = self.root / 'audio' / 'clip.mp3'
        path.write_bytes(MP3_BYTES)
        self.assertEqual(self.loader._read('audio\\clip.mp3', 'audio')[0], MP3_BYTES)
        self.assertEqual(self.loader._read(str(path), 'audio')[0], MP3_BYTES)
        with self.assertRaises(MediaError):
            self.loader._read(str(self.root.parent / 'outside.mp3'), 'audio')

    async def test_oversize_is_rejected_before_read(self):
        (self.root / 'clip.mp3').write_bytes(MP3_BYTES)
        self.loader.MAX_BYTES = 20
        with self.assertRaises(MediaError):
            self.loader._read('clip.mp3', 'audio')

    async def test_real_cbr_vbr_mpeg_versions_and_id3_variants_keep_exact_bytes(self):
        title2 = b'TT2\x00\x00\x02\x00x'
        title3 = b'TIT2\x00\x00\x00\x02\x00\x00\x00x'
        ext3 = b'\x00\x00\x00\x06\x00\x00\x00\x00\x00\x00'
        ext4 = b'\x00\x00\x00\x06\x01\x00'
        unsynchronised = b'PRIV\x00\x00\x00\x03\x00\x00x\xff\x00\xe0'
        for name, raw in {
            'cbr_id3v23': MP3_BYTES, 'vbr_id3v24_xing': OTHER_MP3_BYTES,
            'mpeg25_untagged': THIRD_MP3_BYTES, 'mpeg1_untagged': MPEG_FRAMES,
            'id3v22': id3_tag(2, title2) + MPEG_FRAMES,
            'id3v23_extended': id3_tag(3, ext3 + title3, 0x40) + MPEG_FRAMES,
            'id3v23_unsynchronised': id3_tag(3, unsynchronised, 0x80) + MPEG_FRAMES,
            'id3v24_extended': id3_tag(4, ext4 + title3, 0x40) + MPEG_FRAMES,
            'id3v24_footer': id3_tag(4, title3, 0x10) + MPEG_FRAMES,
            'id3v24_appended': MPEG_FRAMES + id3_tag(4, title3, 0x10),
            'id3v23_padding': id3_tag(3, title3 + bytes(31)) + MPEG_FRAMES,
            'id3v1': MPEG_FRAMES + b'TAG' + bytes(125),
        }.items():
            with self.subTest(name=name):
                (self.root / 'clip.mp3').write_bytes(raw)
                self.assertEqual(self.loader._read('clip.mp3', 'audio'), (raw, 'audio/mpeg'))

    async def test_malformed_id3_and_mpeg_are_rejected_without_resynchronising(self):
        for name, raw in self.invalid_mp3s().items():
            with self.subTest(name=name):
                (self.root / 'clip.mp3').write_bytes(raw)
                with self.assertRaises(MediaError):
                    self.loader._read('clip.mp3', 'audio')

    async def test_mp3_duration_is_bounded_by_frames_instead_of_advisory_hint(self):
        # Genuine encoded frames: 48 kHz / 1152 samples, 8 kHz / 576 samples.
        for frame, allowed in [(MPEG48_FRAME, 5000), (THIRD_MP3_BYTES[:72], 1666)]:
            with self.subTest(sample_frame_bytes=len(frame)):
                raw = frame * allowed
                (self.root / 'clip.mp3').write_bytes(raw)
                self.assertEqual(self.loader._read('clip.mp3', 'audio'), (raw, 'audio/mpeg'))
                (self.root / 'clip.mp3').write_bytes(raw + frame)
                with self.assertRaisesRegex(MediaError, 'length'):
                    await self.loader.prepare([{'event_type': 'user_audio_chunk',
                        'payload': {'audio_ref': 'clip.mp3', 'duration_ms': 1}}])

    @staticmethod
    def invalid_mp3s():
        header = int.from_bytes(MPEG_FRAMES[:4], 'big')
        invalid_header = lambda mask, value: ((header & ~mask) | value).to_bytes(4, 'big') + MPEG_FRAMES[4:]
        return {
            'frozen_six_byte_id3': bytes.fromhex('494433000000'),
            'fake_id3': b'ID3mock audio', 'tag_without_audio': id3_tag(3, bytes(20)),
            'tag_size_exceeds_file': b'ID3\x03\x00\x00\x00\x00\x7f\x7f' + MPEG_FRAMES,
            'tag_size_not_synchsafe': b'ID3\x03\x00\x00\x80\x00\x00\x00' + MPEG_FRAMES,
            'tag_version_reserved': b'ID3\xff\x00\x00\x00\x00\x00\x00' + MPEG_FRAMES,
            'tag_flags_reserved': id3_tag(3, flags=1) + MPEG_FRAMES,
            'tag_frame_truncated': id3_tag(3, b'TIT2\x00\x00\x00\x10\x00\x00x') + MPEG_FRAMES,
            'tag_extended_truncated': id3_tag(3, bytes(4), 0x40) + MPEG_FRAMES,
            'tag_padding_nonzero': id3_tag(3, b'\x00x') + MPEG_FRAMES,
            'footer_missing': id3_tag(4, flags=0x10)[:-10] + MPEG_FRAMES,
            'footer_mismatch': id3_tag(4, flags=0x10)[:-1] + b'\x01' + MPEG_FRAMES,
            'mpeg_header_only': MPEG_FRAMES[:4], 'mpeg_short_frame': MPEG_FRAMES[:20],
            'mpeg_truncated_last_frame': MPEG_FRAMES[:-1],
            'mpeg_partial_next_header': MPEG_FRAMES + MPEG_FRAMES[:3],
            'mpeg_trailing_garbage': MPEG_FRAMES + b'garbage',
            'mpeg_leading_garbage': b'garbage' + MPEG_FRAMES,
            'mpeg_reserved_version': invalid_header(3 << 19, 1 << 19),
            'mpeg_reserved_layer': invalid_header(3 << 17, 0),
            'mpeg_reserved_bitrate': invalid_header(15 << 12, 15 << 12),
            'mpeg_free_format_unsupported': invalid_header(15 << 12, 0),
            'mpeg_reserved_rate': invalid_header(3 << 10, 3 << 10),
            'mpeg_over_120_seconds': MPEG48_FRAME * 5001,
        }

    async def test_invalid_mp3_is_rejected_before_any_planner_http_request(self):
        attempts = []
        def forbidden(request):
            attempts.append(request.method)
            self.fail('Invalid media must fail before main, acoustic, or other HTTP work.')
        with patch.dict(os.environ, {'SECRET_GEMINI_API_KEY': 'synthetic-test-key',
                        'PARTICIPANT_MEDIA_ROOT': str(self.root), 'PARTICIPANT_PREWARM': '0'}, clear=True):
            planner = Planner(transport=httpx.MockTransport(forbidden))
            await planner.setup()
            try:
                for name, raw in self.invalid_mp3s().items():
                    with self.subTest(name=name):
                        (self.root / 'clip.mp3').write_bytes(raw)
                        with self.assertRaises(PlannerError):
                            await planner.plan({'messages': [{'event_type': 'user_audio_chunk',
                                                'payload': {'audio_ref': 'clip.mp3'}}]})
                        self.assertEqual(planner.evidence[-1]['status'], 'media_error')
                        self.assertFalse(planner._audio_cache)
            finally:
                await planner.close()
            self.assertFalse(attempts)
            self.assertFalse(planner._pending_tasks)

    async def test_pcm_wav_and_supported_images_still_validate(self):
        encoded = io.BytesIO()
        with wave.open(encoded, 'wb') as audio:
            audio.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            audio.writeframes(bytes(320))
        raw = encoded.getvalue()
        (self.root / 'clip.wav').write_bytes(raw)
        self.assertEqual(self.loader._read('clip.wav', 'audio'), (raw, 'audio/wav'))
        (self.root / 'clip.wav').write_bytes(raw[:-1])
        with self.assertRaises(MediaError):
            self.loader._read('clip.wav', 'audio')
        for suffix, mime in [('png', 'image/png'), ('jpg', 'image/jpeg'), ('webp', 'image/webp')]:
            path = self.root / ('image.' + suffix)
            Image.new('RGB', (4, 4), 'blue').save(path)
            self.assertEqual(self.loader._read(path.name, 'image'), (path.read_bytes(), mime))


if __name__ == '__main__':
    unittest.main()
