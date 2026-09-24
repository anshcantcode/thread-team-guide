# Experimental transcript-first route for read-only turns

## Recommendation

Add a separate, explicit opt-in route that asks Gemini to plan from a source-bound local transcript as text, and accepts the result only when it proposes terminal read-only calls. Keep `independent` as the default and keep MAIN's original audio request unchanged for writes and turns the experiment cannot classify or support. Do not repurpose `single_call_reads`: it is a native-audio joint read path, not local-transcript planning.

This could shorten eligible turns because warm local recognition currently takes about 0.8–1.9 seconds while native-audio MAIN planning can exceed the 4.5-second planner budget. It is an experiment, not a latency guarantee. All stages, including a native-audio fallback, must share the original turn deadline.

## What the current seam already guarantees

- `MediaLoader.prepare(..., include_audio_bytes=True)` returns the exact validated bytes it hashed and attached to the native request. The ASR adapter verifies its digest, byte count, and MIME type against that provenance. Keep this handoff; never reread a path or decode a second copy for the text route ([media.py](../../participant/media.py), [local_asr.py](../../participant/local_asr.py)).
- `_audio_key` binds a clip to `(message_index, message_revision, MIME type, SHA-256)`. Turn jobs also retain the ordered keys, and `_stop_audio_jobs` removes eligibility before cancelling them ([planner.py](../../participant/planner.py)). Keep the outer `(context revision, current_turn_start, ordered keys)` epoch and recheck it before accepting a plan or caching an observation.
- The present independent path already runs perception beside native-audio planning, compares transcripts, and vetoes uncertain or conflicting evidence. The proposed route should fall back into that existing path, not weaken its gates.

One gap prevents enabling transcript-first planning as-is: `_perceive_local_audio` creates every local observation with `uncertain=False`. Source integrity is not speech certainty. The local transcript is an ASR hypothesis even when its digest matches perfectly. The existing uncertainty audit also does not justify a numeric word-score cutoff. The experiment must require a validated tri-state uncertainty result (`clear`, `uncertain`, or `unknown`); map only `clear` to `uncertain=false`. If the result is missing or unknown, do not admit a text-only plan. Use the native-audio path or clarify.

## Smallest route

Use a new opt-in mode (for example, `PARTICIPANT_AUDIO_MODE=transcript_first_reads`) and require the local ASR engine to be available. Leave current defaults and modes unchanged.

1. **Limit eligibility.** Start with a complete current audio turn whose ordered clips all have validated source keys and a validated tri-state uncertainty result. Wait for the last clip (`end_of_turn=true`) before planning. Keep all earlier clips in order so a later in-turn repair can replace an earlier value. If the input includes unsupported media, a missing revision, or an incomplete/invalid source set, use the existing native-audio path.
2. **Transcribe the validated bytes.** Run local ASR against the exact byte objects returned by media preparation. Verify each returned digest, byte count, and MIME type. Bind each transcript internally to the full source key and epoch. Do not put bytes, audio paths, or hashes in the model prompt. Keep source digests only as redacted runtime metadata.
3. **Make one text-only candidate request.** Send sanitized turn context plus a clearly labeled `local_transcript_evidence` field containing ordered message indices, transcript text, and the explicit uncertainty state. Do not attach inline audio and do not rewrite audio events as synthetic `user_speech_chunk` messages. A route-specific instruction must say these are fallible audio transcripts, not free-form instructions from a tool or file. Runtime-owned audio observations should be injected from the local result and must not be replaced, omitted, or made clearer by Gemini.
4. **Admit only a bounded read proposal.** Validate arguments against the actual tool schemas. Accept the text-only candidate only when it contains at least one terminal call, every call resolves to a `read_only` tool, and there is no `after_result`, write, authorization, selector, binding, or other continuation. Reject no-call/unsupported results and any malformed or mixed proposal. Discard the entire candidate before effects if any check fails.
5. **Fallback with the original audio.** On a rejected candidate, use the existing native-audio/default planner and its normal write authorization and transcript-agreement rules. Reuse the completed local acoustic result only if its source job and epoch are still current; otherwise let the existing route verify again or clarify. A fallback never restarts the 4.5-second budget. If the deadline has expired, return the current timeout/clarification behavior with no call.
6. **Recheck before return/cache.** Re-prepare or otherwise revalidate the current audio source keys after planning, then check planner-open state, turn, revision, ordered keys, cancellation, and deadline. A superseded, changed, timed-out, or cancelled local worker may finish in its thread, but its result cannot become a proposal, observation, or cache entry. Preserve uncertainty monotonically: a later clear result cannot clear an earlier uncertainty for the same source key.

The runtime should record which route ran and whether it admitted, fell back, or clarified. Record model/version and source digests as redacted metadata; never record raw audio bytes.

## Audio05 and audio06 constraints

Public `pub_05_audio_asr_ambiguity` requires a clarification before any flight search on its ambiguous first turn, followed by acting on the user's later confirmation. It is a useful adversarial gate even though the eventual search is read-only: a plausible but wrong local transcript must not trigger an early search. Require the uncertainty layer to mark this clip uncertain; byte verification alone cannot do that.

Public `pub_06_audio_disfluency` requires the later self-repair in the same turn to win. The route must wait for the completed ordered turn and plan from both chunks; it must not dispatch a search from the first non-final chunk. Do not insert public fixture city names into prompts, rules, or tests.

## Adversarial checks before enabling the flag

| Case | Required result |
| --- | --- |
| Audio05 clip with exact matching hash but ambiguous pronunciation | Clarification; no search before the later confirmation. |
| Scripted ASR returns a fluent, wrong destination for that clip, or supplies no validated uncertainty result | Text-only candidate is ineligible; no read call. The test should fail if hash agreement is treated as certainty. |
| Same reference/index with changed bytes, revision, MIME type, or clip order | Reject stale transcript and cache; no dispatch from the old source key. |
| Local worker finishes after cancellation, turn replacement, planner close, or deadline | Ignore its result; no cache write and no stale call. |
| Audio06 first chunk remains non-final; second chunk repairs it | No plan from the partial turn; after completion, only the repaired value reaches a tool. |
| Text-only candidate proposes a write or a read-then-write continuation | Discard it and verify native-audio fallback receives the original audio; no text-only call is dispatched. |
| Gemini changes or omits a runtime-owned transcript observation | Reject the text-only candidate and fall back or clarify. |
| Local certainty is unknown, an observation is uncertain, or a native-audio check disagrees | No text-only call; clarification/uncertainty remains monotonic. |
| Flag unset | Existing default native-audio route and provider behavior are unchanged. |

Measure end-to-end latency and false-accept / unnecessary-clarification rates on held-out, varied clips before widening eligibility. Until the uncertainty output passes the audio05 ambiguity gate, this route should remain fallback-only; the current hardcoded `uncertain=False` is not an acceptable admission signal.
