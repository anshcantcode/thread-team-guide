# Post-review frozen package: public evidence

Checked 24 September 2026. The safety fixes following the first Astra review
were frozen at `c3eba57` in a 52-file package. Its ZIP SHA-256 is
`9e080d733df4a6d2c856e62012fd8890a8bbdaeeaa11dbbf3f8a9af212b3254a`.
The unchanged official Samsung kit's Stage 1 and Stage 2 checks passed; 33
official files were byte-preserved, 51 manifest member hashes verified, and
the offline exchange made zero external requests. The source passed 1,066
Python 3.11 tests. Android `:app:testDebugUnitTest` passed locally and is now
part of CI. These gates do not measure hosted-model quality.

The frozen package completed the official nine public cases, three attempts
each, at `--time-scale 1`. Its [27-attempt report](../benchmarks/mega-post-fix-2026-09-24-3x.json)
has checked-out SHA-256
`88098876b16108da85de7bd5303e6c3403e723459aa6dc6cbe79917cfb2d3fb0`.
The weighted score was **78.9**, plain average 81.7, with 15/27 perfect
attempts. Case medians were text 01 100, interrupted text 02 58.2, chained
booking 03 100, no-tool text 04 100, audio 05 72.3, audio 06 56.9, visual
07 47.7, tool failure 08 100, and unseen tool 09 100. This does not establish
a stable improvement over prior THREAD samples or DUET's reproduced 97.4.

Focused replays on the same source immediately after the full batch gave text
02 **100/100/100**, audio 06 **100/100/100**, and visual 07
**47.7/100/47.7**. Their raw official harness traces and redacted planner
records are in ignored `.runtime/public-traces/current-pub{02,06,07}-2026-09-24-3x.json`.
All three successful audio-06 replays had HTTP 200 acoustic and MAIN calls:
acoustic durations 2,562–2,968 ms, planning 3,156–3,625 ms. Earlier failed
audio-06 traces recorded 3.5-second acoustic or 4.5-second MAIN deadlines.
The full batch and focused replay are separate samples, so the favorable replay
cannot replace the frozen score. They show how strongly the free hosted route's
deadline availability affects the public score.

In the visual replay, one 4.515-second MAIN timeout produced no lookup. One
HTTP 200 decision at 2.734 seconds copied both `HDMI` and `SS` from the
image, but asked which port the user meant and did not call `lookup_manual`.
The third attempt selected a supported conditional HDMI lookup and scored 100.
This separates an actual recognition/referent decision miss from the timeout;
no safe fix follows from the public score alone. A free-tier
`gemini-3.5-flash` visual trial on the same source scored **47.7/47.7/100**,
with two 4.5-second MAIN timeouts. A Groq Qwen visual retry returned 429 on
its first call, so it supplied no fair three-attempt comparison. None of these
focused probes is a substitute for a complete route evaluation.

The submission metadata still says `LOCAL_DRAFT_TEAM_METADATA_REQUIRED` until
the registered team name is supplied. The private draft PR remains a review
candidate, not a claimed competition winner or final submission.
