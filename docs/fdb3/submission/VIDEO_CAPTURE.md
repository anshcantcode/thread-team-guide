# Draft video capture and assembly record

The local `VIDEO_DRAFT.mp4` contains real recorded evidence assembled into a
four-minute-ten-second edited review. It is not an unedited capture or a fresh full
benchmark result. See `VIDEO_AND_SLIDES.md` for its chapter map and
`VIDEO_PROVENANCE.json` for exact SHA-256 identities and the latest QA result.

## Actual sources

- Benchmark: archive `20260927T175531Z-6dcc34fa`, source
  `088cf6fcfbb33958f631738c808d26cbb0088241`, `case-011`, original `input.wav`,
  received `inference/spoken.wav` and `inference/result.json`.
- Extension: separately preregistered `extension-audio015`, frozen desktop
  source `fecb5c221e2609e39799b87627e1f7327a54da89`, owned `emulator-5560`,
  recorded developer-authored SAPI input, received WebRTC PCM, actual silent
  `adb screenrecord`, actual after-check screenshot, tool/native receipts,
  restart readback and successful cleanup records. The separate native viewer
  source is `8e9324ab74d84c3a77c47e278702a6a066a1bf41`; its APK hash is in
  `VIDEO_PROVENANCE.json`. Native files match that commit, while the build
  worktree contained unrelated changes. Packaged Python was not executed by
  this tethered run; the desktop runtime remained frozen. This exposed authored
  control is not held-out or official benchmark evidence.
- Context: rendered slides 1, 3, 4, 7 and 8 from the prepared eight-slide draft.
  Microsoft Zira Desktop, through local Windows System.Speech, reads explicitly
  labelled narration outside the two evidence scenes. The narration text and
  generated audio hashes are recorded in the provenance manifest.

## Disclosed edits

The output uses H.264 picture at 1280 x 720 and 24 frames per second, with AAC
stereo sound at 48 kHz. FFmpeg assembles eight chapters. No GPU, planner,
recognizer, evaluator or device action runs during video assembly.

The 50-second benchmark chapter includes the full 40.680-second input WAV and
full 48.610-second received WAV. The output track starts 61.071 ms after the
input, using the saved arrival-clock difference. Each track has gain 0.85 and
is resampled for the final audio format; neither is sped up or edited for
content. Only trailing silence is added. The saved-log tool panel appears at
the recorded dispatch offset. It is a report panel, not fabricated application
footage. Arrival timing is not an official latency measurement.

The 50-second extension chapter includes the full 11.0695-second authored
input and full 43.290-second received WAV. Its approximate audio alignment uses
`input_finished_at - input_duration` as the input origin and the first received
PCM timestamp as the output origin. The received track starts at scene time
zero; the input starts 1.199829 seconds later. This is an editing estimate:
transport pacing and capture clocks do not establish speaker-playout timing.
Both original tracks retain their pacing and have gain 0.85. No synthesized
success speech is inserted into either evidence scene.

The actual extension display uses seconds 20.4-65.4 of the original silent
emulator recording, at original speed. Its top-left 540 x 750 pixel region is
resized to 332 x 461 pixels, showing the real saved item and receipt. The
approximate display alignment uses the first visible viewer near source second
49 and the logged viewer-open completion at scene second 28.617. It is labelled
approximate and supports no latency claim. At scene second 45, an explicit cut
shows the same run's actual screenshot after process restart, cropped from its
top-left 1080 x 1500 pixels to the same display area. The read-only native viewer
and native `read_checklist` agree. The complete one-call agent write trace and
later verification read are disclosed. Failed take 013 and successful earlier
take 014 remain in the raw evidence; their audio or device images are not used
as substitutes for take 015.

The other six chapters are context slides or a receipt report with synthetic
narration. Their title banner identifies that narration. Chapter boundaries,
source versions and the later readback cut remain visible. They must not be
described as a single continuous live run.

## Verification and retained material

The assembly workspace is ignored under `.thread-run/submission-build/video/`.
It retains narration source/WAVs, chapter MP4s, FFmpeg commands, logs and sampled
review frames. Original benchmark and extension recordings remain unchanged in
their respective evidence roots. `VIDEO_PROVENANCE.json` uses portable logical
source names with hashes rather than claiming those large raw bundles are
embedded in the repository.

Archive-location refresh, 28 September: the logical prefix
`archive/20260927T175531Z-6dcc34fa/` now resolves to the canonical
`C:/Users/ANSH/fdb3-evidence/20260927T175531Z-6dcc34fa/`, not the removed
duplicate in its frozen worktree. All media hashes and the MP4 are unchanged.
The [companion score note](VIDEO_AND_SLIDES.md#28-september-score-update-speaker-note--companion-caption)
updates the historical 50/100 narration without changing the recording.

Final QA probes picture/sound duration, codec, resolution and chapter markers;
decodes the complete MP4 with FFmpeg; measures audio peak; and visually inspects
every chapter plus tool-dispatch and later-readback states. Full human listening
and playback remain a final review item. A successful decode and readable
frames do not establish human hearing or organizer acceptance.

For any future capture, freeze the actual release source and APK, retain
preregistration/configuration, and record the full flow with the visible
read-only native viewer. Verify the same item after process restart. Preserve
failed takes and every executed call. Use only the owned emulator and remove
only its diagnostic session data afterward. Label authored synthetic input and
any cuts. A new take needs its own run, APK hash, source identity and outcome;
never substitute an older run's UI or receipt without disclosing the separate
evidence.

Before release, review the complete file, replace authorized team placeholders,
choose an accessible public video location and test the URL independently of
the team's private account. Update the deck, final fields and tagged repository
to reference the same approved video hash. No upload or submission is performed
by this local assembly step.
