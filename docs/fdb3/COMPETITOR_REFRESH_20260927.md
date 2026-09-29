# Competitor refresh — 27 September 2026 (read-only)

Method: `git ls-remote` of public refs and reading two pinned source files.
No competitor code was executed or copied; no ranking is implied.

## Refs versus the 1.0 handoff snapshot

| Repository | Heads now | Change since handoff |
|---|---|---|
| PROSTLE/samsung (Keel) | main `8c6ef4c0bb66` | none |
| RomitDeokar/TriageLine | main `7a81d763ed21` | none |
| MridulNegi2005/AccessFlow | main `116b3159e6a9`, engine `353fe9827384`, perception `e04f943c30e6` | none |
| pylrn/talent-atlas-realtime-agent | main `4874b991f758`, dev `1f53ba02297a` | none |
| xan-antx/aura-samsung | main `a69dfe34022a`; fullstack-visualizer `36e3f674b94b`, genai-scenarios `c2ff74aff915`, ml-perception `bd5e300bbee4` | main unchanged; branch heads not recorded in the handoff |
| joannamariyajames/interjectsamsung | integration/livekit-fdb `53e7bf10140f`, main `eb5f4f7c8f36` | none |

## Patterns reviewed

**Keel gate** (`keel/livekit/gate.py@8c6ef4c`): hold dispatch until the turn
ends and a quiet interval passes; drop undispatched calls when new speech
arrives; one execution per (session, tool, arguments). THREAD already blocks
dispatch at speech onset, re-checks admission at the executor boundary, and
deduplicates identical calls within a request. Nothing to adopt.

**TriageLine adapter** (`livekit_agent/adapter.py@7a81d76`): adaptive settling —
commit a final quickly when the running transcript already plans to a complete
call, wait longer when it looks unfinished or required arguments are missing.
THREAD uses fixed SDK endpointing (0.8 s min, 5 s max). With post-speech
windows of 2–11 s in the released recordings, an adaptive commit is a candidate
latency improvement. It must be implemented independently and measured as its
own candidate; its public-set-tuned rules are not evidence of generalization.

## Later update (owner's research, 27 September; not independently executed here)

* **Keel (PROSTLE/samsung)**, main `9cc18bb`: a team-published full
  100-recording Gemini Live run (commit `e14fe3b`, run
  `20260927T083931Z_keel_gemini_realtime`) reports 43/100 strict, tool
  selection 0.942, argument accuracy 0.581, median tool latency 3.09 s, using
  `--latency instant --judge none` (exact-match arguments, no LLM judge) and a
  source identity `8c6ef4c` *with uncommitted changes*. Its run artifacts are
  public. Keel also added a fence that waits for correction words still being
  transcribed; THREAD's hold-marker fence (`134abb3`) addresses the same
  failure from the controller side.
* **InterjectSamsung** `integration/livekit-fdb` at `491b970`: an FDB-v3
  adapter and LiveKit lifecycle fixes; its checked test feeds dialogue text,
  not a 100-recording voice run.
* AccessFlow, TriageLine, Aura, Talent Atlas: no comparable new result.

**Comparability.** THREAD's local runs use a local Qwen judge and loopback
LiveKit; Keel's uses no judge and a hosted realtime model. Neither is an
organizer result, and "43 vs 39/40" is not a like-for-like ranking.

## 28 September 2026 refresh

Scope: The implementation reviewer’s owner-supplied 28 September public-cohort check, supplemented
here by read-only retrieval of pinned Keel and TriageLine READMEs and the
FDB-v3 paper. No competitor code, model or benchmark was executed for task D.
No Git remotes were contacted. This is not an exhaustive entrant inventory.
Source hashes and verification limits are in
[`evidence/task-d-docs-20260928.json`](evidence/task-d-docs-20260928.json).

| Evidence | Snapshot and run | Result with full denominator | Judge and limits |
|---|---|---|---|
| THREAD run #3 | Frozen `f6329dd`; `20260928T033707Z-18db0ad9`; recorded at `eb6bdb3` | 53/100 strict and window-strict, 47 non-passes; 100 evaluated; 0 paid requests | Local Qwen3.5-4B; one diagnostic, not an organizer score |
| THREAD exact rescore | Same run and saved inference | 45/100, 55 non-passes | No judge; rescoring, not fresh inference |
| THREAD prior best | `088cf6f`; `20260927T175531Z-6dcc34fa` | 50/100 strict, 42/100 exact | Local Qwen / no-judge modes respectively; retained historical result |
| Keel, author-reported | `PROSTLE/samsung` main snapshot `9cc18bb`; `20260927T083931Z_keel_gemini_realtime`; reported run source `8c6ef4c` with uncommitted changes | 43/100 strict, 57 non-passes; full 100-recording Gemini Live run | No judge, exact-match arguments; dirty source and different runtime; not rerun by THREAD |
| FDB-v3 paper, GPT-Realtime | arXiv `2604.04847v1`, Table 2 | Pass@1 0.600 on the paper's full 100 recordings | Paper's GPT-4o judging; published baseline, not a Samsung rerun |
| FDB-v3 paper, Gemini Live 3.1 | Same paper and table | Pass@1 0.540 on the paper's full 100 recordings | Paper's GPT-4o judging; separate model/configuration, not a Samsung rerun |

Keel is the **only repository in The implementation reviewer’s reviewed cohort with a published
full FDB-v3 run**. Its authors attribute 20 of 34 argument failures to form
differences and report 16 recordings with no response. These are their
diagnoses, not waived failures or a projected judged score. All 57 failures
remain in its denominator.
Source: [Keel README at `9cc18bb`](https://github.com/PROSTLE/samsung/blob/9cc18bb/README.md#L168),
run `20260927T083931Z_keel_gemini_realtime`.

The paper baselines above use judged scoring, unlike Keel's run and THREAD's
exact rescore. Source: [FDB-v3 paper, experimental setup and Table 2](https://arxiv.org/html/2604.04847v1),
also shown on the [authors' results page](https://daniellin94144.github.io/FDB-v3-demo/#results).

The implementation reviewer’s 28 September check found **no published FDB-v3 run** for AccessFlow,
TriageLine, Aura, interject, interjectsamsung, Talent Atlas, Pivot, REACTOR,
CHRONOS, BargeIn or `itsramhere/samsung_prism`. This is a dated source-review
finding, not evidence of zero performance. TriageLine explicitly labels its
89.1/100 result as its own nine-scenario practice harness, **"Not FDB-v3"**;
the FDB-v3 live run is marked not run in the
[README at `7a81d76`](https://github.com/RomitDeokar/TriageLine/blob/7a81d763ed21/README.md).
This task rechecked that distinction, not every branch of every repository.

**No like-for-like ranking follows.** A common no-judge metric makes 45/100
and 43/100 useful context, but different source states, runtimes and unmeasured
run variance prevent a demonstrated lead. THREAD's 53/100 local-Qwen result
must not be ranked against Keel's 43/100 exact result or the paper's judged
baselines. None is an organizer result, and untested entrants remain unranked.
THREAD run #4 on candidate `18ad4ea` is **PENDING, result unknown here**;
task C's later natural-answer changes are also unmeasured.
