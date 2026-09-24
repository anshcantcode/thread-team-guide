# Interject checkpoint and goal-switch audit

## Pinned source

Peer repository: [joannamariyajames/interject](https://github.com/joannamariyajames/interject). On 2026-09-24, `git ls-remote` reported `main`/`HEAD` at **`df269b2dbbabc4dcc74d65f49633e2db685e607f`**. The isolated clone was checked out detached at that full commit before inspection or test setup. All source links below point to that pin.

This report is based on THREAD branch `codex/interject-resumption-audit`, created from `origin/codex/provider-route-benchmark` at **`09f91640dd833cab7efaa387cd52847260802c35`**.

## Reproduction

The peer [README](https://github.com/joannamariyajames/interject/blob/df269b2dbbabc4dcc74d65f49633e2db685e607f/README.md#L154) documents `make test`. Its [Makefile](https://github.com/joannamariyajames/interject/blob/df269b2dbbabc4dcc74d65f49633e2db685e607f/Makefile) runs `cd server && ./.venv/bin/python -m pytest tests -q`. On this Windows host, GNU Make was unavailable, so the literal `make test` stopped with “The term 'make' is not recognized”. I ran the same Python 3.11 pytest target with the Windows venv executable instead.

The clone was public and detached, with system Git configuration and terminal prompts disabled and the credential helper cleared:

```powershell
$env:GIT_TERMINAL_PROMPT = '0'
$env:GIT_CONFIG_NOSYSTEM = '1'
$peer = Join-Path $env:TEMP 'interject-peer-audit-df2692db'
git -c credential.helper= clone --no-checkout https://github.com/joannamariyajames/interject.git $peer
git -C $peer switch --detach df269b2dbbabc4dcc74d65f49633e2db685e607f
```

From that clone's `server` directory, I installed the peer's pinned development requirements and ran its full test target with the model credential explicitly empty:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --disable-pip-version-check --no-input --index-url https://pypi.org/simple -r requirements-dev.txt
$env:LLM_API_KEY = ''
.\.venv\Scripts\python.exe -m pytest tests -q
```

Result: **26 passed in 60.55s**. Dependency installation used public PyPI; test execution used the local deterministic provider and made no model-service calls. `LLM_API_KEY` is the switch used by the peer's [configuration](https://github.com/joannamariyajames/interject/blob/df269b2dbbabc4dcc74d65f49633e2db685e607f/server/app/config.py#L81) and [provider factory](https://github.com/joannamariyajames/interject/blob/df269b2dbbabc4dcc74d65f49633e2db685e607f/server/app/providers/__init__.py) to select the remote provider; it was empty for the test run. No THREAD credentials were used.

The passing suite includes these published behaviors:

- `test_barge_in_stops_mid_answer_and_keeps_the_work`: interruption stops token output and leaves a checkpoint.
- `test_continuing_after_an_interrupt_resumes_instead_of_restarting`: “go on” reuses the checkpoint.
- `test_a_goal_switch_after_an_interrupt_parks_instead_of_resuming`: a new goal is switched to and the interrupted answer is not resumed.
- `test_explicit_switch_parks_rather_than_drops_the_goal` and `test_revert_resumes_the_parked_goal_with_its_constraints`: a parked goal remains available with its constraints.

These tests are in the pinned [runtime tests](https://github.com/joannamariyajames/interject/blob/df269b2dbbabc4dcc74d65f49633e2db685e607f/server/tests/test_runtime.py) and [goal tracker tests](https://github.com/joannamariyajames/interject/blob/df269b2dbbabc4dcc74d65f49633e2db685e607f/server/tests/test_goals.py). The README says the test suite contains 19 tests, while pytest discovers and passes 26 at this commit.

## Voice and audio boundary

The backend tests drive `AgentRuntime` with text utterances and explicit interrupt calls. The default [MockProvider](https://github.com/joannamariyajames/interject/blob/df269b2dbbabc4dcc74d65f49633e2db685e607f/server/app/providers/mock.py) streams deterministic text tokens, so these results cover transcript-driven interruption and checkpoint logic, not microphone latency or acoustic interruption.

The browser's [voice replay](https://github.com/joannamariyajames/interject/blob/df269b2dbbabc4dcc74d65f49633e2db685e607f/web/src/lib/voice.ts) fetches canned transcripts from `/api/transcripts`, adds their words to the draft one at a time, then submits the completed text with voice modality. The draft path sends partial text frames through the [session store](https://github.com/joannamariyajames/interject/blob/df269b2dbbabc4dcc74d65f49633e2db685e607f/web/src/store/session.ts). No `getUserMedia`, `MediaRecorder`, `SpeechRecognition`, or `speechSynthesis` path was found under `web/src` at this commit. Real microphone capture, speech recognition, and speech synthesis are outside the tested behavior.
