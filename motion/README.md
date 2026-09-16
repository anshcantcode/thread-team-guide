# THREAD — Keep the thread.

**Superseded by [Version 2 — Keep going](v2/README.md).** The replacement is a
43-second feature-led edit in both formats. This directory retains the first
cut and its production history.

Two finished motion films built around THREAD's defining behavior: a correction
changes the task without losing the details. The wordmark, Manrope type, ink
background and acoustic blue sphere come from the existing product.

## Watch and use

- `output/THREAD-Keep-the-thread-landscape.mp4` — 58 seconds, 2560 × 1440,
  60 fps. Use this as the opening film in the hackathon presentation.
- `output/THREAD-Keep-the-thread-vertical.mp4` — 49 seconds, 1080 × 1920,
  60 fps. Reframed and recut for portrait; retains the full interruption example.
- Both use H.264, standard 4:2:0 video, BT.709 colour, AAC stereo at 48 kHz and
  320 kbps, plus optional embedded English captions. Sidecar SRT files are beside
  the MP4s for players and social editors that do not read embedded captions.
- `output/THREAD-soundtrack.wav` — landscape audio master, 48 kHz, stereo,
  24-bit PCM. The vertical master is also included.
- `audio/voice-stem.wav`, `audio/music-stem.wav`, `audio/effects-stem.wav` —
  separate 58-second stems for further editing. These are pre-master stems and
  will not null against the loudness-normalized master after simple summing.

Play the film with sound. In the presentation, let the final “Keep the thread”
resolve, then open the actual S24 demo and repeat the correction interaction.
The film introduces the benefit; the live demonstration supplies the proof.

## Editorial decisions

The landscape edit moves from optical macro photography into the brand sphere,
then an interrupted flight request. “Wait” arrests the motion and drops the
score. Mumbai replaces Delhi while Chennai, tomorrow and after 21:00 remain.
The second half moves through search, sports, a saved task and widgets, using
actual device screenshots on a rendered phone. The standalone Android shot
ends with the invitation “Go on. Keep the thread.”

The vertical edit removes the nine-second explanatory beat at source 25.6–34.6
because the preceding interaction already demonstrates it. It has distinct
type wrapping, phone size, camera position and sphere composition. Its captions
and soundtrack use the same cut and remain synchronized.

The conversation voices are directed synthetic performances from
`gemini-3.1-flash-tts-preview`, using Charon and Aoede. The request and interruption
were recorded in one continuous character performance and edited into the scene
to preserve a consistent voice. The original score is a
96 BPM electronic composition with detuned harmonic pads, sparse glass tones,
soft low-frequency pulses, stereo transitions and a three-note sonic signature.
No commercial music track or stock sound library is used. Speech is kept central;
stereo width belongs mainly to the score and effects. The interruption is an
intentional editorial effect. [Gemini speech-generation documentation](https://ai.google.dev/gemini-api/docs/speech-generation).

## Claims and provenance

This is an edited product film. The flight example is labeled **illustrated
interaction** and **demo flight data** on screen. It is not a real-time latency
measurement or a claim that live flight inventory was purchased or reserved.
The engine's demonstrated behavior is constraint retention and correction.

The screenshots are exact copies of these project evidence assets:

| Film asset | Original |
|---|---|
| `assets/screens/home.png` | `reports/android-embedded-current-screen.png` |
| `assets/screens/search.png` | `reports/android-smart-google-videos.png` |
| `assets/screens/sports.png` | `reports/android-profile-virat-kohli.png` |
| `assets/screens/correction.png` | `reports/android-smart-correction.png` |
| `assets/screens/widget.png` | `reports/android-widget-clocks-host.png` |

The device shell is a procedural visual, not footage of physical hardware.
The content inside it is actual Android UI. Third-party names, imagery and data
appear as part of that UI; the film claims no endorsement from those parties.

`assets/optical-macro.png` was generated with the built-in imagegen tool using
the existing sphere as its reference. The production prompt and creative brief
are in [BRIEF.md](BRIEF.md). The original `web/images/thread-sphere.png` is used
directly for the hero. `web/fonts/Manrope.ttf` is licensed under the accompanying
SIL Open Font License in `web/fonts/Manrope-OFL.txt`.

The on-phone backend exists in Android 0.6. Gemini voice and fresh information
still require internet. This appears on the Android shot. No offline AI,
Spotify playback, autonomous purchases, official-kit certification, Samsung
endorsement or prize outcome is claimed.

## Reproduce and edit

Production is isolated in this directory. It does not modify the app or server.
Requires Python 3.11+, Pillow, NumPy, SciPy, ModernGL, FFmpeg/FFprobe and an OpenGL
3.3 context. The render command uses the NVIDIA H.264 encoder available on this
machine. On another machine, replace `h264_nvenc` encoder options in `render.py`
with a supported encoder. Runtime versions are in `requirements.txt`.

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r motion\requirements.txt

# Completed voice takes are reused. New takes require the existing .env key.
# Requests are deliberately spaced to stay within this project's TTS quota.
.\.venv\Scripts\python.exe motion\voice.py

.\.venv\Scripts\python.exe motion\sound.py
.\.venv\Scripts\python.exe motion\render.py --stills
.\.venv\Scripts\python.exe motion\render.py --stills --vertical
.\.venv\Scripts\python.exe motion\render.py
.\.venv\Scripts\python.exe motion\render.py --vertical
.\.venv\Scripts\python.exe motion\finish.py
```

`finish.py` reuses an existing `output/THREAD-soundtrack.wav`. If changing the
audio, move the previous master to a versioned filename before running it so
the new premaster is analyzed and normalized. Rendering and mixing completed
takes need no network or API calls. The scripts never save the API key in any
asset or send it through command arguments.

`render.py` contains the edit and layout; `scene.frag` contains optical motion,
filaments and the procedural phone. `voice.py` contains the exact script and
performance directions. `sound.py` contains the original score and time-coded
voice edit. `audio/edit.json` records actual take durations and the one mild
tempo adjustment. `output/manifest.json` records the final exports and hashes.

## Verification

Visual review covered landscape and portrait keyframes, actual screenshot
contents, typography boundaries, phone framing and the opening dissolve.
Each deliverable is decoded in full by FFmpeg; the exporter checks dimensions,
frame rate, duration, audio channels and sample rate. Optional caption tracks
are included, and portrait cue times are shifted to match its shorter edit.

The landscape audio master measures **−16.17 LUFS integrated** and **−1.20 dBTP**
before AAC encoding, with a 5.6 LU loudness range. The final landscape AAC audio
measures **−16.18 LUFS / −1.14 dBTP**; portrait measures **−16.44 LUFS / −1.17 dBTP**.
These readings are saved in `output/verification.json`. A model-assisted
listening pass recovered the dialogue correctly and reported no audible
garbling, distortion or distracting music. That is an additional model check,
not a claim of human studio listening.

An initial comparison found the separately generated user lines inconsistent.
Both were replaced by cuts from `audio/character_session.wav`; the final listening
check found the character consistent across the request and interruption.

An early proxy review flagged the opening fade as a black flash. It was replaced
with a continuous optical dissolve and its intermediate frames were inspected.
The interrupted utterance is captioned with a dash. The review's “cat images”
comparison conflated the later real search screen with the earlier flight
dialogue; they are separate scenes. The small music transition into the product
shots is deliberate dynamics, while the mastered speech remains intelligible.
The original proxy review is retained in `output/film-review.json`.
