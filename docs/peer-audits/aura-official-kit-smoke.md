# AURA official-kit smoke

Checked 24 September 2026 against [`xan-antx/aura-samsung`](https://github.com/xan-antx/aura-samsung) at detached commit [`6b277a2e2e63f43459d4b264b4597012d701b162`](https://github.com/xan-antx/aura-samsung/tree/6b277a2e2e63f43459d4b264b4597012d701b162). The clone is at the ignored `.runtime/aura-samsung/` path; its `origin` is the requested repository and its working tree is clean. No competitor source, THREAD kit, or evaluator was edited.

The repository identifies itself as a Samsung PRISM GenAI Hackathon 2026 Theme 05 project for team `Thapar_Aura`. Its README describes an author-built deterministic harness and says its scorer is based on the author's reading of the rubric, **not Samsung's scorer**. The README's 40/35/15/10 category weights match the public kit's [SCORING.md](../../theme5_kit/participant-kit/participant-kit/docs/SCORING.md). I found no reported aggregate official score in the checked project documentation. The `100.0` values in `harness.py` are local self-check assertions, not an official-kit result.

## Official package validation

Environment: Windows `10.0.26200.0`, Python `3.13.5`, Git `2.49.0.windows.1`. The evaluator used was THREAD's unchanged [`eval_submission.py`](../../theme5_kit/participant-kit/participant-kit/eval_submission.py), SHA-256 `37C1B3EC9BFDEB5525D2625EE3B2131EF9A41ACF3D8844ED2A208EC99DCC3504`.

Exact command, run from the THREAD repository root:

```powershell
python .\theme5_kit\participant-kit\participant-kit\eval_submission.py .\.runtime\aura-samsung --reps 1 --time-scale 8
```

Result: **failed at Stage 1, package validation** (process exit 1): `missing .\.runtime\aura-samsung\submission.yaml`. Stage 2 contract smoke and Stage 3 scenario evaluation did not run; there is no score. No API credentials were read or passed. I did not run a public scenario because the package is rejected before the contract is reached.

The immediate blocker is the missing root `submission.yaml` required by the [public submission contract](../../theme5_kit/participant-kit/participant-kit/docs/SUBMISSION.md). The source also is not a direct participant package as checked: `agent.Agent` accepts a manifest and exposes synchronous `handle(event, now)`, while the kit requires a class constructible with input/output queues and an async `run()` method. The AURA README itself describes writing an adapter for that queue contract. No adapter or package files were added for this audit.

**Outcome:** repository identity and source commit verified; public category-weight claim corroborated; no official score established; official package validation failed on the missing manifest, so the contract and representative scenario remain untested.
