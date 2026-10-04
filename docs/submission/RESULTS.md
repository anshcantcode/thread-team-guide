# Results and reproducibility

**4 October 2026 final source.** THREAD's selected benchmark configuration uses pinned Whisper `small.en` and Qwen3.5-4B Q4_K_M. The final-source measurement is the **full Windows run `20261003T192003Z-cf861d7d` at `4e88d4b`: 63/100 strict tool passes**, 79/100 spoken answers judged correct, 58/100 both, all 100 recordings evaluated and zero infrastructure errors. The judge was the local Qwen3.5-4B diagnostic judge. The [README results section](../../README.md#results) has the domain split, failure layers and the `pets_allowed` contract gap. [Curated evidence](../fdb3/evidence/final-windows-20261004.json) and the [per-case failure list](../fdb3/evidence/final-windows-20261004-failures.md) are committed.

## Final-source run — 4 October 2026

| Measure | Result | Scope |
|---|---:|---|
| Strict tool pass | **63/100** | All released recordings |
| Spoken answer judged correct / both | **79/100 / 58/100** | All released recordings |
| Tool selection F1 · argument accuracy · response quality | **94.0% · 69.8% · 79.0%** | Upstream printed metrics, 100 turn-taken recordings |
| Infrastructure errors | **0** | 100 completed, evaluated sessions |
| First response · first tool call | **10.15 ± 3.43 s · 5.57 ± 1.63 s** | Upstream latency analyzer with the local judge, N=100 / 97; diagnostic |
| Planner screening | 4B **15/52** vs 9B Q3_K_S **14/52** | 52 hard cases, same local judge; the 4B stays |

The run used Windows 11, an RTX 4050 Laptop 6 GB, a local LiveKit dev room, Windows SAPI TTS, seed 42 and temperature 0. It is local diagnostic evidence, not Samsung's judge or organizer hardware. Clean Linux qualification of `4e88d4b` has not been run; the Linux S2 result below measures `8ef5b59`.

The fresh **3 October 2026 Linux one-command S2 run at source `8ef5b59`** scored **61/100 strict tool passes**, all 100 recordings completed/evaluated, with zero observed infrastructure failures. It is a separate run with its own source, environment, reports and hashes. No score transfers between sources.

The earlier selected benchmark configuration used pinned Whisper `small.en` and Qwen3.5-4B Q4_K_M. Its complete `8dd530f` measurement scored **61/100 strict tool passes**. All 100 released recordings were evaluated, with **zero infrastructure errors**.

## Fresh Linux one-command qualification — 3 October 2026

`full-003` used a clean `git archive` export, a new `THREAD_WORK`, WSL Ubuntu 24.04, CPython 3.11.16, RTX 4050 Laptop 6 GB, Linux espeak-ng and **local Qwen judging**. All four stages (inference, tools, pass rate, latency) exited 0; the script's own verifier has `complete=true`, `judge_verified=true`, `found=completed_inference=evaluated=100`. Overall exit **1** means complete with non-passes. `qualification_eligible=false` remains truthful: this is not Samsung's official judge or organizer-hardware qualification.

| Measure | Fresh Linux result | Denominator / scope |
|---|---:|---|
| Strict tool pass | **61/100 (61%)** | All released recordings |
| Tool selection accuracy (F1) | **87.1%** | Upstream printed metric, 95 turn-taken recordings |
| Argument accuracy | **66.8%** | Upstream printed metric, 95 turn-taken recordings |
| Response quality | **69.5%** | Upstream printed metric, 95 turn-taken recordings |
| No response | **5** | Still included in the strict denominator; no recordings skipped |
| Observed infrastructure failures | **0** | 100 closed sessions; zero recorded session errors; all stage exits 0 |
| Whole-command wall time | **7,046 s (1:57:26)** | 13:26:42–15:24:08 UTC, including environment installation with declared caches |
| Sampled peak GPU / VRAM used | **100% / 5,817 MiB** | Host-wide one-second sampling; minimum reported free VRAM 104 MiB |

The checked tool/pass stages record **329 successful local judge requests**, zero errors. The unchanged latency analyzer made another **95 logical local calls**, analyzed 100 recordings and reported 0 skipped/failed. These latency calls do not have the checked-wrapper per-request receipts. First-response latency is **12.94 ± 4.40 s (N=95)**; tool-call latency **8.11 ± 3.34 s (N=86)**. The reported judge-selected task-completion latency is **12.47 ± 8.16 s (N=95)** but includes **four negative estimates**, minimum -19.76 s; retain it as an unreliable diagnostic timing estimate, not a physical latency claim.

