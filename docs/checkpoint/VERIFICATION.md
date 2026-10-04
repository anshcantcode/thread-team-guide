# Verification record

**Historical checkpoint record.** “Current” and test counts below belong to this September checkpoint. Later measurements remain source-labelled in [submission results](../submission/RESULTS.md); final-source evidence is in [the README results](../../README.md#results).

This checkpoint repairs the current source and connects it to browser and Android Kitchen. Historical benchmark measurements and fresh engineering checks are separate evidence.

## Verified historical measurements

| Evidence | What was checked | Result |
|---|---|---|
| Run 7, source 1fcba977 | 100 input hashes, source/evaluator snapshots, inference/evaluation identities, tool journals and judge receipts | 61/100 strict and window-strict; 100 evaluated; 0 infrastructure errors |
| Run 8, source 4f95fdcb | Same checks across all 100 recordings | 61/100 strict and window-strict; 100 evaluated; 0 infrastructure errors |
| Held-out-016, source 4f95fdcb | 18 authored scenarios Ã— live audio / text / ASR-text; exact original source and evaluation provenance | 25/54 strict; 54 present; 0 unmatched writes; 0 audit errors |
| Run 4 raw accounting | Recounted case outcomes and infrastructure status | 57/100, 99 evaluated, 1 infrastructure error; previous 58 claim corrected |

These checks recompute archive consistency, not fresh inference. The local judge is Qwen, not an organizer result. The two 61/100 runs use different source revisions. Of the 61 strict tool passes in each, 58 also have positive local response-quality judgments. Do not merge those criteria or infer repeated frozen-source qualification.

Sources: [run 7 audit](evidence/run7-archive-audit.json), [run 8 audit](evidence/run8-archive-audit.json), [held-out gate audit](evidence/heldout016-archive-audit.json). Their raw originals remain preserved. Portable release exports explicitly identify any path normalization.

## Fresh controller and SDK checks

The final serial run after the spoken-receipt repair passed **1,876 base tests and 102 real-SDK tests**, with zero failures, errors or skips. Runtime/test source hashes were identical before and after both suites. Base duration: 234.488 seconds; SDK: 52.356 seconds.

A subsequent one-line host cleanup catches a normal peer WebSocket disconnect during shutdown. Its seven independent host-authority tests passed again, and live client retests exercise the actual connection lifecycle. That follow-up is recorded separately rather than silently changing the source identity of the full suite.

The reproduction guard suite passed **18/18** both with the Windows Git Bash prerequisites available and under the existing Ubuntu WSL environment. This tests configuration, failure exits, reference identities and shell guards. It is not a complete Linux/NeMo/GPU benchmark.

## Defects repaired

- Missing required search arguments now cause clarification. The bridge no longer injects None into required numeric/string fields.
- A planner result that actually finishes after its deadline cannot commit an audio-cache update.
- Old scheduled typed requests and reused input tokens cannot borrow the authority of newer input.
- A matching device receipt can settle an unknown result even when the synchronous caller timed out first. It never repeats the effect or revives the expired continuation.
- Empty flushes, out-of-order acknowledgements and intermediate playback statuses cannot mark unheard audio as complete.
- Exact returned human-readable receipt sentences remain usable when the record also contains numeric IDs or nested booleans. The assistant no longer falls back to narrating internal IDs for this case.
- Android playback accounts for interleaved message spans and host-origin interruption before local voice activity detection.

Independent regressions reproduced the relevant defects before repair. Three older search expectations were strengthened to reject schema-invalid dispatch; no expected benchmark answer, grading rule, timeout or test target was relaxed.

## Browser and Android

[Client component evidence](evidence/client-components.json) records the build, 11 JVM tests, 9 emulator checks, browser storage/lifecycle checks and existing platform regressions. The APK includes a manifest of the current Python source and is checked against the checkout before release.

The first live browser request successfully added and persisted a real checklist row, then exposed the ID-narration defect. Its exported tool receipt and failure observation remain in the evidence. The repaired browser retake and native debug APK each completed one actual checklist write, spoke a clean caption and preserved the row after reopening. Native playback used the actual AudioTrack playback head. Across these three typed turns, all three tool requests are recorded in [the client live summary](evidence/client-live-summary.json).

The minified release APK passed installation, signature, embedded-source identity, upgrade-data preservation and a separate Java companion UI smoke from MainActivity through Settings into Kitchen. The debug AndroidX instrumentation runner could not start against the R8-minified release; that failed attempt ran no model/tool request. The actual native host/tool/audio test used the debug APK. The two scopes are not conflated.

A synthetic SAPI recording then traveled as paced 16 kHz PCM through the actual host recognizer, current controller, unmodified browser tool implementation with file-backed storage, and speech output. Its first attempt failed before transcription because CUDA DLLs were not exposed to the process. The launcher now sets its own CUDA search path. The same recording then produced exactly one `add_checklist_item` call for `rinse barley`, a successful persistent receipt, and 157,896 bytes of 24 kHz output PCM. All requests, both attempts, and audio hashes appear in [recorded-audio evidence](evidence/recorded-audio.json). Captured output was independently transcribed locally. The probe acknowledged no acoustic playback and makes no human-hearing claim.

Kitchen is a host-backed extension with real client-owned storage. The Android check uses an emulator and a development signing certificate. It is not physical Samsung-device qualification, standalone on-device inference, or production Play signing. Browser and native typed checks do not establish ASR quality.

## Retained failed attempts

Earlier full test invocations are preserved, including a busy-host timing failure, an invocation with three scheduling/stdio errors, and the deterministic planner-deadline failure that led to the general repair. The initial reproduction-guard attempt lacked Git Bash utilities and exposed a missing historical-reference config key during documentation cleanup; the key was restored with an explicit historical scope and the unchanged tests rerun successfully. The live narration failure is also retained.

The original required-argument and deadline negative controls are evidence of the defects. Only the final, identified passing invocations are cited as current test results. Historical failures were not deleted to manufacture a clean record.

## Remaining qualification

- No fresh full 100-recording result has been established for this repaired checkpoint. The 61/100 historical score does not transfer.
- The three fresh preregistered 100/100 target remains unmet.
- Full independent Linux/NeMo/GPU reproduction and the organizer rerun remain required.
- OS-enforced evaluator isolation, physical-device acoustic behavior and multilingual recognition remain unqualified.
- Final video/slides, team metadata, required human disclosure/signature, organizer access, confirmed deadline/form and final tag remain pending.
- Competitors without comparable actual execution remain unranked.

All current work uses the authorized local lane with zero paid inference, speech, judge or LiveKit requests. Three typed turns plus one successful audio turn executed four actual client tool requests. The failed audio setup attempt executed none. A separate local CPU ASR pass checked the captured output. These are engineering checks, not benchmark cases. See [Samsung requirements](SAMSUNG.md) for the final submission boundary.
