# Android correction control — 28 September 2026

The preregistered recovery run **extension-audio014 passed the exposed synthetic correction and persistence control**. Exactly one actual `add_checklist_item` wrote `wash the spinach`; no celery was written. Force-stopping the app and restarting its native read handler returned the same persisted item. The preceding **extension-audio013 was an infrastructure failure**, retained with exit 1 and zero device writes.

Both runs used frozen source **`fecb5c221e2609e39799b87627e1f7327a54da89`**, with a clean worktree and unchanged runtime hashes. This is evidence for that frozen revision, not the evolving submission candidate. It is one reused development control, not a benchmark score, held-out validation, human-speech result, or G7 completion.

Machine-readable evidence and raw-artifact hashes: [extension013-summary.json](evidence/extension013-summary.json). Raw artifacts remain in the ignored `.thread-run/raw` evidence directory of the retained `thread-fdb3` worktree; they were not copied into this release document directory.

| Run | Exit / status | Actual writes | Persisted correction | Received speech | Assessment |
|---|---|---:|---|---|---|
| extension-audio013 | 1 / infrastructure error | 0 | No session checklist created | No recognized speech | Invalid correction inference; retained failure |
| extension-audio014 | 0 / diagnostic completed | 1 | `wash the spinach`, still present after app restart | Received WebRTC waveform retained | Exact correction/persistence control passed |

## Frozen input and configuration

The 11.0695-second recording is independently authored Microsoft David Desktop SAPI speech, previously used for extension development. Its SHA-256 is `97b5babb91f47021a6559954c73c936f485dc008b1991817fe63eee910f97443`. The unchanged acceptance criteria require one `add_checklist_item`, exact text `wash the spinach`, no `chop the celery`, actual persistence after restart, and speech tied to the real native receipt.

The successful input recognition contained these successive utterances:

1. “Add chop the celery to my checklist.”
2. “No, do not add celery.”
3. “Add wash the spinach to my checklist instead.”

Runtime: local Qwen3.5-4B-Q4_K_M on port 8098, 8192 context, GPU layers 99; faster-whisper base.en on CUDA; local LiveKit WebRTC on port 7880; Windows SAPI development TTS; tethered adb debug Activity on an owned read-only emulator. `THREAD_FDB3_WHISPER_PROMPT=contract`, prompt cache, argument normalization, follow-up, and planner guidance 1 were enabled. The summary records model/Whisper/source hashes, package versions and GPU identity. No benchmark judge was used for this device control.

The installed APK hash was independently read from the emulator and matched `72d4d22c44f3044bd3b60391d4dda4eead5286d52fad8d96473041f5e964df1e`. The existing native extension Activity source hash was `7a93eb76713578086b14644c5cc29fe6cd445c16d49dafc811a40255f8b4d2a9`.

## Execution and preserved failure

The implementation reviewer’s batch010 completed before this lane used the GPU; its output ended `FULL2_SKIPPED` and `ALL_DONE`, and no benchmark worker remained. The prepared extension script needed two host setup adjustments: the registered AVD name is `Medium_Phone_API_36.0`, and its existing read-only data overlay lacked enough install space. A fresh owned per-run data image supplied space without deleting or replacing the shared AVD overlay. All launches were hidden/headless on owned serial `emulator-5560`.

013 failed when input ASR could not load the already-installed `cublas64_12.dll`. It made zero planner calls and zero device writes, reached the runner's bounded timeout, and saved the errors and empty-speech evidence. This is not a valid inference comparison. Its raw files were not overwritten.

014 was separately preregistered before execution. The only inference environment recovery was prepending the existing `.runtime/llama` directory to `PATH`, as batch010 had done. Source, audio, models and acceptance criteria stayed fixed. No dependency/model download or paid request occurred, and no further inference retry was made.

The actual tool ledger contains only:

```json
{"function":"add_checklist_item","args":{"text":"wash the spinach"},"outcome":"success"}
```

The native receipt said `Added checklist step: wash the spinach`. A subsequent real `am force-stop com.thread.app`, native `read_checklist` restart, and private-preference readback found exactly one unchecked `wash the spinach` item. The verification read is separate from the agent's recorded tool calls.

## Speech and visual evidence

The TTS request exactly matched the native receipt: `Added checklist step: wash the spinach`. The saved output is received WebRTC PCM. Local Whisper transcribed that waveform as `Add a checklist step, wash the spinach.` These are recorded separately because output ASR is fallible; no human listening review is claimed.

Actual unedited emulator screen recordings and screenshots were captured. The debug transport Activity finishes immediately and has no visible checklist view, so the screenshots show the launcher. **These visuals do not prove checklist persistence.** The proof is the native receipt and readback after restart; the raw silent screenrecord and received speech WAV are separate captures, not a continuous audiovisual demonstration.

Useful retained files under the raw evidence root:

- `extension-audio013-preregistration.json`, `extension-audio013-execution.json`, and `extension-audio013/result.json`: preserved failed attempt and identity.
- `extension-audio014-preregistration.json`, `extension-audio014-execution.json`: recovery registered before execution, exact command/environment.
- `extension-audio014/result.json`, `tool-calls.jsonl`, `stt-requests.jsonl`, `tts-requests.jsonl`, and `model-requests.jsonl`: actual runtime ledger.
- `extension-audio014/verification.json`: force-stop, native restart, and actual storage readback.
- `extension-audio014/spoken.wav`, `extension-audio014-real.mp4`, `extension-audio014-screenrecord.json`, and `extension-audio014/device-after.png`: actual media with capture limitations above.

014 consumed 40.923 seconds of worker wall time, four local model requests, three input transcriptions, one output transcription, and one SAPI synthesis. Model token usage was reported for only two requests; the missing values remain null in raw evidence. These single-control timings are not official benchmark latency. Total paid requests across both attempts: **0**.

The diagnostic session cleanup returned success, owned emulator shutdown returned exit 0, and subsequent adb/process inspection confirmed that emulator and extension workers were gone. The shared model/LiveKit services and all raw results were retained. The GPU was released to the coordinator.

The remaining extension gate includes a reviewable UI, current-candidate validation, physical-device/live-microphone evidence, and submission review. Timer behavior was not tested here. A later viewer/build/run must have its own source/APK identity and new preregistration; it must not relabel 014 as evidence for changed code.
