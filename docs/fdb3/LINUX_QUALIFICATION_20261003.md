# S2 Linux one-command qualification — 3 October 2026

## Status

**QUALIFIED for the requested local WSL, full-100, one-command execution.** Attempt `full-003` completed all 100 recordings from measured source `8ef5b590a949586a4661df7e250bc7f62769acc4`. The script's own verifier reports `complete=true`, `judge_verified=true`, 100 completed/evaluated and **61/100 strict passes**. All four execution stages exited 0. The overall script exit is **1**, the documented complete-with-non-passes outcome, not an infrastructure failure. Earlier partial attempts are not combined with it.

This is **not qualification on the organizers' 48 GB hardware or with their official judge**. Local Qwen judging remains diagnostic and `qualification_eligible=false` remains unchanged. The final documentation/evidence commit does not change the measured runtime. [Machine-readable summary and output hashes](evidence/s2-linux-qualification-20261003.json).

The requested base was `5191ea5`. The release branch had advanced to `f83e389` when inspected; this isolated branch deliberately starts from the requested `5191ea5`, not the moving release reference. All S2 commits were made on that isolated branch. No push, PR, release upload, hosted judge or paid API was used. Spending: **INR 0**.

## Tested environment and command

- WSL distro `THREAD-Submission-Sprint3`, Ubuntu 24.04, Linux 6.6.87.2.
- NVIDIA RTX 4050 Laptop GPU, 6,141 MiB reported total; driver 592.82, reporting CUDA driver compatibility 13.1. This is not the organizer's 48 GB GPU.
- WSL memory approximately 7.6 GiB with 2 GiB swap. Build parallelism 1; OpenMP/OpenBLAS/MKL threads 1 in the private supervisor.
- Existing uv-managed **CPython 3.11.16**, at `/root/.local/share/uv/python/cpython-3.11.16-linux-x86_64-gnu/bin/python3.11`; `python3.11` was absent from PATH. uv version 0.12.19. See [explicit Python/toolkit provisioning](REPRODUCE.md).
- Qwen3.5-4B Q4_K_M, Whisper small.en CUDA/float16, seed 42 and the release's other candidate settings unchanged. Linux speech output uses espeak-ng.
- The permitted September 28 CUDA 12.4 **SM89** llama build was reused at executable SHA-256 `c34cf1dc8c6ded0a49d4f77ede370a69e66682e6cad50c4f651a238d1325af23`. Its source is pinned commit `56381e407c0ccfb3a6f71e668a27a901001d22ce`. This is not a portable binary claim for arbitrary GPU architectures.

Every attempt uses a `git archive` export extracted into the Linux filesystem, without `.git`, and a different new `THREAD_WORK`. The source snapshot records null Git commit/dirty values and exact source hashes; it does not borrow an unrelated checkout identity. The measured `8ef5b59` source tar has SHA-256 `c2aac7e5f78027ac8342a24cbee83bfe6af180423bb7e174db64d5c0109549f7`; its 903 members include no `.git`, `.thread-run`, `.runtime`, `.venv`, `__pycache__`, `.env` or GPU-lock entries.

The full command is `bash scripts/reproduce_fdb3_linux.sh`. The local supervisor supplies `THREAD_PYTHON`, the released data zip, a fresh `THREAD_WORK`, `THREAD_FDB3_JUDGE_MODE=local`, `THREAD_BUILD_JOBS=1` and the permitted `LLAMA_SERVER`. It bounds each full attempt to four hours with `timeout --foreground`, closes stdin, and samples `nvidia-smi` every second. It never starts Windows llama-server.

The first task preparation used fresh task-owned pip/Hugging Face caches. The repaired download path downloaded and hash-verified GGUF, Whisper and LiveKit assets. `full-001` installed the real 225-package hash-locked evaluator environment, checked dependency consistency, and downloaded/restored the upstream NeMo model. Later attempts declare reuse of those task-owned caches and the supported supplied-GGUF/Whisper options, with hashes rechecked by the script. They still create new environments, re-download/verify LiveKit and run fresh inference. No earlier result is reused. This is **not** a claim of an entirely cache-free final attempt.

The unchanged upstream selected `nvidia/parakeet-tdt-0.6b-v2`, observed snapshot `ae9ad07059c7c739ffaf932226a8fe64ae2620b0`. Its 2,472,222,720-byte NeMo file has SHA-256 `d99e39955c9d3d0350d8fb7c75e40c64a2b2eaeb003883d7c941fd2e8747b28c`. This records the actual download; it does not change the official evaluator's model selection.

## Completed full-003 measurement

