# Talent Atlas judging-gate peer audit

- **Checked:** 2026-09-24
- **Peer:** [`pylrn/talent-atlas-realtime-agent`](https://github.com/pylrn/talent-atlas-realtime-agent)
- **Pinned peer commit:** `4874b991f7584c61d436dd03d17e52bf2c06cd6e` (`main`, resolved from both `HEAD` and `refs/heads/main`)
- **THREAD base:** `origin/codex/provider-route-benchmark` at `09f91640dd833cab7efaa387cd52847260802c35`; this clean worktree was fast-forwarded to that commit before the report was added.

## Commands and environment

The peer was cloned with `git clone --depth 1` into a temporary checkout outside the THREAD worktree. The clone had no `.env`. Its `pyproject.toml` supports Python `>=3.10,<3.13`; the gates were run with Python 3.11.9 on Windows in a peer-local virtual environment.

Python 3.11 initially had no project packages installed. The gate import path needs Pydantic, pydantic-settings, asyncpg and pydantic-ai; the configured `.env` source also needs python-dotenv. These packages are declared in the peer's `pyproject.toml`. Only that import-time subset was installed, followed by an editable, no-dependency install so the documented script paths could import `pipeline`:

Resolved direct package versions were Pydantic 2.13.5, pydantic-settings 2.15.0, asyncpg 0.31.0, pydantic-ai-slim 1.107.6, and python-dotenv 1.2.3.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --disable-pip-version-check "pydantic>=2.9.0" "pydantic-settings>=2.5.0" "asyncpg>=0.30.0" "pydantic-ai-slim[groq]>=1.106.0,<2.0" "python-dotenv>=1.0.0"
.\.venv\Scripts\python.exe -m pip install --disable-pip-version-check --no-deps -e .
.\.venv\Scripts\python.exe scripts/benchmark_realtime_interruptions.py
.\.venv\Scripts\python.exe scripts/evaluate_realtime_agent.py
```

The first attempts at the last two commands, before the editable install, both exited 1 with `ModuleNotFoundError: No module named 'pipeline'`. The editable install resolved that packaging/import-path issue. The successful runs used the same two gate commands afterward. Provider API keys, database URLs and Langfuse keys were removed from the gate process environment; no model, database, telemetry or network service was used by either gate.

## What the gates exercise

### `scripts/benchmark_realtime_interruptions.py`

This invokes `InterruptionBenchmark` in `pipeline/realtime_benchmark.py`. The benchmark uses an in-memory fake search engine and deterministic synthetic candidates, then returns scenario checks, selected metrics and a process exit code. It has twelve boolean-pass scenarios:

- fast-path acknowledgement and speculative retrieval start;
- selective cancellation and retention of unchanged slots;
- duplicate call IDs, idempotent writes and superseded writes;
- malformed tool arguments and tool failure;
- a burst of three barge-ins and dropped-transport cleanup;
- grounded final state.

The script prints thirteen headline fields and each scenario's pass/fail checks. The default acknowledgement budget is 250 ms. Its cancellation branch lifecycle uses a virtual clock; the source identifies first-acknowledgement and dropped-transport-close as the two wall-clock measurements. It emits no per-case 0–100 score; exit status is 0 only when all scenario invariants pass.

**Outcome:** exit 0; **12/12 scenarios passed**. Headline output included 3.954 ms first acknowledgement, two invalidated branches (`bm25`, `vector`), 0.0 ms virtual cancellation latency, 120.0 ms virtual work avoided, one changed slot (`city`), one duplicate call detected, zero cancellations from the three-barge-in burst, 0.262 ms dropped-transport close, and one candidate in the closing snapshot.

### `scripts/evaluate_realtime_agent.py`

This is explicitly documented in its module docstring as a deterministic, network-free evaluation. It constructs `RealtimeAgentSession` with `EvaluationEngine` fakes and two synthetic candidates (`c-1`, `c-2`); it does not instantiate the production search engine or call a provider. Its assertions cover initial search, a location revision, cached plan reuse, preserving in-flight retrieval on barge-in, speculative retrieval from a partial transcript, presentation-only formatting, invalid-tool rejection, truthful/ungrounded filler handling, tool blocking classifications, goal replacement/refinement, and selective cancellation of an obsolete vector branch. It prints JSON with one overall `passed` boolean and scenario data, and exits 0/1; it does not compute a participant score.

**Outcome:** exit 0; `passed: true`. The cache-return path made zero additional canonical-engine calls; barge-in preserved in-flight search; speculation started before a tool call and added zero calls when the settled plan matched; malformed arguments were rejected; an unsupported pre-evidence result claim was marked as a violation; and changing goals dropped prior constraints while retaining surfaced candidate context.

## Comparability to the Samsung participant score

**These results are not numerically comparable to a nine-case Samsung participant score.** The Samsung kit has nine public scenarios (six text, two audio and one visual), consumes its event/media protocol and scores participant traces against scenario ground truth. Its scoring contract defines per-scenario checkpoints across task, recovery, latency and safety, then applies modality/difficulty weights and (for final ranking) a transcript-quality multiplier; the sealed-set procedure uses three runs and a median. THREAD's benchmark gates instead exercise internal Talent Atlas lifecycle invariants with fake engines and return Boolean pass/fail data. They do not consume the Samsung cases, raw audio or visual files, Samsung tool manifest, or Samsung scorer, and produce no shared 0–100 scale.

Use the two gates as evidence that Talent Atlas's own simulated interruption/session invariants pass at this commit. They do not establish a Samsung score, a score delta against THREAD, or performance parity. For a direct comparison, the same pinned participant, frozen Samsung kit, official evaluator, configuration and repeat count would have to be used.

## Blockers and limits

- No execution blocker remained after installing the declared import-time subset and editable package in the isolated peer venv.
- The full Talent Atlas runtime requirements were not installed; the tested scripts' exercised paths are the fake-engine gates described above. In particular, these runs do not measure database-backed retrieval, a live Gemini session, real audio recognition, image understanding, UI delivery or factual quality on Samsung cases.
- The two wall-clock figures are one local Windows run and are environment-dependent. The remaining simulated timing checks use deterministic virtual time.
