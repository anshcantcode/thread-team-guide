# Talent Atlas official-kit package smoke

Checked 24 September 2026 against [`pylrn/talent-atlas-realtime-agent`](https://github.com/pylrn/talent-atlas-realtime-agent) at `4874b991f7584c61d436dd03d17e52bf2c06cd6e` (`Update README.md`). The clone's `origin` is `https://github.com/pylrn/talent-atlas-realtime-agent.git`, and `git rev-parse HEAD` returned that full SHA. It lives at `.runtime/competitor-research/talent-atlas-4874b99`; `git check-ignore -v` confirmed the THREAD `.runtime/` ignore rule, and the peer checkout had no tracked changes after the runs. No peer source or THREAD kit file was edited.

## Published claims

The [technical overview](https://github.com/pylrn/talent-atlas-realtime-agent/blob/4874b991f7584c61d436dd03d17e52bf2c06cd6e/docs/hackathon/TECHNICAL_OVERVIEW.md) and [12-slide presentation](https://github.com/pylrn/talent-atlas-realtime-agent/blob/4874b991f7584c61d436dd03d17e52bf2c06cd6e/docs/hackathon/submission/Talent_Atlas_PRISM_Y2026_Presentation.pptx) claim **12/12 interruption scenarios passed**. The README documents the gates; both documented deterministic scripts below reproduced successfully.

The README also says **674 tests passed**, while the technical overview says **670 tests pass on Python 3.11.12**. This pinned public tree has no tracked unit-test directory or unit-test files (the tracked test-named Python files are load/smoke scripts), so neither test-count claim could be reproduced from this checkout. No Samsung nine-case, weighted, or other 0–100 participant score was found in the inspected public README, docs, scripts, or presentation.

## Environment and commands

Windows; Python 3.11.9; no provider credentials were needed. The two peer gates use fake engines and deterministic local inputs. A peer-local virtual environment used Pydantic 2.13.5, pydantic-settings 2.15.0, asyncpg 0.31.0, pydantic-ai-slim 1.107.6, and python-dotenv 1.2.3, followed by an editable `--no-deps` install for the documented script import path.

From the peer repository root:

```powershell
.\.venv\Scripts\python.exe scripts/benchmark_realtime_interruptions.py
.\.venv\Scripts\python.exe scripts/evaluate_realtime_agent.py
```

The interruption benchmark exited 0 with **12/12 scenarios passed**. It reported 1.535 ms first acknowledgement and 0.199 ms dropped-transport close in this local run; these two wall-clock readings are environment-dependent, while its cancellation lifecycle uses virtual time. The session evaluation exited 0 and returned `"passed": true` using its documented fake `EvaluationEngine`.

The untouched THREAD evaluator was [the kit's `eval_submission.py`](../../theme5_kit/participant-kit/participant-kit/eval_submission.py), SHA-256 `37C1B3EC9BFDEB5525D2625EE3B2131EF9A41ACF3D8844ED2A208EC99DCC3504`; `git diff --exit-code HEAD --` confirmed no edit. With Python 3.11.9, the exact invocation was:

```powershell
& $py311 $kit\eval_submission.py $peer --reps 1
```

Here `$py311` was `C:\Users\ANSH\AppData\Local\Programs\Python\Python311\python.exe`, `$kit` was `theme5_kit\participant-kit\participant-kit`, and `$peer` was `.runtime\competitor-research\talent-atlas-4874b99`. It exited 1 at **stage 1 package validation** with `missing ...\talent-atlas-4874b99\submission.yaml`. The evaluator did not import or run the peer.

## Comparability and blocker

The public repo is a FastAPI recruiting application (`api/`, `pipeline/`, `db/`, `scripts/`), not a Samsung participant package: its root has no `submission.yaml` or `agent/agent.py` implementing `ParticipantAgent`. Because validation stops before the participant contract, no official contract smoke or Samsung scenario was feasible; no public scenario was run. The reproducible **12/12** is Talent Atlas's own synthetic interruption benchmark, not a Samsung score and not numerically comparable to the kit's nine public cases.