| Measure | Actual result |
|---|---|
| UTC start / finish | 2026-10-03 13:26:42 / 15:24:08 |
| Whole-command wall time | **7,046 seconds (1 h 57 min 26 s)**, including fresh environment installation with declared cache reuse |
| Found / completed inference / evaluated | **100 / 100 / 100** |
| Strict tool pass | **61/100 (61%)** |
| Tool selection accuracy (F1), as upstream prints it | **87.1%**, turn-taken only, N=95 |
| Argument accuracy, as upstream prints it | **66.8%**, turn-taken only, N=95 |
| Response quality, as upstream prints it | **69.5%**, turn-taken only, N=95 |
| Silent/no-response recordings | **5**; still in the 100-recording strict denominator, not skipped |
| Infrastructure failures observed | **0**; 100 closed sessions, zero recorded session errors, all stages exit 0 |
| Checked tool / pass judge requests | **218 / 111 successful**, zero failed or pending |
| Additional latency judge calls | **95 logical local calls**, inferred from upstream control flow and populated outputs; not covered by checked-wrapper request receipts |
| Latency analyzer coverage | **100 analyzed, 0 skipped, 0 failed** |
| Peak sampled GPU utilization / used VRAM | **100% / 5,817 MiB** |
| Minimum reported free VRAM | **104 MiB** |
| Main script / verifier exit | **1 / 1**, complete with strict non-passes |

The upstream report also preserves its all-recording tool selection / argument fields (`tool_selection_acc_all=0.867`, `argument_acc_all=0.665`). The headline numbers above are the evaluator's printed N=95 measures, not a substituted denominator or the historical Windows response-quality count. The five silent recordings are model outcomes, not missing inference jobs.

Upstream latency output is preserved verbatim:

| Latency measure | N | Mean ± standard deviation | Minimum / median / maximum |
|---|---:|---:|---:|
| First response | 95 | 12.94 ± 4.40 s | 6.32 / 11.84 / 28.24 s |
| Tool call | 86 | 8.11 ± 3.34 s | 4.02 / 7.68 / 26.35 s |
| Local-judge task completion | 95 | 12.47 ± 8.16 s | **-19.76** / 12.24 / 28.24 s |

There are **four negative judge-selected task-completion latencies**. These are not valid physical timing estimates; they are an explicitly retained limitation of this local judge/analysis, not corrected or clamped values. All 95 speech-bearing latency rows have populated results and no recorded `LLM error`; the other five say `No ASR chunks`. Latency uses 95 additional logical calls beyond the 329 checked tool/pass requests. It has no checked-wrapper per-request receipts, so wire-level latency retries are not independently counted. All stages target the local Qwen endpoint; no hosted judge is enabled.

GPU figures come from 6,963 valid `nvidia-smi` host-wide samples requested at one-second intervals, not a continuous profiler or per-process allocation measurement. The GPU services had exited when checked; the original owner-checked shared lock was released at **2026-10-03T15:29:04Z**. No Windows llama-server was started or observed by the task monitor.

## Preserved attempts

| Attempt | Source | Actual outcome |
|---|---|---|
| `prepare-001-missing-python` | `5191ea5` | Exit 2: required Python command missing |
| `prepare-002` | `5191ea5` | Exit 0, `PREPARED_ONLY`, using the explicit managed interpreter |
| `prepare-003` | `48fb504` | Exit 2: interrupted GGUF transfer, curl HTTP/2 error 92; partial bytes retained |
| `prepare-004` | `d3593b3` | Linux exit 0, `PREPARED_ONLY`; separate Windows tool transport returned 1 with console error 0xE9 |
| `full-001` | `d3593b3` | Exit 143 after stopping the owned, terminal-suspended process group; 0 completed; 2,176 seconds |
| `prepare-005` | `1362509` | Exit 0, `PREPARED_ONLY` |
| `full-002` | `1362509` | Exit 143 after repeated ASCII decoding failures; 1 completed, 4 `inference_failed`, 95 without a final result; 1,017 seconds |
| `prepare-006` | `8ef5b59` | Exit 0, `PREPARED_ONLY` |
| `full-003` | `8ef5b59` | Complete; all 100 inferred/evaluated; strict 61/100; all stage exits 0, overall exit 1; 7,046 seconds |

Both aborted full attempts were separately checked with the script's own verifier after termination. They return incomplete (exit 2), with all 100 inputs retained in the accounting. That post-abort check is **not** the normal successful end of the full script. The initial `full-001` post-abort verifier invocation incorrectly addressed the extraction parent and found zero inputs; that invocation and the corrected 100-input invocation are both preserved. Its zero-byte transient `/tmp` collector disappeared after WSL restarted; no replacement was fabricated. Persistent attempt logs and per-room journals remain.

`full-001` host-wide sampled VRAM peak: 5,728 MiB; peak GPU utilization: 44%. `full-002`: 5,855 MiB and 99%. Neither has valid aggregate benchmark scores. GPU samples include desktop/driver overhead and are not per-process allocation measurements.

## Repairs and verification