S2 used the permitted, exact-hash September 28 CUDA llama binary. Earlier task preparations downloaded/verified the assets and installed the actual evaluator; the final attempt declared reuse of those task-owned package/model caches, rechecked hashes, created new environments and ran entirely fresh inference. Failed full attempts are preserved and not combined with this score. **INR 0**; no hosted calls, pushes or publication.

See the [S2 qualification report](../fdb3/LINUX_QUALIFICATION_20261003.md) for hardware, commands, repairs, failures, output paths/hashes and test scope; the [curated JSON](../fdb3/evidence/s2-linux-qualification-20261003.json) records the verifier result and aggregates. These are local branch additions, not an update to the previously published release archives.

## Historical Windows runs audited on 30 September 2026

| Run ID | Measured source | Recognition | Strict tool pass | Response quality | Both | Evaluated | Infrastructure errors |
|---|---|---|---:|---:|---:|---:|---:|
| `20260929T123808Z-ff6e52b3` | `771981a` | small.en | 59 | 69 | 55 | 100 | 0 |
| `20260929T144039Z-33e49402` | `771981a` | large-v3-turbo | 64 | 73 | 59 | 100 | 0 |
| `20260929T201004Z-010c0644` | `8dd530f` | small.en | 61 | 77 | 59 | 100 | 0 |

Counts have denominator 100. Strict tool matching, spoken-answer quality and their intersection are separate measures. The judge was **local Qwen3.5-4B**, despite the upstream request alias `gpt-4o`. The records explicitly have `qualification=false`. These are diagnostic results, not organizer scores, and not three fresh 100/100 runs.

The two `771981a` arms have matching source, planner, data, evaluator, dependencies and recorded runtime flags, with different pinned recognizers. The larger recognizer gained seven cases and lost two. The change affects both input recognition and transcription of received output audio for evaluation. This is one paired experiment, not repeated proof of superiority. The final default remains `small.en`; the experimental A/B harness and turbo pins were not promoted.

## Historical 30 September integration boundary

The 30 September integration audit established that participant controller files, the LiveKit bridge, voice/room modules, Windows audio worker and evaluator tools matched the `8dd530f` snapshot at that time. That audit precedes the reproduction repairs and the 3 October search/write-gate changes; it is not a claim that today's runtime hashes still match. The configuration declares seed 42, uses a separately resolved evaluator dependency lock and supports a source archive without Git metadata. Historical runs had no explicit seed. The 61/100 figure remains a source-labelled historical reference, not a fresh final-release result. The separate S2 result above measures the repaired Linux entry point directly.

The final integration adds native history and repairs camera, playback, source-manifest, pinned setup and browser wiring that newer application commits had removed. Fresh release tests are recorded separately in the portable evidence archive. Android Kitchen is tethered to the local host; its client-owned writes and software playback receipts do not prove physical-device acoustics.

See [release verification](VERIFICATION.md) for the executed installation, controller, SDK, client and package checks.

## Historical evidence integrity

All three full runs were audited against 100 recording, result and evaluation hashes apiece, as well as source/evaluator/contract snapshots, actual tool journals, judge receipts and paced local LiveKit WebRTC transport. Failed cases remain in each archive. The release evidence export records original and exported hashes when machine-specific paths are normalized. Raw recordings and original archives remain locally preserved; the release provides source references and audio hashes rather than redistributing the organizer corpus.

| Original report | SHA-256 |
|---|---|
| small.en control | `3d3887d89d3a913229f4dbcfa3f0e64b38da0a1ac201df778e84b2a553122c86` |
| large-v3-turbo experiment | `8f8b5b15b6b27bea9f4b5de188511cb5f04ab5619189c33d3708be5688c52cee` |
| selected small.en path | `25928777585dae2cf687be6e280eb28d6ff462cb8fea010d936a2730aaa87f14` |

## Limits and next engineering work

The official judge snapshot and final normalized score have not been established locally. The **full local WSL Linux/NeMo/GPU execution gate now passed** at `8ef5b59`, but evaluation on the organizer's 48 GB target, a newly built CUDA server, an entirely cache-free final attempt and every CUDA 12/13 toolkit combination remain untested by S2. Historical Linux component evidence stays labelled with its own source, prerequisites and failed attempts. Neither the fresh local score nor regression tests replace the official judging gate.

Remaining failures include recognition, planning/argument selection, spoken-answer quality and tool-window timing. Repairs must target general mechanisms with independent examples. No runtime lookup of benchmark gold answers, case-specific routing, weakened grading, hidden extra calls or cross-scenario result reuse is permitted. The release makes no comparable competitor-victory claim.

Run the [one-command reproduction](../fdb3/REPRODUCE.md) with a fresh output directory to measure changed code. Hosted calls remain disabled under the current ₹0 authorization.
