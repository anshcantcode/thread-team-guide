# THREAD — Keep going.

The replacement film for the first, slower cut. Both exports run **43 seconds
at 60 fps**, with separately composed landscape and portrait layouts.

## Play

- `output/THREAD-Keep-going-landscape.mp4` — 2560 × 1440, presentation film.
- `output/THREAD-Keep-going-vertical.mp4` — 1080 × 1920, portrait cut.
- `output/THREAD-Keep-going.srt` — English captions, also embedded as an optional
  subtitle track in each MP4.
- `output/THREAD-Keep-going-soundtrack.wav` — 48 kHz, 24-bit stereo master.

Start with [the cinematic script](SCRIPT.md). [Asset sources and exact ImageGen
prompts](ASSETS.md) accompany the project. The exports and WAV takes live locally
and are ignored by Git to keep large generated files out of the source history.

## What changed

The first request starts at 0.10 seconds. Branded flight details occupy the first
shot: airport codes, departure and arrival times, duration, date, price, a second
airline option and a legible sample-fare note. The assistant begins a reply,
the user interrupts, and the destination rolls to Mumbai inside the same ticket.

The next requests move through weather, a morning itinerary, a packing list and
Library save, Kohli's ODI-to-T20 profile, a Google images-to-videos handoff,
research sources, a calculation, a timer, two world clocks, widget pinning and
the saved trip. The film closes with **Ask. Interrupt. Keep going. THREAD.**

Large results replace chapter labels and constraint tables. The composition
uses pale ticket stock, location imagery, an athlete photo, useful charts and
animated controls. Complementary moving reveals take 320 ms with continuous easing, and
rolling text is clipped to its own slot. The soundtrack is a rhythmic 120 BPM
composition with speech ducking, an intentional interruption and timed actions.

## Relationship to the product

This is a **cinematic representation of implemented capability families**, with
purpose-built motion compositions. It is not an unedited screen recording and
does not establish measured response latency or exact shipping UI parity.

The product's flight provider is still a demonstration. Airline marks and
sample details in this film do not imply a live feed or purchasing capability.
Google is a supported search handoff; the illustrated search surface is not a
new embedded Google browser. Saving documents and returning to work, public
research, sports, weather, calculations, timers, clocks and Android home widgets
are grounded in the project. The clock sequence includes the Add action used
to complete pinning. Dates and sports statistics are captured values, documented
in ASSETS.md. The wider feature backlog is not presented as shipped.

## Rebuild

Run from the repository root with the project's `.venv` and `ffmpeg` on PATH:

```powershell
.venv\Scripts\python.exe motion\v2\voices.py
.venv\Scripts\python.exe motion\v2\soundtrack.py
.venv\Scripts\python.exe motion\v2\render_v2.py --stills
.venv\Scripts\python.exe motion\v2\render_v2.py --stills --vertical
.venv\Scripts\python.exe motion\v2\render_v2.py
.venv\Scripts\python.exe motion\v2\render_v2.py --vertical
.venv\Scripts\python.exe motion\v2\finish_v2.py
```

Dependencies remain in `motion/requirements.txt`. `render_v2.py` reuses the
existing ModernGL compositor and adds the new scenes. `voices.py` reuses the
voice helper, with an optional model parameter added for supported-model fallback.
It reads the existing API key from the repository `.env` without copying it into
production assets. Existing audio takes are reused, so a visual rerender makes
no API calls. `capture_data.py` is for an intentional weather/data refresh; doing
so also requires updating the film's dates and accompanying provenance.

`finish_v2.py` performs two-pass loudness mastering, embeds captions, checks
duration, resolution, frame count and audio format, decodes every exported
frame, measures final audio, and writes `output/manifest.json` with hashes.
`review.py` offers additional model-assisted media critique. Inspection notes
in `VERIFICATION.md` distinguish this from direct human listening.