| Commit | General repair | Evidence |
|---|---|---|
| `48fb504` | Pinned LiveKit download and executable verification; exact receipt for the allowed archive-built llama binary; explicit compiler/toolkit prerequisites; disable unpinned prebuilt UI fetch | Clean preparations, real asset hashes, identity rejection/acceptance tests, headless CMake UI component check |
| `d3593b3` | Bounded asset transfer retries; retain each failed transfer; fail immediately on hash mismatch; refuse overwrites | Authored curl failure controls and successful real downloads |
| `1362509` | Close batch stdin so supervised upstream FFmpeg cannot stop on terminal input | Authored-silence control: old behavior timed out 124, closed stdin exited 0; regression fails before fix and passes afterward |
| `8ef5b59` | Stable Python UTF-8 child/subprocess decoding even after a native-library locale reset to `C` | Authored Unicode control fails in ASCII mode and passes in UTF-8 mode; behavioral entrypoint regression |

Executed suites:

- **1,891 base tests passed**, no failures/errors/skips, 385.852 seconds, source `48fb504`, using the requested Windows venv. Later changes are reproduction setup fixes, not silently re-labelled executions of this suite.
- **102 SDK tests passed**, exit 0, 41.468 seconds, source `48fb504`, in a dependency-complete Linux test environment. Earlier invocations with missing SDK/test dependencies or fixture/TTS environment are retained as failed evidence.
- **31 runner tests passed** at `8ef5b59`: Windows/Git Bash 9.384 seconds; native Ubuntu from the clean source export 6.541 seconds.
- Headless UI CMake component check passed. S2 did **not** rebuild the entire CUDA llama executable; permitted exact-hash reuse is declared above.
- Upstream tracked inference/evaluator files were verified unchanged against `3e799c45a045256f47d5f1c9cda90157e2d2ec9e` before/after both `full-002` and `full-003`. Every final runtime source-snapshot hash matches. No grading rules, test expectations, benchmark answers or case-specific runtime logic were changed.

## Evidence and remaining qualification boundary

Private progress is under the isolated worktree's `.thread-run/STATE.json`, `NEXT.md` and `S2_STATUS.md`. Raw attempts are preserved under `/opt/thread-linux-qual-20261003/`; `evidence/` contains command logs, exits, timestamps, GPU samples, platform/source receipts, upstream audits and output hash manifests. These private runtime directories are not committed or submission assets.

Exact copies of the final reports, checked judge receipts, GPU CSV, source identity, audits and selected failed-attempt summaries are also retained in the qualification checkout's private `.thread-run/evidence/S2-20261003-final` folder. Its inventory verifies the copied bytes. The committed JSON is a curated aggregate/hash summary, not the private logs, corpus, credentials, model cache or case-level answers. The existing published release assets have not been changed.

The paths below are relative to `/opt/thread-linux-qual-20261003/`:

| Output | SHA-256 |
|---|---|
| `full-003/verification.json` | `bdf5e5b60026e393006907a6da5336091449f95e5213f7df8548e27c72bba4ea` |
| `full-003/thread_evaluation_report.json` | `d904f11f2fbcb8c268f8e3bd331212c101a70fb20e0f9808d78270982786950a` |
| `full-003/thread_pass_rate_report.json` | `5760b7d78d891b0d7d525a94a15c8436472cf64ecc2ee0f0b9c98856b1f83c7e` |
| `full-003/upstream/v3/thread_latency_report.json` | `c91a410ce5b7ae9a72363959e4cab30ed00445d05f63d246a49498ac1807a9ea` |
| `full-003/source-identity.json` | `d8e0ca915b8253e13eca91660616a9f2032dfd6a98330e197e2d9d6b48ed8f37` |
| `evidence/full-003-output-hashes.json` | `ff5127f7695142dcb5c29801fba84b256cf24164941e45205268d6753ea67046` |

The complete output manifest covers per-recording result/evaluation/audio outputs, session journals, logs and receipts; the source archive is separately hashed above. The final global tool collector was copied after all 100 sessions closed to `full-003/logs/agent-tool-calls.post-inference.jsonl`, SHA-256 `f39c4a5c73baf15422f0000b355252054764e1f48b723eca940a689369a4eb8d`. No `.thread-run/raw` evidence was changed.

The organizer command and prerequisites are in [REPRODUCE.md](REPRODUCE.md). A CUDA driver alone is insufficient to compile llama-server: the clean build route requires a compatible CUDA toolkit, CMake and host build tools. The 48 GB hardware, a new full CUDA build and every CUDA 12/13 toolchain combination have not been exercised by S2. Local Qwen judging is diagnostic, not Samsung's official judge; the verifier's `qualification_eligible` flag is not changed to manufacture official qualification.

AI coding assistance was used for these setup repairs, tests and execution/evidence recording (see the [AI disclosure](../submission/AI_DISCLOSURE.md)). No human form was signed, no existing attribution was removed, and no release or submission was published.
