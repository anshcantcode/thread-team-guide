# Four-minute-ten-second draft evidence review and eight-slide deck

`VIDEO_DRAFT.mp4` is a local edited draft, not an uploaded or submitted video.
Its picture and sound streams last 250 seconds. It combines original recorded
benchmark audio, complete executed-tool records, an actual emulator recording,
and visibly labelled synthetic context narration. `VIDEO_PROVENANCE.json`
records source identities, file hashes, edits and verification.

The updated Theme 05 guide requests a 3-5 minute real demo and says that unedited
single takes are preferred. This draft discloses its separate recordings and
report panels; it does not present them as one continuous live session. A human
should review the complete sound track and the organizer's demonstration
requirement before using it as the final submission video. Unknown team and
public-link fields remain placeholders.

## 28 September score update: speaker note / companion caption

Use this note with the **2:59–3:28 results chapter**. It is companion text,
not an edit to the MP4, its audio, captions or source provenance:

> The video shows the earlier run `20260927T175531Z-6dcc34fa` on `088cf6f`:
> 50/100 strict with local Qwen, 42/100 without a judge. The latest completed
> diagnostic is run #3, `20260928T033707Z-18db0ad9` on frozen `f6329dd`:
> 53/100 strict and window-strict, 100 evaluated, 47 non-passes and zero paid
> requests, using local Qwen3.5-4B, not the organizers' judge. Its exact rescore
> is 45/100 on the same saved inference. Source: evidence commit `eb6bdb3`.
> Run #4 on `18ad4ea` is pending, result unknown here. Task C's later natural
> answers are unmeasured. No organizer score or competitive ranking is claimed.

The video's spoken phrase "best archived complete local run" describes its
earlier evidence snapshot, not the latest result. Do not silently relabel the
`088cf6f` audio as `f6329dd` or run #4. The refreshed deck is a later snapshot
than the slide images embedded in the unchanged video.
Sources: [release evidence](../RELEASE_EVIDENCE.md) and
[task-D source record](../evidence/task-d-docs-20260928.json).

## Chapter map

| Time | What the viewer sees and hears | Evidence boundary |
|---|---|---|
| 0:00-0:21 | THREAD title and team placeholders; synthetic introduction | Edited local draft, not an official score. |
| 0:21-0:49 | Architecture from the prepared deck; synthetic explanation | LiveKit, Whisper, Qwen proposals, shared controller, tool ledger and speech. |
| 0:49-1:39 | Full original benchmark input and received response; saved-log display of every executed call | Archived local diagnostic `20260927T175531Z-6dcc34fa`, source `088cf6f`, `case-011`. |
| 1:39-2:09 | Complete one-call receipt and synthetic explanation | `add_to_cart(product_id="B7", quantity=1)`; successful receipt has cart total `99.99`. |
| 2:09-2:59 | Separate kitchen checklist diagnostic; recorded authored input, received response, actual emulator excerpt and native receipt/readback | Extension source and APK are identified in the video and provenance manifest. This is a tethered emulator diagnostic. |
| 2:59-3:28 | Archived complete-run table; synthetic explanation | 50/100 local strict tool passes, 42 judge-free exact matches, zero infrastructure errors; source `088cf6f`. |
| 3:28-3:56 | Intended Linux reproduction entry point and prerequisites | Independent clean full Linux execution remains outstanding. |
| 3:56-4:10 | Next checkpoint and placeholder submission fields | Fresh frozen-candidate evidence, reproduction and human submission review remain distinct requirements. |

## Benchmark source

Recording `ecommerce_11_62a885d5b6af18b3d4579e1b` contains a correction from
quantity three to one before dispatch. The archived trace has exactly one
executed call and a matching successful receipt. The video includes the complete
`input.wav` and `inference/spoken.wav` at their original speed. Its call display
is reconstructed from the saved trace, clearly labelled as such. It is not a
screen recording of a fresh benchmark run and is not evidence that later code
achieved the same result. Local Qwen response labels can miss factual errors.
Its canonical media path is
`C:/Users/ANSH/fdb3-evidence/20260927T175531Z-6dcc34fa/case-011/`.
The deleted duplicate in the old frozen worktree is not a source location.

## Extension source

The extension chapter uses fresh `extension-audio015`, with frozen desktop
runtime `fecb5c2` and a separately identified native read-only viewer from
`8e9324a`. The installed APK SHA-256 is recorded in the provenance manifest.
The developer-authored synthetic input first asks for celery, retracts that
request, and asks for `wash the spinach`. Exactly one actual
`add_checklist_item` call writes the spinach item. The recorded viewer displays
that saved item and its successful action receipt. Force-stop, native restart,
`read_checklist` and persisted storage agree; no celery item exists. The viewer
itself was verified not to change the preference map.

The complete received WebRTC audio is preserved, with no added assistant speech.
The device recording is cropped and scaled for readability, with approximate
clock alignment disclosed. A separate later screenshot shows the actual viewer
after process restart. The scene is a tethered emulator diagnostic, using an
exposed authored control, not held-out evidence or a standalone Android speech
agent. See `../evidence/extension015-summary.json` for exact run and APK scope.
The benchmark remains a separate archived source.

Failed take `extension-audio013` is retained: a missing CUDA DLL search path
stopped ASR before any device write. It is not counted as a successful run.
The successful earlier `extension-audio014` receipts and launcher recording are
also retained, but are not spliced into the final extension chapter.

## Deck relationship and remaining review

The video reuses an **earlier rendering** of slides 1, 3, 4, 7 and 8 of
`CollegeName_TeamName_Submission_DRAFT.pptx`. Task D refreshes the editable deck
without changing the MP4 or those embedded slide snapshots. The complete deck
has eight slides. Its source template had twelve slides and
was consolidated to the updated guide's eight-slide limit. The deck and final
submission fields must be refreshed together when new verified evidence or team
details become available.

No public video URL, final release tag, disclosure signature, organizer score,
100/100 result or successful clean Linux rerun is claimed. The final release
should bind the chosen source, configuration, reproduction output, deck,
disclosure and video reference before the authorized submission flow.
