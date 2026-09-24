# Frozen package score variance — 24 September 2026

The Samsung package built from THREAD commit `c2504bc` passed the official
package/contract checks and all 27 real-time public attempts. Its
[score report](../benchmarks/mega-packaged-2026-09-24-3x.json) is **90.6
weighted**, below the earlier [94.0 source run](../benchmarks/mega-pre-local-asr-2026-09-24-3x.json).
The package was frozen before this run, with the official kit files preserved.
This difference is a measured reliability problem, not an adjusted score.

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

The full Python 3.11 suite passed in isolation after the live run:
`1,044 tests in 64.550s, OK`. An earlier suite run concurrent with the
evaluator had one timing-test failure that passed on rerun. These tests
verify local contracts but cannot remove hosted-model latency variance.

No public scenario ID, image label, destination, or expected answer should be
used as a production branch. A generic acknowledgment ordering fix and a
bounded, source-validated visual-read speedup require their own safety checks
and a new frozen full-package evaluation before promotion.
