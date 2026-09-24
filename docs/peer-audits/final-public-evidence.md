# Second-review fixes: frozen public evidence

Checked 24 September 2026. The post-second-review fixes were frozen at
`197b6714c55ca778f2570d6d553f859f43cd20a3`. The 52-file package is
`.runtime/mega-package-197b671.zip`, SHA-256
`84fd8c95c9ac0fa7546b75db0e7442e16d8672c73fc6efc8a5dd1183509da4ad`.
Its 33 official Samsung kit files were preserved byte for byte. Offline
verification passed Stage 1, Stage 2, all 51 manifest hashes, dependency and
import checks, and the queue/result exchange with zero external requests.
The source passed **1,082 Python 3.11 tests**. The registered team name remains
`LOCAL_DRAFT_TEAM_METADATA_REQUIRED`.

The [official 27-attempt report](../benchmarks/mega-final-197b671-2026-09-24-3x.json)
is the valid run of the unchanged Samsung evaluator with `--time-scale 1`,
`--reps 3`, the local credential file, and `PARTICIPANT_MEDIA_ROOT` set to the
unchanged kit root. The report has SHA-256
`82117b8bca835af5a97f6ff71e19e3f750ca4765709150df7bf0ddaf18289091`.
It scored **74.1 weighted**, **75.9 plain**, with **12/27 perfect attempts**.
Case medians in public-case order were **100, 58.2, 100, 100, 72.3, 56.9,
47.7, 100, 47.7**. Audio averaged 64.6 and visual 47.7 by modality. This
sample is below the earlier 78.9 frozen run and DUET's independently reproduced
97.4. None of those separate samples establishes a stable causal trend or
hidden-set performance.

An immediately preceding run of the same package scored 71.5 but omitted
`PARTICIPANT_MEDIA_ROOT`. It is retained only at ignored
`.runtime/mega-package-197b671-9x3.json` as a setup-error diagnostic and is
**excluded** from the comparison. The valid run is the `-verified-media.json`
artifact copied into the linked committed report.

Focused traces on byte-identical runtime modules explain part of the score:

- Text 02 scored **58.2/58.2/58.2**. Its corrected-turn planner recorded one
  4.515-second timeout and two HTTP 503 responses at 1.266 and 1.438 seconds.
  The original first turn still dispatched a tool call. Trace:
  `.runtime/public-traces/final-197b671-pub02-3x.json`.
- Text 09 scored **47.7/47.7/24.6** in a separate replay. Each planner request
  timed out near 4.5 seconds with no read call. Raising only the configured
  planning limit to its supported 5.5-second maximum yielded
  **47.7/47.7/47.7**, with all three calls still timing out. Traces:
  `.runtime/public-traces/final-197b671-pub09-3x.json` and
  `.runtime/public-traces/timeout55-pub09-3x.json`.
- Audio 05 scored **60.8/72.3/72.3** in a separate replay. Both acoustic
  checks on every attempt reached the 3.5-second subdeadline, so the agent
  asked for a repeat instead of treating an unverified name as fact. Trace:
  `.runtime/public-traces/final-197b671-pub05-3x.json`.
- Experimental `single_call_reads` on audio 06 scored **56.9/56.9/56.9** in
  a separate replay: two planning HTTP 503 responses and one 4.5-second
  timeout. It was not promoted. Trace:
  `.runtime/public-traces/single-call-197b671-pub06-3x.json`.

The free Groq Qwen3.8 route again scored **100** on one unseen-tool text
attempt. A subsequent interrupted-text attempt scored 74.3, and an audio-05
attempt scored 72.3; the route then received HTTP 429 during audio-05's second
turn after seven API calls. These are partial route probes, not a full-route
score, and the adapter kept image embedding disabled. Reports remain in ignored
`.runtime/provider-benchmark/groq-{pub09,focused}-final-197b671-1x.json`.
No paid API tier was enabled.

The offline [Astra counterexample probe](astra_post_fix_probes.py) was also run
against the frozen package. It rejected both sliced wrong-field primitive
writes, rejected unavailable-frame and duplicate-key decisions, dispatched a
fresh read for an updated request, retired the overdue write continuation while
recording its late receipt, and submitted exactly one effect in all 18
unresolved replay controls. The probe made zero external requests. These
injected cases test admission boundaries, not live model quality. A final
independent Astra review of this exact head remains the release gate.
