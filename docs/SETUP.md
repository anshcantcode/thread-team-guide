# Run THREAD

Python 3.11, Git and FFmpeg are required. Windows Kitchen uses local Windows SAPI speech. The local planner is Qwen3.5-4B Q4_K_M served by pinned llama.cpp b10930. Recognition defaults to pinned Whisper `small.en`. Model files are downloaded separately and verified; no credentials are bundled and no API key is required for Kitchen.

## Browser Kitchen

From a fresh Windows checkout:

```powershell
py -3.11 -m venv .venv-kitchen
.\.venv-kitchen\Scripts\python.exe -m pip install -r requirements-fdb3-clients.lock
.\.venv-kitchen\Scripts\python.exe scripts/setup_local.py
```

`setup_local.py` downloads the pinned Windows CUDA runtime, model files and recognizer. It also fetches the earlier app's vision projector; Kitchen itself does not use that file. Allow several GB of storage and network transfer. For existing assets, use their explicit paths in the commands below; keep private `.env` files out of the new checkout. GPU/CUDA availability must match the chosen profile.

Windows GPU speech also requires a complete NVIDIA cuDNN 9 installation for CUDA 12, as specified by [faster-whisper's GPU prerequisites](https://github.com/SYSTRAN/faster-whisper#gpu). The bundled cuBLAS package and CTranslate2's cuDNN dispatcher alone do not establish that prerequisite. Install the complete runtime from NVIDIA and add its DLL directory to this terminal's PATH before starting the host. This does not change the persistent system environment:

```powershell
$env:PATH = 'C:\PATH_TO_YOUR_CUDNN9\bin;' + $env:PATH
```

The launcher automatically exposes the pinned `.runtime/llama` CUDA DLLs to its own process. For an existing verified installation elsewhere, append `--cuda-bin C:\PATH_TO_EXISTING_LLAMA_RUNTIME`. No silent CPU fallback occurs. The recorded-PCM check of the earlier checkpoint passed on the existing machine; a clean Windows machine with these prerequisites has not been independently qualified.

In the first terminal, launch the planner with the declared settings. Use a fresh empty directory for this host's slot cache:

```powershell
New-Item -ItemType Directory .runtime/kitchen-slots -ErrorAction Stop
.\.runtime\llama\llama-server.exe --model .runtime/models/Qwen3.5-4B-Q4_K_M.gguf --host 127.0.0.1 --port 8098 --alias Qwen3.5-4B --ctx-size 8192 --parallel 1 --reasoning off --skip-chat-parsing --gpu-layers 99 --cache-ram 0 --batch-size 128 --ubatch-size 64 --threads 4 --seed 42 --slot-save-path .runtime/kitchen-slots
```

In a second terminal:

```powershell
.\.venv-kitchen\Scripts\python.exe scripts/serve_fdb3_clients.py --whisper .runtime/whisper-small-en
```

Open **http://127.0.0.1:8768**, connect and follow [the tour](TOUR.md). Keep only one Kitchen conversation active. Typed input needs no microphone permission. Voice input uses the browser's explicit microphone permission. Stop the two owned processes with Ctrl+C when finished.

CPU component testing is possible with a separately declared profile: set `THREAD_FDB3_PROFILE=cpu-component`, use `--gpu-layers 0` for llama-server, and keep the same asset hashes. It is slower and is not the measured GPU benchmark configuration. Do not override candidate flags silently.

On Linux, first install the CUDA/cuDNN prerequisites in [the complete reproduction procedure](fdb3/REPRODUCE.md), use the pinned model/config with a locally built llama-server and set a local synthesizer command, for example:

```bash
export THREAD_FDB3_TTS_COMMAND='["espeak-ng","-w","{output}","-f","{text_file}"]'
export THREAD_FDB3_TTS_PROFILE=espeak-ng
python scripts/serve_fdb3_clients.py --whisper /absolute/path/whisper-small-en
```

## Android Kitchen

Install `THREAD-1.0.0-android.apk` from the [submission release](https://github.com/anshcantcode/thread-team-guide/releases/tag/PRISM_GENAI_HACKATHON_Y2026). It is a development-signed build; verify the release checksum. An existing installation signed with a different certificate cannot be upgraded in place. Preserve its app data and use another test device/profile rather than uninstalling it blindly.

With Android 12+ and ADB authorized on the chosen device:

```powershell
adb -s YOUR_DEVICE_SERIAL reverse tcp:8768 tcp:8768
adb -s YOUR_DEVICE_SERIAL install -r PATH_TO_THREAD_APK
```

Open THREAD, then **Settings → Open Kitchen**. Leave the host at `http://127.0.0.1:8768`, connect and use the tour. The PC must continue running the host and planner. The native checklist persists in this installation; it is separate from the browser checklist. Starting Kitchen does not import Gemini credentials or change the existing app's configured mode.

The release APK keeps the network-facing activity private. ADB test-only extension controls are confined to the debug build. The current validation uses an Android emulator; physical-device/acoustic qualification is separate.

## Original Gemini app mode

The browser and Android app also retain their earlier Gemini interface. This mode is separate from the local FDB-v3/Kitchen submission path. Its setup is documented in [the original app runbook](RUN.md) and [Android setup](../android/README.md).

For the desktop browser, install `requirements.lock` in a Python 3.11 environment. On the first setup only, copy `.env.example` to `.env` and configure your own `THREAD_API_KEY`. Preserve any existing `.env`. Run `./run.ps1` on Windows and open `http://127.0.0.1:8766`. Android Settings stores its separately supplied key through the app's encrypted configuration. Provider access and quota are required; the release contains no key and enables no paid calls automatically.

## Build and test

Install the appropriate lock in a dedicated environment. Controller tests use `requirements.lock`; the real-SDK/client tests use `requirements-fdb3-clients.lock`.

```powershell
python -m unittest discover -s tests -v
python -m unittest discover -s tests_fdb3 -v
python -m unittest discover -s tests_linux -v
node tests/fdb3-client-check.mjs
node tests/kitchen-transport-check.mjs
node tests/audio-check.mjs
node tests/live-audio-check.mjs
node tests/workspace-check.mjs
```

Some SDK/contract tests require the pinned upstream checkout at `.runtime/Full-Duplex-Bench`; follow [reproduction](fdb3/REPRODUCE.md). Run timing-sensitive suites without competing builds/model loads. Retain a failed run before retrying; a busy-host timeout is still a failed invocation.

Android requires the checked-in Gradle wrapper, Android SDK and JDK 17 or newer:

```powershell
cd android
.\gradlew.bat --no-daemon --max-workers=2 :app:assembleDebug :app:assembleRelease :app:testDebugUnitTest :app:lintVitalRelease
```

The build stages the current Python source and a SHA-256 manifest into the APK. Validate that manifest against the checkout before publication; an APK built before controller edits is stale even if its version name is unchanged.

## Troubleshooting

An unavailable planner, mismatched recognizer hash or failed speech engine must produce a setup/session error, not a fabricated success. Read host logs, confirm ports 8098/8768 and asset hashes, and inspect the saved checklist before retrying an unknown write. Never repeat a write solely because its spoken response was interrupted.
