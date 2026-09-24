# Unseen-tool outlier: reproduction gap

Reviewed from `origin/codex/provider-route-benchmark` at `09f91640dd833cab7efaa387cd52847260802c35`.

## Finding

I could not reproduce a generic tool-schema or result-binding defect offline. The official `pub_09_text_unseen_tool` manifest uses the documented descriptor shape: a required string argument and an optional string enum. `ParticipantAgent._dispatch` resolves the tool from the runtime manifest and validates those arguments without a tool-name allowlist.

The focused regression in `tests/test_participant_general_function.py` renames the unseen tools, dispatches through their manifest schemas, selects one returned row, binds an argument to its returned field, and grounds the final response in the second result. It passes with the current implementation. Focused tests passed: 86 tests across `test_participant_general_function.py` and `test_participant_controller.py`.

## Evidence gap

`docs/benchmarks/gemini-public-2026-09-24-3x.json` records the three `pub_09` totals as `47.7, 100, 100`, but omits the per-repeat event trace, accepted planner decision, and rejection reason. The two successful repeats and the renamed offline check do not identify what happened in the low-scoring run. It could not be tied to schema validation, result binding, or any other deterministic participant behavior from the available artifact.

No production change was made. A per-repeat trace for the 47.7 run, including the planner decision and emitted actions, is needed to identify a fixable participant defect.
