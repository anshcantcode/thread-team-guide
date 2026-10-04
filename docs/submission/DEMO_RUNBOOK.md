# One continuous THREAD demonstration

**Target: 4:30, acceptable 3:00–5:00. One unedited screen-and-audio take of the selected final source.** Owner-reported submission deadline: 4 October 2026. This is a recording procedure, **not a claim that the take has been recorded or that these live checks passed**. S4 adds opt-in local playback and a live observer; tonight's build/tests are CPU-only. No model, LiveKit, GPU, WSL, emulator, benchmark or live demo is started for that verification. Device playback and the final-source recording remain to be rehearsed in an exclusive GPU window.

## What the take can honestly show

1. An unchanged released recording sent at real time into the **live local LiveKit/WebRTC agent** with the official mock-tool contract. The audience hears both its disfluent/corrected request and the received reply as the worker feeds/receives PCM. The observer reads actual ASR, raw planner proposals, controller decisions, tool outcomes and TTS journals during execution. A correction before dispatch is distinct from interruption during audible assistant speech.
2. **Kitchen, the real extension:** microphone read → corrected add → interrupt the spoken reply → End → browser refresh/reconnect → read the durable item and export its one write receipt. Browser storage is real; it is not a purchase, cloud service or standalone phone inference.

`web/fdb3.html` is the live **Kitchen** client, despite its filename. It is not a benchmark-room viewer. Use the new [live read-only evidence page](../../web/demo-live.html), served automatically by [fdb3_live_demo.py](../../scripts/fdb3_live_demo.py). It checks journals every second and shows all observed events, including holds/refusals with their recorded reasons, controller admission, executed calls with outcome, and reply synthesis lines. Expand any entry for its raw evidence. Controller admission and `dispatch_intent` are **not** proof of invocation; only a `finished` entry is counted as a finished actual call, and the final result is shown separately. Missing evidence stays unknown. No hold or successful write is invented.

The wrapper invokes the **same `fdb3_audio_worker.py --room` path used by `fdb3_run.py`**, from a fresh source snapshot, adding only `--demo`. That flag enables the local `sounddevice` PCM tee and journals existing bridge events without changing gate decisions. Without `--demo`, the original sink/path remains and no playback module/device starts. The campaign runner, evaluator and Linux reproduction script are unchanged. Demo timing includes device I/O and extra journaling: **do not mix it into benchmark campaigns or latency/score evidence**. SAPI still synthesizes each text chunk before the existing pipeline emits audio; this is received-frame playback, not token-streaming synthesis.

## Pre-flight, before starting the recording

