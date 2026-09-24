# Interject Samsung kit smoke

Checked on 24 September 2026 against [joannamariyajames/interject](https://github.com/joannamariyajames/interject) at detached commit `df269b2dbbabc4dcc74d65f49633e2db685e607f`. The clone's `origin` is `https://github.com/joannamariyajames/interject.git`; `.runtime/competitor-research/` is ignored by the THREAD checkout. The competitor worktree remained clean, and no competitor source or Samsung kit file was changed.

## Public claims

The pinned [README](https://github.com/joannamariyajames/interject/blob/df269b2dbbabc4dcc74d65f49633e2db685e607f/README.md) describes Interject as a Theme 05 Samsung PRISM project. It publishes no Samsung scenario result, aggregate score, or leaderboard placement. It says interruption time-to-yield is typically under 1 ms; the corresponding [runtime test](https://github.com/joannamariyajames/interject/blob/df269b2dbbabc4dcc74d65f49633e2db685e607f/server/tests/test_runtime.py) checks only that the reported value is below 250 ms, and comments that local runs land in single-digit milliseconds. This official-kit smoke does not establish the README's typical-under-1-ms claim. The README also says the project has 19 tests; a prior pinned audit recorded 26 tests passing, as described in [interject-resumption.md](interject-resumption.md).

## Official evaluator attempt

The evaluator was the unchanged THREAD copy at `theme5_kit/participant-kit/participant-kit/eval_submission.py`. Python 3.11.9 was used, within the kit's supported Python range. No dependencies were installed and no credentials were supplied.

From the THREAD repository root, the command was:

```powershell
py -3.11 'theme5_kit\participant-kit\participant-kit\eval_submission.py' '.runtime\competitor-research\interject-df269b2'
```

Result: **failed at Stage 1, package validation** with `missing .runtime\competitor-research\interject-df269b2\submission.yaml` (exit code 1). The pinned repository has no top-level `submission.yaml` or `participant/agent.py`; it is a FastAPI/web application with its runtime under `server/app`. The evaluator therefore did not reach Stage 2 contract smoke or Stage 3 scoring. Its generic “would score 0” invalid-package message is not an observed Samsung scenario score. No Samsung score was produced.

A representative public Samsung scenario was not feasible: Stage 1 rejects the repository before scenarios load, and there is no Samsung `module:Class` entry point implementing the evaluator's queue-based participant contract to exercise. No adapter or source changes were added to manufacture one. This result is a package-compatibility blocker, not evidence of Interject's behavior on any Samsung scenario.
