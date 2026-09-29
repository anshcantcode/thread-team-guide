# Offline participant trace film

`scripts/render_participant_demo.py` turns retained official-participant evidence into a local MP4. It reads files only; it never imports or executes the participant, evaluator, model client or application. The existing `scripts/render_evidence.py` serves the separate browser application and its different trace format.

Use Python with Pillow and the installed FFmpeg/FFprobe executables. The renderer uses the repository's Manrope font under its existing OFL licence. It adds no runtime dependency to the participant package.

Prepare cards first, using a private cut file and a **new** private output directory:

```powershell
python scripts/render_participant_demo.py --self-test
python scripts/render_participant_demo.py --cut <cut.json> --evidence <sealed-acceptance-directory> --kit <original-kit-directory> --out <new-private-output-directory>
```

Inspect `contact-sheet.jpg` and the full-size `cards/*.png`. Fix the cut if any text, image or explanation is misleading. Preparation rejects missing references, changed evidence hashes, unconsumed media, overflowing text, truncated audio and a film at or above five minutes. It preserves the source commit, archive hash, source files, exact excerpt pointers, original event timestamps and input-media hashes in `source-cut-manifest.json`.

Only encode when resource use is appropriate for any concurrent evaluation:

```powershell
python scripts/render_participant_demo.py --encode --out <prepared-private-output-directory>
```

The result is `THREAD-participant-demo.mp4`: 1600 × 900, H.264, 10 fps, AAC audio and fast-start metadata. Encoding uses two video threads. `media-qa.json` records duration, streams, a full decode check, output hash and byte-exact decoded-input placement in the lossless intermediate soundtrack. The MP4 uses lossy AAC; the PCM equality check applies to `original-inputs.wav`. Automated decoding does not replace listening or visual inspection. Preserve the encoding log, final review and source/cut manifest alongside the film. Existing MP4 files are never overwritten.

The cut is deliberately small JSON: pinned `review_sha256` and `factual_sha256`, a `sources` mapping of names to retained attempt files relative to the evidence directory, and an ordered `cards` list. Each card supplies `section`, `title`, `duration_s`, `blocks` and an optional explanation `note`. A block has a `label` and either authored `text` or a `ref` such as `case02#/trace/10/payload/text`; `time_ref` can point to that event's original `t_ms`. Optional `size` changes the block's text size. An `image` or `audio` path is relative to the original kit, with `media_source` naming the attempt whose model-input evidence must contain the matching hash. Audio starts one second into its card unless `audio_offset_s` is specified, plays completely at normal speed, and must fit within the card. Optional `related_reviews` entries pin a separate batch receipt by `name`, absolute `path` and `sha256`; they supply context without changing the selected replay's identity.

Every frame says **Recorded replay · Mock tools**. The layout is an evidence presentation, not a recording of the application UI. Separate scenarios stay separate. Explanation holds and edited soundtrack placement are visible; film duration is never a latency measurement. Original trace times remain the timing evidence. Only original input recordings supply sound; assistant speech events appear as exact text. No synthetic assistant voice, manual passage, combined dialogue or unrun outcome is added. The kit recordings' human/synthetic origin must remain unverified unless separate provenance is supplied.

The selected clips do not replace whole-batch results. Show the actual returned manual metadata as metadata, keep conditional answers conditional, retain failed or incomplete qualification results, and update the result card only from independently sealed evidence on the identified artifact. Required assistance disclosures, third-party credits and team metadata remain separate submission obligations.
