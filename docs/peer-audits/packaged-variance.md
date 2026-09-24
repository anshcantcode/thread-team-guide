# Frozen package score variance — 24 September 2026

The Samsung package built from THREAD commit `c2504bc` passed the official
package/contract checks and all 27 real-time public attempts. Its
[score report](../benchmarks/mega-packaged-2026-09-24-3x.json) is **90.6
weighted**, below the earlier [94.0 source run](../benchmarks/mega-pre-local-asr-2026-09-24-3x.json).
The package was frozen before this run, with the official kit files preserved.
This difference is a measured reliability problem, not an adjusted score.

A later package from `c513567`, including a 10 ms post-turn acknowledgment
fence, also passed package and contract checks but scored only **78.0
weighted** on the complete official 27 attempts. Its
[per-attempt report](../benchmarks/mega-fenced-package-2026-09-24-3x.json)
has SHA-256 `93D7F95A8FBE93DFE4A050986E0D6F2FD14F700939318523933C34E3AEC7AF8C`;
the package ZIP SHA-256 is
`44d10a0ce8a45293221dc80a5027acb4be60e8d2c21bdb808ecf53d661e07a65`.
Its case medians were text 01–04: 100, audio 05: 72.3, audio 06: 56.9,
visual 07: 47.7, text 08: 100, unseen tool 09: 47.7. The fence did not
demonstrate an improvement. Different hosted responses and timing can also
explain part of the decline; these separate runs do not isolate one cause.

A focused replay of audio 06 against that same package scored `56.9, 56.9,
56.9`; raw harness and planner records are in the ignored local file
`.runtime/public-traces/fenced-pub06-2026-09-24-3x.json`. Every attempt
clarified without a tool call. Two Gemini MAIN planning calls hit the
4.5-second limit after acoustic calls returned HTTP 200 at 3,235 and 2,438
ms. The remaining acoustic call timed out at 3.5 seconds and blocked the
read. This follow-up shows a concrete provider-deadline bottleneck; it is a
separate sample and cannot be substituted for the 27-attempt score report.

A similar focused unseen-tool replay scored `47.7, 47.7, 100`. In the first
two attempts Gemini MAIN timed out after 4,515–4,516 ms, so no tool was
called; the third returned HTTP 200 in 1,844 ms and the agent completed the
manifest-supplied `weather_lookup` with a grounded answer. All three
post-turn acknowledgments landed 12–13 ms after the user chunk, so the 10 ms
fence addressed that narrow scorer race but did not fix the larger provider
tail. Raw records are at `.runtime/public-traces/fenced-pub09-2026-09-24-3x.json`.

A subsequent visual 07 replay scored `47.7, 47.7, 47.7` and produced no
manual lookup. Planner records show one timeout after 2,532 ms and two
transport errors before inference after 15 and 47 ms. This is additional
evidence of route availability trouble; the short transport errors are not
evidence that the model misidentified a port. Its ignored trace is
`.runtime/public-traces/fenced-pub07-2026-09-24-3x.json`.

The visual case had scores `47.7, 33.8, 100` in the packaged full run. A
second three-attempt replay against the **same package** produced `47.7, 100,
75.4`. The latter replay saved official harness traces locally at
`.runtime/public-traces/package-pub07-2026-09-24-3x.json` (ignored by Git).
In its first attempt, the agent acknowledged at 625 ms and clarified at
5,141 ms without a manual lookup. This is consistent with the 4.5-second
planning limit; the harness trace alone does not prove which internal error
caused it. In attempt 2, `lookup_manual` began at 4,359 ms, completed at
6,453 ms, and the agent answered from that result. In attempt 3, lookup began
at 4,516 ms and completed at 6,610 ms, at the end of the scenario tail; no
grounded final answer appeared. The image embedding and query were present in
both successful calls. The actionable bottleneck is time remaining after a
validated visual read is selected, not a package validation failure.

The unseen-tool case scored `76.9, 100, 24.6` in the full run. A second
packaged replay scored `76.9, 100, 100`; raw traces are at
`.runtime/public-traces/package-pub09-2026-09-24-3x.json`. In the 76.9
attempt, `weather_lookup` completed with the correct city and the agent
answered from its result. Task and safety were full credit, but latency was
zero. The acknowledgment was logged at 796 ms, four milliseconds before the
last user chunk's nominal 800 ms timestamp. The scorer therefore measured
the first **post-turn** answer at 3,828 ms (3,028 ms after that chunk). In
the two 100-point attempts, acknowledgments landed at 812 ms, 12 ms after
the nominal end. This is a narrow timing race around the turn boundary.

The full Python 3.11 suite passed in isolation after the first live run:
`1,044 tests in 64.550s, OK`. After the fence change, `1,045 tests in
72.136s, OK`; an intermediate run hit a 0.5-second mocked-request startup
wait under host load and the same test passed alone. Its startup wait was
raised to two seconds, while the tested acoustic deadline stayed at 40 ms.
These tests
verify local contracts but cannot remove hosted-model latency variance.

No public scenario ID, image label, destination, or expected answer should be
used as a production branch. A generic acknowledgment ordering fix and a
bounded, source-validated visual-read speedup require their own safety checks
and a new frozen full-package evaluation before promotion.
