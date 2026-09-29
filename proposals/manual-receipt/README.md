# Pending answer-preservation repair

This directory preserves a completed development proposal. It is **not integrated**
into the active `participant/` package.

The repair keeps the substantive manual answer alongside its evidence receipt,
and preserves explicitly requested metadata without replacing that answer.
Its own recorded checks passed 82 scoped tests. Those results do not establish a
pass on the current integrated runtime or the complete public kit.

- `baseline/agent.py` is the exact source against which the patch was prepared.
- `candidate/agent.py` is the proposed replacement source.
- `candidate/test_participant_cited_answer.py` contains its regression checks.

Compare the baseline with the current participant before applying the patch;
do not overwrite later source changes. After integration, run the relevant
regressions and the complete package checks, recording fresh results. Original
development logs remain in the local archive.
