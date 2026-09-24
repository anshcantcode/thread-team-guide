# Release-candidate public evidence — 24 September 2026

The safety follow-ups and competitor-derived inline audio correction were frozen at
`8bbe8e29c322d927e25c3f97d4e91223452a608b`. The local draft package is
`.runtime/mega-package-8bbe8e2.zip`, SHA-256
`cac7db3ea7ecbbb6150d39d7e72cbbe57af5bd505d6108d48ad88e00fe4f892b`.
It contains 52 unique members, preserves 33 official Samsung kit files byte for
byte, and includes the seven allowlisted participant runtime modules. The
offline verifier passed official Stage 1 and 2, all manifest and import checks,
exact dependency pins, and the queue/result exchange with zero external
requests. A clean Python 3.11 run passed **1,122 tests**. The browser WAV,
microphone lifecycle, live-audio, and 72 workspace rendering/export checks
also passed. The registered team field is still
`LOCAL_DRAFT_TEAM_METADATA_REQUIRED`.

The [official public report](../benchmarks/mega-review-8bbe8e2-2026-09-24-3x.json)
used the unchanged Samsung evaluator, all nine public scenarios, three
repetitions each, `--time-scale 1`, the local Gemini credential file, and
`PARTICIPANT_MEDIA_ROOT` explicitly set to the official kit. Its normalized
file SHA-256 is
`66456ed376f232a9bf72249726fdeef63cd984f78375d8cb939b3d45f1a7912c`.

| Scenario | Three attempt totals | Median |
| --- | --- | ---: |
| Text 01 | 100 / 100 / 100 | 100 |
| Text 02 interruption | 56.8 / 58.2 / 44.2 | 56.8 |
| Text 03 chained booking | 100 / 100 / 100 | 100 |
| Text 04 no tool | 100 / 100 / 76.9 | 100 |
| Audio 05 ambiguity | 42.6 / 60.8 / 72.3 | 60.8 |
| Audio 06 disfluency | 56.9 / 56.9 / 56.9 | 56.9 |
| Visual 07 port lookup | 47.7 / 47.7 / 47.7 | 47.7 |
| Text 08 tool failure | 100 / 100 / 80.8 | 100 |
| Text 09 unseen tool | 47.7 / 47.7 / 24.6 | 47.7 |

**Weighted score: 72.3; plain average: 74.4; perfect attempts: 10/27.**
This sample is below THREAD's previous 74.1 frozen package and DUET's
independently reproduced 97.4. The three were measured at different times,
so the numbers do not establish a stable trend or hidden-set ranking.

Separate focused replays on runtime modules byte-identical to this package
diagnose several misses; they are not the raw traces of the aggregate run:

- Text 09 scored 47.7 / 47.7 / 47.7; all three planning requests hit the
  4.5-second deadline without an accepted unseen-tool call. Retained trace:
  `.runtime/public-traces/review-8bbe8e2-pub09.json`.
- Visual 07 scored 24.6 / 47.7 / 24.6; all three MAIN requests timed out near
  4.5 seconds. Disabling image embedding in a separate three-attempt trial
  scored 24.6 each time, also all timeouts. This does not support turning the
  embedding off. Retained traces:
  `.runtime/public-traces/review-8bbe8e2-pub07{,-noembed}.json`.
- Audio 05 scored 65.8 / 72.3 / 60.8. The six acoustic checks returned two
  HTTP 503 responses and four 3.5-second timeouts; the controller blocked
  unverified audio effects. Retained trace:
  `.runtime/public-traces/review-8bbe8e2-pub05.json`.
- Text 02 scored 58.2 / 58.2 / 45.4. Each corrected-turn MAIN request timed
  out near 4.5 seconds after the first local read. Retained trace:
  `.runtime/public-traces/review-8bbe8e2-pub02.json`.

The [prior Astra release review](ASTRA_RELEASE_REVIEW_4f1abcf.md) found five
deterministic code failures. New focused tests and the offline
`astra_release_probes.py` now reject the decimal-prefix write, wrong target,
enum override, result-bound numeric substitution, duplicate/incomplete
acoustic corroboration, and unavailable-image text/audio lookups; exact values
and verified nonvisual recovery remain accepted. Additional Luna probes closed
result-bound boolean and string substitutions, coordinated-clause target
borrowing, and an adjective-before-field string substitution. Astra High added
bounded correction-tail normalization only after independently verified audio.
The full-suite run caught a read-only binding regression in that follow-up;
`8bbe8e2` scopes the new string authority check to state changes, and the
previously failing freshness test plus the complete suite pass. The final
independent Astra XHigh review is a separate release gate.

Gemini Priority billing was deferred by the user. Standard free Gemini remains
the only complete current submission route; Groq Qwen text checks were fast but
its shared daily token cap and incomplete visual/audio comparison prevent
promotion. Optional local Whisper is not in this package: it needs unpinned
dependencies and model weights absent from the candidate, and the kit does
not promise a cached model or GPU. No paid tier was enabled. This is a draft
candidate, not a submitted entry or a claim of parity with DUET.
