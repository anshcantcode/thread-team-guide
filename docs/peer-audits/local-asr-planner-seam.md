# Local ASR seam in the participant planner

## Recommendation

Add local ASR as an explicit, default-off implementation of the existing independent acoustic pass. Keep MAIN's Gemini request attached to the original audio bytes. The local transcript should enter as a separate, source-bound audio observation and pass through the current agreement and uncertainty gates. Do not turn it into a synthetic user speech message.

This is the narrowest opt-in: it replaces only the acoustic provider for configured runs. With the option unset, `audio_mode='independent'` and the current two-Gemini-request behavior remain unchanged ([planner initialization](../../participant/planner.py#L825), [setup defaults](../../participant/planner.py#L892)).

## Existing flow and seam

`MediaLoader.prepare` resolves each reference under the media root, reads and validates the raw file, preserves audio order, hashes the bytes, and then encodes those same bytes into Gemini's inline media parts. Its returned provenance includes message index, byte count, MIME type, and SHA-256, but the raw audio bytes are discarded after encoding ([media preparation](../../participant/media.py#L195)).

In the default independent mode, `_generate` starts `_current_audio` and `_decide` concurrently. `_current_audio` sends the current clips to `_perceive_audio`; `_decide` sends the native audio parts to MAIN. After both finish, the planner compares transcripts and makes disagreement or uncertainty a clarification with no tool calls ([parallel start](../../participant/planner.py#L1192), [agreement and veto](../../participant/planner.py#L1241)).

The source identity already has the right core fields: `_audio_key` is `(message_index, message_revision, MIME type, SHA-256)`. `_current_audio` owns one turn job, checks the ordered source keys on join, and `_stop_audio_jobs` removes eligibility before cancelling work ([source key and cancellation](../../participant/planner.py#L1033), [turn job](../../participant/planner.py#L1058)). Reuse that identity; do not bind ASR to a path or message index alone.

The smallest media change is an opt-in way for `prepare` to hand its already-validated raw audio bytes and provenance to the planner while preserving the existing three-value return for default callers. Capture the bytes at the point where `_read` returns them, calculate the same digest used in `input_media`, and pass the exact byte object to the local engine. Do not reread the path for ASR, decode the provider's base64 part, or retain bytes in planner evidence/log records.

## Admission and lifecycle

- Gate engine construction/use behind a separate explicit local-ASR setting, default off. Leave `PARTICIPANT_AUDIO_MODE` and provider selection alone. Missing model/runtime, unsupported audio, or local-ASR error must produce a clarification for that opted-in run; it must not silently switch provider or weaken the default Gemini route.
- Give each job an immutable epoch `(planner revision, current_turn_start, ordered source keys)`. Each returned observation must identify exactly one submitted message and match its key. Before returning it or caching it, check the planner is open, the epoch/job is still current, the turn has not been stopped, and the current prepared source keys still match. A new revision, changed bytes, missing/duplicate row, timeout, or cancellation retires the result.
- Use the planner's existing shared start time and outer deadline. Local work must not reset a deadline on replan. A thread-backed decoder can continue after asyncio cancellation, so cancellation alone is not the acceptance check: discard its eventual result unless the epoch and job identity still match. Cache only completed, validated results under their full source key, preserve their uncertainty bit, and never treat an uncertain result as clear corroboration.
- Preserve a monotonic uncertainty veto: local uncertainty, MAIN uncertainty, an absent/incomplete transcript, or a material disagreement means no tool call and no clear cache promotion. Expose the local engine through the same observation shape `{message_index, type:'audio', transcript, uncertain}`. Do not treat raw ASR word scores as calibrated confidence; if confidence is used to set `uncertain`, its threshold needs evaluation against the target clips.

## 5.5-second assessment

Replacing MAIN's native audio with source-bound text is not required to try to meet 5.5 seconds. The independent acoustic job already runs beside MAIN, so a warm local pass can replace the separate remote acoustic request while MAIN continues to plan from the exact validated audio. The turn then remains bounded by the slower of MAIN and local ASR, under the existing planner deadline (`timeout` defaults to 4.5 seconds and is configurable up to 5.5; acoustic work currently has a 3.5-second subdeadline: [budgets](../../participant/planner.py#L831), [setup validation](../../participant/planner.py#L899), [acoustic deadline](../../participant/planner.py#L1389)). This is a latency opportunity, not a guarantee that MAIN completes in budget.

A previous local feasibility run for faster-whisper large-v3-turbo reported about 0.4–0.46 seconds per clip after warm-up and a 6.529-second model load (`codex/local-whisper-feasibility:docs/peer-audits/local-whisper-feasibility.md`). That was one warm pass per clip, not a stable end-to-end or quality result. Therefore the model must already be loaded before a timed turn, and the full planner path still needs measurement. Replacing MAIN audio with ASR text would remove the independent native-audio perception and could make the planner treat an ASR error as user authority; it is not the first seam to test.

## Tests that would protect the seam

Extend the existing participant audio tests rather than testing only the adapter in isolation:

- **Exact-byte binding:** alongside `test_exact_bytes_order_and_latest_frame_without_reference_text` in [test_participant_media.py](../../tests/test_participant_media.py#L40), assert the opt-in ASR receives the validated bytes whose SHA-256 appears in `input_media`, in message order. Changing the file bytes at the same reference must create a different source key and must not reuse the old transcript.
- **Mismatch veto:** alongside `test_conflicting_clear_transcripts_cannot_authorize_the_main_plan_or_future_history` in [test_participant_planner.py](../../tests/test_participant_planner.py#L1125), make fake local ASR return a materially different transcript from MAIN while MAIN proposes a write. Expect a clarification, no tool calls, the local source transcript marked uncertain, and no clear cache entry. Include a local `uncertain=true` case even when MAIN is clear.
- **Late completion:** alongside `test_new_text_or_wordless_interruption_evicts_late_swallowed_completion` and `test_changed_bytes_or_message_identity_cannot_reuse_a_completed_turn_job` in [test_participant_audio_staging.py](../../tests/test_participant_audio_staging.py#L361), block the local worker, supersede/cancel/close or change the bytes/revision, then release it. Assert its late result cannot populate the cache, authorize a call, or be attached to the newer turn.
- **Default-route regression:** with local ASR unset, assert the engine is never constructed/called and MAIN/acoustic requests still receive the same native audio MIME/data parts. With opt-in set, only the acoustic provider changes; MAIN's native audio bytes remain identical.
