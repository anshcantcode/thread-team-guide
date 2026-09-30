# Results and reproducibility

THREAD's selected benchmark configuration uses pinned Whisper `small.en` and Qwen3.5-4B Q4_K_M. The latest complete measurement of that execution path scored **61/100 strict tool passes**. All 100 released recordings were evaluated, with **zero infrastructure errors**.

## Complete local runs audited on 30 September 2026

| Run ID | Measured source | Recognition | Strict tool pass | Response quality | Both | Evaluated | Infrastructure errors |
|---|---|---|---:|---:|---:|---:|---:|
| `20260929T123808Z-ff6e52b3` | `771981a` | small.en | 59 | 69 | 55 | 100 | 0 |
| `20260929T144039Z-33e49402` | `771981a` | large-v3-turbo | 64 | 73 | 59 | 100 | 0 |
| `20260929T201004Z-010c0644` | `8dd530f` | small.en | 61 | 77 | 59 | 100 | 0 |

Counts have denominator 100. Strict tool matching, spoken-answer quality and their intersection are separate measures. The judge was **local Qwen3.5-4B**, despite the upstream request alias `gpt-4o`. The records explicitly have `qualification=false`. These are diagnostic results, not organizer scores, and not three fresh 100/100 runs.

The two `771981a` arms have matching source, planner, data, evaluator, dependencies and recorded runtime flags, with different pinned recognizers. The larger recognizer gained seven cases and lost two. The change affects both input recognition and transcription of received output audio for evaluation. This is one paired experiment, not repeated proof of superiority. The final default remains `small.en`; the experimental A/B harness and turbo pins were not promoted.

## What the final code shares with the measured source

The integration audit established that participant controller files, the LiveKit bridge, voice/room modules, Windows audio worker and evaluator tools matched the `8dd530f` snapshot. That audit precedes the final reproduction repairs. The release now declares seed 42, uses a separately resolved evaluator dependency lock and supports a source archive without Git metadata. Historical runs had no explicit seed. These are deliberate configuration/setup changes, so the 61/100 figure remains a source-labelled historical reference, not a fresh final-release result.

The final integration adds native history and repairs camera, playback, source-manifest, pinned setup and browser wiring that newer application commits had removed. Fresh release tests are recorded separately in the portable evidence archive. Android Kitchen is tethered to the local host; its client-owned writes and software playback receipts do not prove physical-device acoustics.

See [release verification](VERIFICATION.md) for the executed installation, controller, SDK, client and package checks.

## Evidence integrity

All three full runs were audited against 100 recording, result and evaluation hashes apiece, as well as source/evaluator/contract snapshots, actual tool journals, judge receipts and paced local LiveKit WebRTC transport. Failed cases remain in each archive. The release evidence export records original and exported hashes when machine-specific paths are normalized. Raw recordings and original archives remain locally preserved; the release provides source references and audio hashes rather than redistributing the organizer corpus.

| Original report | SHA-256 |
|---|---|
| small.en control | `3d3887d89d3a913229f4dbcfa3f0e64b38da0a1ac201df778e84b2a553122c86` |
| large-v3-turbo experiment | `8f8b5b15b6b27bea9f4b5de188511cb5f04ab5619189c33d3708be5688c52cee` |
| selected small.en path | `25928777585dae2cf687be6e280eb28d6ff462cb8fea010d936a2730aaa87f14` |

## Limits and next engineering work

The official judge snapshot and final normalized score have not been established locally. Complete independent Linux/NeMo/GPU evaluation on the organizer's target remains unqualified. Historical Linux component evidence is labelled with its own source, prerequisites and failed attempts. Local regression tests do not replace these gates.

Remaining failures include recognition, planning/argument selection, spoken-answer quality and tool-window timing. Repairs must target general mechanisms with independent examples. No runtime lookup of benchmark gold answers, case-specific routing, weakened grading, hidden extra calls or cross-scenario result reuse is permitted. The release makes no comparable competitor-victory claim.

Run the [one-command reproduction](../fdb3/REPRODUCE.md) with a fresh output directory to measure changed code. Hosted calls remain disabled under the current ₹0 authorization.
