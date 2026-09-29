# Genuine MP3 unit fixtures

These are synthetic sine tones generated for the tests, not speech or acceptance
answers. Tests read the committed encoded bytes and require no audio encoder,
decoder, network, or model. The four files total 4,135 bytes.

Generated with FFmpeg 8.1.1 and its libmp3lame encoder, one encoding thread:

```text
ffmpeg -hide_banner -loglevel error -nostdin -f lavfi -i sine=frequency=440:sample_rate=44100:duration=0.12 -ac 1 -codec:a libmp3lame -b:a 96k -threads 1 -filter_threads 1 -id3v2_version 3 -write_xing 0 -metadata "title=Synthetic 440 Hz test tone" -y tone-cbr.mp3
ffmpeg -hide_banner -loglevel error -nostdin -f lavfi -i sine=frequency=880:sample_rate=22050:duration=0.18 -ac 2 -codec:a libmp3lame -q:a 4 -threads 1 -filter_threads 1 -id3v2_version 4 -metadata "title=Synthetic 880 Hz test tone" -y tone-vbr.mp3
ffmpeg -hide_banner -loglevel error -nostdin -f lavfi -i sine=frequency=220:sample_rate=8000:duration=0.18 -ac 1 -codec:a libmp3lame -b:a 8k -threads 1 -filter_threads 1 -id3v2_version 0 -write_xing 0 -y tone-mpeg25.mp3
ffmpeg -hide_banner -loglevel error -nostdin -f lavfi -i sine=frequency=440:sample_rate=48000:duration=0.024 -ac 1 -codec:a libmp3lame -b:a 32k -threads 1 -filter_threads 1 -id3v2_version 0 -write_xing 0 -y tone-48k.mp3
```

| File | Encoding | SHA256 |
| --- | --- | --- |
| tone-cbr.mp3 | MPEG-1 Layer III, mono, 44.1 kHz, 96 kbps, ID3v2.3 | f88e7c08c16cfd0fafcb865710dc3db8094157c069dd6560ea18383648f3506b |
| tone-vbr.mp3 | MPEG-2 Layer III, stereo, 22.05 kHz, VBR, ID3v2.4 and Xing | d8592a021df038c7028fefad2e15dcf244590355096b9b51f74ab9bae078de6e |
| tone-mpeg25.mp3 | MPEG-2.5 Layer III, mono, 8 kHz, 8 kbps, no ID3 tag | 8958ce2ab42e885035186f6d557cf89be0592d7d36153659393d3d294e7c33d2 |
| tone-48k.mp3 | MPEG-1 Layer III, mono, 48 kHz, 32 kbps, no ID3 tag | 11d31bf150c7a8d7104facb92197b83ada410d7a89c640c66729c99d3336e198 |

All files were independently decoded with the existing development PyAV 18.1.0:
6 / 8 / 5 / 2 decoded frames respectively for CBR / VBR / MPEG-2.5 / 48 kHz. PyAV and FFmpeg
are development checks only and are not participant runtime dependencies.

The duration boundary tests repeat the genuine first 96-byte frame of the 48 kHz
fixture and the first 72-byte frame of the MPEG-2.5 fixture. At 48 kHz, 5,000
frames of 1,152 samples give exactly 120 seconds; one more gives 120.024 seconds.
At 8 kHz, 1,666 frames of 576 samples give 119.952 seconds; one more gives
120.024 seconds. The accepted repeated streams were independently decoded as
development controls. The runtime ceiling counts encoded frames, including
encoder priming/padding, and does not use an advisory duration hint.
