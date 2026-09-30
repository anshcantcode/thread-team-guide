# Competitor ideas review — 29 September 2026

Read-only review of public competitor source at pinned commits: Reprise `0672c5d`, Keel `9cc18bb`, TriageLine `9be7806`, Interject `07e71bf` and Aura `a69dfe3`. No competitor code was executed or copied. Interject is MIT-licensed; the others publish no license, so only ideas were used and THREAD's implementation is its own. Nothing here changes grading, tool semantics or evaluator inputs, and nothing reads benchmark answers.

## Adopted

| Idea (credited) | THREAD finding | Change |
|---|---|---|
| Keel: fill declared defaults before taking the idempotency key | Reproduced: while `add_to_cart(B7)` had an unknown outcome, a later proposal `add_to_cart(B7, quantity=1)` (or the reverse) dispatched a second write, because the write key compared raw arguments. Identical arguments were already blocked. | The write ledger key now fills top-level declared defaults (`participant/schema.py` `with_declared_defaults`, used in `participant/agent.py` `_dispatch`). Dispatched arguments are unchanged. Two regressions in `tests/test_participant_controller.py`, including a control that an explicit different value still dispatches. |
| Aura: a shared verb with a different object is not confirmation; REACTOR: an intentional repeat is not a duplicate | Already correct: "book a hotel" does not authorize `book_flight`, "Okay." and a question authorize nothing, and a fresh "add one more" after a successful add dispatches. | Kept as regressions in `tests/test_clause_authority.py`. |

## Already present in THREAD

- **Keel editing-only turns / TriageLine correction cues:** a turn ending on a hold marker ("wait", "hold on", "let me think", "actually") delays planning by 2.0 s (`participant/agent.py` `_HOLD_MARKER`, `hold_seconds`).
- **Keel commit fence / Reprise supersede-before-dispatch:** speech onset raises `blocked_through_revision`; the executor refuses any call from a superseded revision at admission (`thread_agent/fdb3.py` `speech_started`, `_invoke`).
- **TriageLine non-blocking tools:** each tool call runs as its own task (`thread_agent/fdb3.py` `_pump`).
- **JANUS-style postcondition doubt:** an unknown write outcome is reconciled from receipts and never blindly retried.

## Not adopted, with reasons

- **TriageLine's long adaptive settle for "unfinished-looking" text.** The pinned upstream runner records output only for the input recording's duration (`livekit_inference.py`, "Wait until exactly input-duration has elapsed"). Extra end-of-turn waiting risks moving calls outside that window. TriageLine's 91/100 is offline transcript replay, which has no window. Worth testing only as a bounded, measured experiment.
- **Reprise's tool-specific argument rewrites.** Examples: mapping `pet_friendly` to `pets_allowed`, rewriting commute origins to "my house", forcing `driver_license`. `pets_allowed` does not appear in the pinned public tool contract, only in the benchmark data, so such mappings amount to fitting benchmark answers. The organizer guide disqualifies that.
- **Hosted realtime models (Reprise Gemini, Interject Groq, Keel Gemini).** Current spending authorization is zero. The equivalent zero-cost lever is local model size; see below.

## Next measured experiments (need the owner's GPU)

In the run 4 case analysis, the 4B planner and recognition are the two largest failure classes (for example "Seoul" heard as "soil", "euros" as "yours"). The organizer machine has a single 48 GB NVIDIA GPU. Two separate A/B candidates are worth measuring:

1. **Larger recognizer**, for example faster-whisper `medium.en` or a large-v3 variant. Pin repo, revision and per-file SHA-256 in `config/fdb3-candidate.json` → `whisper.models` on a machine that can reach Hugging Face; this cloud container cannot. Compare first on the authored held-out fixtures, then with one full 100-recording run.
2. **Larger local planner GGUF** that fits in 48 GB with the pinned llama.cpp. Update `model.name/url/sha256` and keep `--ctx-size 8192`. Also set an explicit seed, as the organizer guide asks.

Each candidate needs its own frozen source, its own full run with all failures retained, and its own identity. Neither this review nor the fix above has a benchmark measurement yet. The historical 61/100 does not transfer to this changed source.
