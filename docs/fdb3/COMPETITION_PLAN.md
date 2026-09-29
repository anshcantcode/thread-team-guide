# Competition-readiness plan (Round 1, Theme 05, FDB-v3)

Written 27 September 2026 from `context.md` (handoff 1.0), the updated organizer
guide summary it records, the pinned upstream `3e799c45`, and sprint-2 evidence
(`docs/fdb3/SPRINT2.md`). Local commits only; nothing is pushed. Budget INR 0.

## What the score depends on

| Round-1 component | Weight | Deciding evidence |
|---|---|---|
| Normalized FDB-v3 benchmark (organizer rerun) | 60% | Correct tool calls/args within the upstream capture window; response quality by the pinned judge; strict pass rate breaks ties |
| Working extension | 20% | Real end-to-end use of the same controller |
| Documentation, architecture, video | 20% | README, one-command reproduction, 3–5 min video, ≤8 slides |

Key fact found in the pinned upstream (`v3/livekit_inference.py`,
`run_tool_benchmark.py`): agent output is captured only for the input
recording's duration, and tool calls are read from the telemetry log right
after inference and ASR. **A correct decision that lands after the window is a
missed call.** Our local runners wait up to 250 s, so they overstate what the
organizer rerun would count. Latency is therefore a correctness problem.

## Chunks, in priority order

### Chunk 1 — Scoring-faithful timing and latency (P0)
1. Upstream-window scoring in the diagnostic and 100-case runner: report
   calls completed inside `stream_start + input_duration` and a window-filtered
   strict pass beside the generous-wait result.
2. GPU offload of the local planner (llama.cpp CUDA build, RTX 4050 6 GB here;
   organizer rerun hardware is a 48 GB GPU). Measure on the same fixtures.
3. Prompt-prefix KV reuse (static system/tool prefix only), measured
   separately; document that no scenario content or result is reused.
4. Prompt size audit; compact only what does not remove the effective request,
   pending corrections, constraints or unresolved effects.

### Chunk 2 — Complete 100-recording public run (P0)
Frozen candidate, fresh output directory, window-faithful and generous metrics,
all 100 accounted (completed/failed/blocked). Public-set exposure disclosed.
Runs in the background from a frozen worktree while other chunks proceed.

### Chunk 3 — Organizer-host portability (P0)
Linux + CUDA one-command reproduction: pinned environment, model/asset manifest
with hashes, llama.cpp server with GPU layers, portable TTS
(`THREAD_FDB3_TTS_COMMAND`), upstream released-data inference, all three
evaluators, nonzero exit on incomplete coverage. A separate WSL environment now
passes preparation and CPU/SDK controls; the full GPU/NeMo/100-case path remains
unverified. Judge failure is checked separately from upstream score totals.

### Chunk 4 — Extension (20%)
Persistent voice checklist through the benchmark controller: natural
correction, exact mutation, persistence after restart, truthful speech.
Fresh015 now verifies the correction, visible native receipt and restart
persistence on named desktop/viewer sources; retain the earlier failures.
Physical-device and broader human-speech evidence remain incomplete.

### Chunk 5 — Submission assets (20%)
README and architecture refresh, ≤8-slide deck, a genuine 3–5 minute demo,
and an AI-disclosure draft for the owner to review and sign. See
`CHECKPOINT_20260928.md` for the current evidence and local checkpoint. The owner
reports a revised 30 September deadline; exact cutoff/form remain placeholders.

### Chunk 6 — Competitor refresh (read-only)
Keel (pre-dispatch gate, reproduction), TriageLine (fragment settling),
Interject-Samsung `integration/livekit-fdb`. Patterns only; no copied code;
no leaderboard claims without matched execution.

## Rules that stay fixed
No gold data or scenario identity in the runtime; no cross-scenario cache;
fresh state per conversation; every run keeps failures; one change per measured
candidate; held-out sets are re-authored once they inform a repair; nothing is
pushed, submitted or signed without the owner.
