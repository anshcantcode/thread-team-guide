# Optional GPU ASR public trial — 24 September 2026

THREAD's default Samsung route remains Gemini independent audio perception. The `local_whisper_cuda` option was tested from the `codex/mega-revamp` source checkout on the same Windows RTX 4050 host used for the independent DUET reproduction. It uses `dropbox-dash/faster-whisper-large-v3-turbo` at revision `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`, CUDA float16, preloaded in `setup()`. The checkpoint was already cached; the process loaded CUDA libraries from the isolated Python 3.11 environment. These tests did not exercise a packaged Samsung submission.

| Public case | Three real-time scores | Observation |
| --- | --- | --- |
| [Audio 05 ambiguity](../benchmarks/local-asr-pub05-2026-09-24-3x.json) | 88.5, 72.3, 100 | Every attempt clarified before the second turn and made **no premature search**. One attempt never searched after “I said Boston”; the other two searched correctly but lost latency credit. |
| [Audio 06 repair](../benchmarks/local-asr-pub06-2026-09-24-3x.json) | 33.8, 100, 56.9 | One attempt searched New York and finished; two clarified without a tool call. No attempt searched the abandoned Boston destination. |

The separate [three-attempt timing probe](../benchmarks/local-asr-pub06-timings-2026-09-24-3x.json) scored 56.9, 56.9, 100. Its local acoustic checks completed in **1.94, 1.00, and 0.77 seconds**. The first Gemini MAIN plan timed out at **4.515 seconds**; the second returned HTTP 200 at 3.547 seconds but still did not score the search; the third returned HTTP 200 at 3.203 seconds and scored 100. This isolates a remaining plan/interpretation problem after ASR latency improves.

These two scenario samples have different attempt order and cannot be combined into a new official nine-case weighted score. The optional route's medians are worse than the [complete default-route 94.0 baseline](../benchmarks/mega-pre-local-asr-2026-09-24-3x.json), so it is **not promoted**. [Judge packaging](local-asr-packaging.md) is also unresolved because the 1.62 GB model and CUDA runtime are not part of the submission package and the judge target is unspecified.