- Integrate the demo changes, docs and the measured final changes first. Use a clean, frozen final checkout; record its full commit. This branch's CPU tests do not transfer any old benchmark score to the new source. If later changes alter runtime/configuration, retain the old take and record a new one.
- Coordinate an exclusive recording window after the other GPU tasks finish. The launch commands below are **for the human recording operator later**, not work performed by S3. Do not reuse, stop or reconfigure another task's server. No emulator is needed.
- Use the existing Windows setup in [SETUP](../SETUP.md#browser-kitchen), Python 3.11 with `requirements-fdb3-clients.lock`, pinned llama.cpp b10930 and Qwen GGUF, pinned small.en, complete CUDA 12/cuDNN 9 DLLs, FFmpeg and local LiveKit 1.13.x. Run the offline asset/hash checks below. Do not run `setup_local.py` over another checkout or change a candidate profile for filming.
- Ask the evidence owner for the prepared assets directory (`dataset-manifest.json`, `agent-contract`, `evaluator-data`). Never send evaluator metadata or gold answers to the agent. The worker accepts only audio and the public contract.
- Recommended rehearsal candidate: **zero-based index 11**, ID **`ecommerce_11_62a885d5b6af18b3d4579e1b`**, duration **40.68 s**. Released metadata marks `SELF_CORRECTION` and exactly one expected state-changing call (`add_to_cart`). This is operator-side selection, **not a pass claim**. `--list` reads released metadata and prints candidates without expected arguments/dialogue; recording execution does not read that metadata or pass any selection ID/answer to the worker. Listen to the unchanged audio and inspect the new trace: accept a demonstration only if the corrected request and exactly one intended successful mock write are actually observed. Do not edit audio, add cues, patch results, tune the agent to this item or call it a 100-case result. If there is no `planning_held` event, show the actual update/cancellation and say so. If there is no actual interruption, that requirement remains unproven.
- Rehearse the frozen source once in a **different fresh take directory**, retaining failures. Verify the benchmark worker finishes within the first ~110 seconds of the proposed take; its hard runtime waits can be much longer. Verify the spoken Kitchen phrase, microphone, reply audio, actual interruption and refresh. The 4:30 schedule is a budget, not measured performance. If the setup cannot fit five minutes, this is a remaining recording gap, not permission to speed up or splice.
- Use one dedicated browser profile/window for this take. Preserve the ordinary user's checklist. Confirm that this profile starts with no rows/receipts, then keep it for the entire recording. Do not clear site data or seed a row. Keep one Kitchen tab/conversation; browser and Android lists are separate stores.
- Use the laptop's already-installed screen recorder (for example OBS): capture the full demonstration desktop plus microphone and system audio at normal speed. Hide private keys, notifications and unrelated windows before recording. Check a short local recorder sample, then discard only that recorder setup sample, not failed agent evidence. Do not replace replies, overlay fake telemetry, pause capture, cut, crop away failures or add a slideshow over the live task.
- Prepare terminal, benchmark observer and Kitchen windows side by side at readable zoom. Show real time/source at the start. Mute the Kitchen microphone until its segment to avoid transcribing narration or file playback. Headphones prevent feedback during the live Kitchen exchange; record system audio directly.

## Exact Windows preparation

Run these from the **selected final checkout** in PowerShell, only after the GPU owners release it. `Read-Host` fields are real existing paths supplied by the operator, not assumed laptop paths. Do not copy a private `.env`. This procedure writes to `.demo-evidence/` inside this checkout and the dedicated browser profile, never `.thread-run` or the shared `.runtime` junction. The existing `.venv-fdb3` has `sounddevice`; no install/download/spending is needed.

```powershell
$Python = Read-Host 'Absolute Python 3.11 exe with requirements-fdb3-clients.lock installed'
$Llama = Read-Host 'Absolute pinned b10930 llama-server.exe'
$Model = Read-Host 'Absolute Qwen3.5-4B-Q4_K_M.gguf'
$Whisper = Read-Host 'Absolute pinned whisper-small-en directory'
$CudaBin = Read-Host 'Absolute pinned llama CUDA DLL directory'
$CudnnBin = Read-Host 'Absolute complete cuDNN 9 DLL directory'
$LiveKit = Read-Host 'Absolute local livekit-server.exe (1.13.x)'
$Assets = Read-Host 'Absolute PREPARED benchmark assets directory'
$SourceCommit = (git rev-parse HEAD).Trim()
if (git status --porcelain) { throw 'Freeze a clean final checkout before filming.' }
$Take = Join-Path (Get-Location) ('.demo-evidence/session-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $Take -ErrorAction Stop | Out-Null
& $Python --version
& $Python scripts/fdb3_config.py --verify-whisper $Whisper
if ($LASTEXITCODE -ne 0) { throw 'Recognizer identity failed.' }
$Candidate = Get-Content config/fdb3-candidate.json -Raw | ConvertFrom-Json
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $Model).Hash.ToLower() -ne $Candidate.model.sha256) { throw 'Planner model hash mismatch.' }
$Candidate.environment.PSObject.Properties | ForEach-Object {
    $old = [Environment]::GetEnvironmentVariable($_.Name, 'Process')
    if ($null -ne $old -and $old -ne $_.Value) { throw ('Conflicting inherited flag: ' + $_.Name) }
    [Environment]::SetEnvironmentVariable($_.Name, $_.Value, 'Process')
}
$env:PATH = $CudnnBin + ';' + $CudaBin + ';' + $env:PATH
$env:THREAD_FDB3_CACHE_OWNER_FILE = Join-Path $Take 'cache-owner'
# Do not inherit a different synthesizer and call it SAPI.
if ($env:THREAD_FDB3_TTS_COMMAND) { throw 'Use a fresh documented Windows SAPI shell, or declare the actual TTS profile.' }
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object LocalPort -in 7880,7881,8098,8768 |
    Select-Object LocalAddress,LocalPort,OwningProcess
# If any required port is occupied, STOP and coordinate; do not kill it.

$Identity = [ordered]@{
    source_commit=$SourceCommit; source_clean=$true
    config_sha256=(Get-FileHash config/fdb3-candidate.json -Algorithm SHA256).Hash.ToLower()
    candidate=$Candidate; model_sha256=$Candidate.model.sha256
    tts='Windows SAPI'; judge='none: demonstration only'; transport='local LiveKit WebRTC'
    final_source_verified_by_operator=$false
}
[IO.File]::WriteAllText((Join-Path $Take 'service-identity.json'), ($Identity | ConvertTo-Json -Depth 20), [Text.UTF8Encoding]::new($false))
& $Python -m pip freeze | Set-Content -LiteralPath (Join-Path $Take 'packages.txt')
# Offline: metadata selection only; no audio device, model, service or GPU.
& $Python scripts/fdb3_live_demo.py --list --assets $Assets
$Take
```

Confirm model executable version using `& $Llama --version`; keep its output. `service-identity.json` is an operator preparation record, not an independent verification certificate. Do not switch `final_source_verified_by_operator` to true without comparing the selected source and snapshot. The demo wrapper separately hashes/verifies the input, contract and Whisper assets, copies a source snapshot, and writes `identity.json` plus `source/source-identity.json` in its newly printed take directory. It does not independently attest to the model already running on port 8098; match that owned service to the verified executable/model/config above.

### Start owned services, before capture

In the prepared shell create a fresh slot directory. In separate PowerShell terminals set the same `$Take`, asset/executable paths and process-local candidate/CUDA environment above (or paste the relevant assignments); variables are **not shared across terminals**. Run each foreground command in its own terminal so Ctrl+C later stops only that owned process. Save logs with `Tee-Object` if needed; never close another task's process.

```powershell
# Terminal 1: planner (the candidate supplies exact args, including seed 42).
New-Item -ItemType Directory -Path (Join-Path $Take 'slots') -ErrorAction Stop | Out-Null
$LlamaArgs = $Candidate.llama.args
& $Llama --model $Model --host 127.0.0.1 --port 8098 --alias Qwen3.5-4B @LlamaArgs --slot-save-path (Join-Path $Take 'slots')

# Terminal 2: loopback LiveKit for the benchmark worker.
& $LiveKit --dev --bind 127.0.0.1 --node-ip 127.0.0.1 --port 7880 --rtc.tcp_port 7881

```

In the prepared control terminal confirm `Invoke-RestMethod http://127.0.0.1:8098/health` succeeds. Then run the one-command demo below **before starting capture**: it reserves a free loopback port, opens the viewer, prints its fresh evidence folder and waits for **Enter**. No separate static server is needed. Port **8765 is forbidden**; an explicitly requested occupied port fails without stopping its owner. Only whitelisted viewer/journal/result/audio files are served, never arbitrary source, logs or directories. Before input starts the page must show waiting/unknown. Do not start Kitchen yet: serial use avoids two recognizers or planner conversations competing on the laptop.

## Shot list — one take, nominal 4:30

| Clock | Screen / exact action | What to say (describe only what actually appears) |
|---|---|---|
| 0:00–0:25 | Recorder rolling. Show `git rev-parse HEAD`, clean `git status --short`, identity/profile. | “THREAD, ReflexAi, Theme 05. This is source [read hash], local Qwen and Whisper, no paid API. I will show a released recording going through the live agent, then the real Kitchen extension. This is a demonstration, not a full benchmark score.” |
| 0:25–1:35 | Press **Enter** in the waiting demo terminal. Keep the live observer visible. The worker automatically plays the unchanged input as it feeds the room, and the received reply PCM as it arrives. Do not start a separate audio player. | “The worker is feeding this recording into a local LiveKit room at real time. Here are the fragments actually recognized and the raw proposals. A proposed or intended call is not an executed write.” Stop narrating over recorded speech. |
| 1:35–2:00 | Follow the actual hold/refusal/admission in the live timeline, then compare finished tool entries with the final actual-call list. Allow the live reply to finish. | “[Point to the actual hold/update/cancellation.] The journal records [actual number] completed calls. This receipt is the mock tool's outcome, not a purchase. The reply is being played from this run's received audio.” If one successful intended write or the required interruption is absent, use the failure path. |
| 2:00–2:25 | Worker has exited. Start Kitchen host below, open **http://127.0.0.1:8768**, show empty saved list, click **Connect and talk**, grant microphone. | “Kitchen is the real extension: the same controller, with browser-owned storage over WebSocket PCM, not benchmark WebRTC.” Speak: **“Read my checklist.”** Let its real response finish. |
| 2:25–3:20 | Speak a single corrected request: **“Add rinse two cups of rice to my checklist—actually, add rinse one cup of rice instead.”** Use a natural immediate correction, not a long pause after the first command. Watch captions, saved row and latest action receipt. | Stay quiet while the agent works. When the actual receipt appears and THREAD is speaking, interrupt aloud: **“Stop speaking.”** Show speech stop. Say: “That interruption stops the reply; it does not undo a write already accepted.” Do not claim this if no reply was in progress or speech did not stop. |
| 3:20–4:05 | Click **End**; export receipts; refresh the page visibly with Ctrl+R. Show saved item, reconnect, say **“Read my checklist.”** Export again. Do not reissue the add. | “The corrected item survived refresh. Reconnecting starts fresh conversation authority. The saved receipt, not my narration, records the write.” |
| 4:05–4:30 | Show the receipt-count command below and README results panel, not a slideshow. Stop at or before 5:00. | “This take has [observed number] successful adds and [observed number] updates. Full-run source/config/logs are linked here. [If pending, say results pending.] Local Qwen judgments are diagnostic; Samsung's pinned-judge rerun decides the official score.” |

**Do not script a reply or exact caption.** The suggested Kitchen text is not a hardcoded demo trigger. If the recognizer normalizes singular/plural wording, read the actual item; do not repair the displayed text. A changed quantity inside checklist text is not a separate numeric tool parameter.

### Commands used during the take

Before capture, in the prepared control terminal (fresh output every invocation; no evaluator or full campaign):

```powershell
& $Python scripts/fdb3_live_demo.py --recording 11 --assets $Assets --whisper $Whisper --endpoint http://127.0.0.1:8098/v1 --model Qwen3.5-4B --evidence-root (Join-Path $Take 'benchmark-takes')
# Wait at the Enter prompt. Start the recorder, show identity, then Enter at 0:25.
# After the worker exits the read-only viewer remains available until Ctrl+C.
```

Equivalent short command for the S4 worktree with its existing assets junction and the documented Windows environment/services already prepared:

```powershell
& '.\.venv-fdb3\Scripts\python.exe' scripts/fdb3_live_demo.py --recording 11 --whisper .runtime/whisper-small-en
```

Run it from the root of the final checkout. Exact ID selection is also supported: `--recording ecommerce_11_62a885d5b6af18b3d4579e1b`. No index/ID is passed to the worker. `--list` requires neither `--whisper` nor services. `--no-browser` prints the URL without opening it; `--start-now` omits the recorder-ready prompt (use only for the smoke test).

The worker uses automatic VAD and paced room audio, CUDA Whisper under the candidate environment, the local planner on 8098, and Windows SAPI. No `--manual`/`--unpaced` path is provided by this wrapper. The original output sink still saves `benchmark/spoken.wav`; the PCM tee also writes those frames to the default output device. Input playback follows each room capture, so it is a near-real-time monitor with normal device/RTC buffering, not sample-accurate synchronization or an official latency measurement. `playback.jsonl` exposes device errors/underflows; device writes and TTS text alone do not prove human hearing. Listen to the real capture.

Controller events can prove pre-dispatch holds/updates; do not call an event an audible barge-in unless the recording actually interrupted a reply in progress. The Kitchen segment separately attempts microphone barge-in. No code forces a hold or suppresses extra calls to make the shot fit.

After the worker exits, in a prepared terminal, start Kitchen:

```powershell
& $Python scripts/serve_fdb3_clients.py --whisper $Whisper --endpoint http://127.0.0.1:8098/v1 --model Qwen3.5-4B --port 8768 --cuda-bin $CudaBin
```

Starting this host must fit the rehearsed schedule. If model loading is too slow, allocate more time within five minutes; do not silently substitute a host from another source. The browser buttons, receipt panel and **Export checklist and receipts** already exist in `web/fdb3.html` / `web/fdb3.js`.

After the second export, open that **actual downloaded file**. The following is read-only and counts distinct stored request receipts, not transcript claims. Reads create receipts too, so total receipt count is not the number of writes:

```powershell
$Export = Read-Host 'Absolute path of the AFTER-RECONNECT exported checklist JSON'
$Saved = Get-Content -LiteralPath $Export -Raw | ConvertFrom-Json
$Receipts = @($Saved.requests.PSObject.Properties | ForEach-Object {
    $fp = $_.Value.fingerprint | ConvertFrom-Json
    [pscustomobject]@{ request_id=$_.Name; command=$fp[0]; status=$_.Value.result.status; detail=$_.Value.result.detail }
})
$Receipts | Format-Table -Wrap
$Saved.items | Format-Table text,checked,item_id -Wrap
'Successful adds: ' + @($Receipts | Where-Object { $_.command -eq 'add_checklist_item' -and $_.status -eq 'success' }).Count
'Successful updates: ' + @($Receipts | Where-Object { $_.command -eq 'set_checklist_item' -and $_.status -eq 'success' }).Count
```

Acceptance for the dedicated empty profile is one corrected saved item, one successful add, no update/second add, matching request ID/detail before and after refresh. Compare both exports after capture as well. The UI's latest receipt can become a read receipt; it is not a substitute for inspecting the full export. This demonstrates browser persistence, not distributed exactly-once behavior under every crash or proof of human hearing.

## If anything fails mid-take

- **Keep recording; name the observed failure.** Do not announce success, hide extra calls or substitute a saved successful screen. If no final worker result exists, call it incomplete, not zero tool calls. Never infer “held” from a blank journal.
- If automatic browser opening fails, open the printed loopback URL manually; the observer needs no model/tool connection. If live playback fails, the worker records an error and preserves any received WAV and journals. Review them with the viewer's **After completion only: file-playback fallback**. This is labelled retrospective playback, **not** a successful continuous live-audio benchmark segment. Do not replay the input over an active Kitchen microphone. Fix the device/driver and start a new full take; preserve the failure.
- If a wait consumes the segment budget, say “This attempt has not completed within the demo window.” Move to the visible failed state/receipts and finish the take before five minutes. Do not overlap the active worker with Kitchen. That file is retained failed evidence, **not a completed required demonstration**.
- If microphone permission fails, typed input via **Connect to type** can diagnose the extension. Label it typed; it does not satisfy the voice/interruption shot. If “Stop speaking” arrives after the reply already ended, interruption is unproven—do not claim a pass.
- After an unknown write or disconnect, inspect the saved list and exported receipts before any retry. Repeating the add to get better audio may duplicate the effect. Never clear a failure away during the take.
- Stop the recorder, preserve the complete failed file/logs, resolve the cause, then start a **new** full take with a fresh directory and separate browser profile. Do not overwrite the failed attempt. No guaranteed fallback can replace a missing end-to-end demonstration; do not use the animated launch film or historical edited demo as a final-source substitute.

## After capture — human release handoff

1. Stop only the owned host/LiveKit/planner/demo-viewer processes with Ctrl+C. Keep the take folder, input hash, raw journals, final result, both exports, original screen recording and all failed attempts. Confirm source/config hashes did not change during the take. The viewer makes no calls into the worker and refreshing it cannot repeat a tool call.
2. Review the **entire** video with sound. Confirm actual interruption, legible fragments/proposal/receipt, no extra write, visible refresh and 3–5-minute duration. Use `ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1 PATH_TO_ORIGINAL_VIDEO` and `Get-FileHash -Algorithm SHA256 -LiteralPath PATH_TO_ORIGINAL_VIDEO`. Metadata/decoding alone is not human listening review.
3. Create the video description from observed facts: final commit, config hash/seed, models/provider, original recording path/hash, benchmark mock tools, live benchmark PCM tee versus any retrospective file playback, live Kitchen audio, browser/device scope, actual call counts, failures and exact duration. Mark **unedited continuous capture** only if true. No score unless linked to its own committed results and source; the filmed clip is not that result.
4. The final results are filled into README, the deck and metadata from committed runs. The owner supplies representative, actual form/link and cutoff time, reviews/signs the AI disclosure, and verifies organizer repository/media access. S3 does not sign, publish, tag, push or submit anything.
5. Check the final APK's embedded Python source hashes, source archive contents, all release checksums and final tag resolution. An older APK/media hash is not proof for new source. Use [RESULTS.md](RESULTS.md) for the measured identities.

## Command/interface audit

S4 extends the S3 base `8e5d083` with `fdb3_live_demo.py` and the worker's opt-in `--demo`. The existing worker flags, Kitchen host options and configuration helpers above remain available. The wrapper uses a stdlib read-only HTTP server and the already-installed `sounddevice`; it neither starts services nor calls an evaluator. Planner/LiveKit commands remain those in [SETUP](../SETUP.md). CPU tests cover default-path no-playback imports/artifacts, exact PCM teeing and failure/cancellation cleanup, synthetic metadata filtering and HTTP path/port restrictions. Tests and `--list` are not a new live pass.

S4 CPU verification: **1,912 base tests** and **109 SDK tests**, zero failures/errors/skips, using the requested Python environments and the assets/upstream junction only for reads. `node tests/demo-live-check.mjs` passes synthetic viewer parsing/render/accounting checks. A separate successful **stubbed** worker comparison against `8e5d083` produced byte-identical default-path `result.json` and `spoken.wav`; no inference or device was used. All changed implementation/test file hashes were held fixed across the final suites. Raw logs, the initial fixed Windows occupied-port failure, and synthetic fixtures remain in the ignored `.demo-evidence/cpu-checks-s4/` directory, not submission assets. Browser automation had no connected browser, so no visual-browser pass is claimed. Actual dual-rate default-device playback, GPU inference and the continuous take remain unverified.

## Next exclusive GPU window: short operator smoke

1. Prepare **owned** planner/LiveKit services and the process-local CUDA paths above; no concurrent campaign or Kitchen host. In a new take, run the short command with `--start-now` (or use Enter). Never point it at `.thread-run`.
2. Listen for the unchanged 40.68-second input and THREAD's received reply. Check that STT, raw proposals and real controller events appear before `result.json`; inspect every finished tool call/outcome and the final call list. Check `playback.jsonl` for errors/underflows. A single intended successful write is an acceptance check, not something the wrapper guarantees.
3. Confirm `demo-status.json` and `benchmark/result.json` both complete; retain `worker.log` and all failures. Check the original screen-capture sample contains system audio from both streams and readable evidence. Measure elapsed time; the nominal benchmark segment budget is ~110 seconds. The worker's existing waits plus its 450-second outer timeout are not a promise that it fits.
4. Only after worker exit, rehearse Kitchen once in its separate fresh profile. Confirm an actual reply-in-progress interruption, persistent corrected item and one matching add receipt. If the released benchmark clip lacks the required interruption, select/rehearse another listed candidate; do not manufacture or infer it.

This smoke verifies the outstanding hardware/driver, CUDA/DLL, room timing, SAPI and recording behavior. It is not a full benchmark, an organizer qualification or the final 3–5-minute video.
