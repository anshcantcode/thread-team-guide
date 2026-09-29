# Set up THREAD with Gemini

Use Python 3.11, an internet connection, and a Gemini API key. The default setup
uses hosted Gemini for planning and media; it needs no local model weights, CUDA,
or local speech-recognition installation. Run commands from the checkout root.

The browser steps below require the full application checkout; they do not apply
to the smaller judge archive. Choose them for a product demo. For the Samsung queue
interface, follow [the judge quickstart](submission/GEMINI_QUICKSTART.md). The
app and participant have separate dependency files and runtime entry points.

## 1. Create your key

Open [Google AI Studio's API Keys page](https://aistudio.google.com/apikey), select
or create your project, and create a key. If an existing project is absent, import
it into AI Studio first. New AI Studio keys use Google's current authorization-key
flow; a rejected older standard key may need migration. Follow
[Google's key instructions](https://ai.google.dev/gemini-api/docs/api-key).

Put the value only in your local `.env` as `THREAD_API_KEY`, or use your deployment's
secret environment injection. Keep the real file and key out of Git, screenshots,
messages, browser code, and shared archives. This application reads `THREAD_API_KEY`
explicitly; Google's SDK names `GEMINI_API_KEY` and `GOOGLE_API_KEY` do not configure it.

## 2. Install the browser app

On Windows, open PowerShell in the checkout:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
if (!(Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
}
notepad .env
```

Set `THREAD_API_KEY` in the editor. Keep the other sample settings for the first
try. If you already have a `.env`, compare its settings with `.env.example` rather
than overwriting it. The example pins `THREAD_MODEL=gemini-3.5-flash-lite` and a separate
Live model; it is a configuration candidate, not a guarantee of quota or timing.

On macOS or Linux, use the same files:

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
test -e .env || cp .env.example .env
```

Edit `.env` in your editor before continuing. Environment activation is optional
because these commands use the environment's Python explicitly.

## 3. Check configuration and start

On Windows:

```powershell
.\.venv\Scripts\python.exe scripts/check_gemini_config.py --profile app
if ($LASTEXITCODE -ne 0) { throw 'Fix the configuration failures above.' }
.\run.ps1
```

On macOS or Linux:

```sh
.venv/bin/python scripts/check_gemini_config.py --profile app && \
  .venv/bin/python -m uvicorn thread_agent.server:app --host 127.0.0.1 --port 8766
```

Open [the local workspace](http://127.0.0.1:8766/). Use the address reported by
`run.ps1` if you changed its port. The POSIX command above binds port 8766 explicitly.

The doctor checks which file is loaded, key presence, alias conflicts, provider,
and model-name syntax. It prints no configured values and makes no network
requests. The app profile does not validate every optional runtime setting; the
participant profile additionally checks the selected thinking level, deadline,
prewarm, image-embedding, audio-mode and media-root settings. The default audio mode
is `independent`; `single_call_reads` is an explicit experiment pending native
evidence. A pass does not
verify that Google accepts the key or that the chosen model meets task deadlines.
Server startup likewise establishes only that the local app is reachable.

## 4. Try one conversation

Choose **Type instead** for a typed request, or **Start talking** and allow the
microphone. Typed requests also open a Gemini Live session and produce voice
replies; they still need Live access. Try a small request before a longer demo,
then interrupt a flight search with a destination correction and inspect the task
record. Flight inventory and reservations are fictional demonstration services.

Opening a conversation and sending requests use provider quota. A successful
conversation checks that particular session; it does not validate the separate
official participant. End the conversation with the red handset. On Windows,
run `stop-thread.ps1` to stop the desktop server. On macOS/Linux, use Ctrl+C in its
terminal.

Android uses its own embedded backend. Enter the key in the phone's THREAD
Settings; the desktop `.env` does not configure the phone. See
[Android setup](../android/README.md) for installation and builds.

## Which setting does what?

| Setting | Consumer app | Official participant |
|---|---|---|
| `THREAD_API_KEY` | Required key name | Supported local key name |
| `SECRET_GEMINI_API_KEY` | Not read | Organizer-injected key name declared in `submission.yaml` |
| `.env` loading | Repository root, automatically | Only when `PARTICIPANT_ENV_FILE` selects it |
| `THREAD_MODEL` | Planning and owned-audio verification | Shared planning-model setting |
| `PARTICIPANT_MODEL` | Not read | Optional alias; must agree with `THREAD_MODEL` within the same configuration tier |
| `THREAD_LIVE_MODEL` | Live voice, including typed browser conversations | Not used |
| `PARTICIPANT_THINKING_LEVEL=minimal` | Not read | Selected candidate's explicit thinking level |
| `PARTICIPANT_TIMEOUT_SECONDS=4.5` | Not read | Whole planning deadline |
| `PARTICIPANT_PREWARM=0` | Not read | Disables setup metadata requests |
| `PARTICIPANT_IMAGE_EMBEDDING=1` | Not read | Enables eligible current-image embedding without delaying planning |
| `PARTICIPANT_AUDIO_MODE=independent` | Not read | Default audio mode; `single_call_reads` is experimental |

The app's process environment overrides file values for the same name. The
participant first chooses the process environment or the file for each complete
alias group: any process alias, even a blank one, suppresses that group's file
values. Differing nonblank aliases within the selected tier are errors. For
example, a process `PARTICIPANT_MODEL` overrides the file's `THREAD_MODEL`; an
empty process `SECRET_GEMINI_API_KEY` hides the file's `THREAD_API_KEY`.
Remove an unintended
Windows override with `Remove-Item Env:THREAD_API_KEY -ErrorAction SilentlyContinue`,
or `unset THREAD_API_KEY` in a POSIX shell, then rerun the doctor. Do not print
the environment to debug keys. Configure one key alias and one model alias when
possible, and avoid keeping stale process overrides.

Remove an old `PARTICIPANT_THINKING_BUDGET` override when using the checked-in
participant profile. Do not substitute a Live model
for a structured planning model. The consumer app has its own generation settings;
participant options do not tune the app.

## Access, quota, and errors

The owner confirmed on 2026-09-21 that the current development key uses the
**free API tier**. Each teammate or judge must check their own project's limits.
Our evidence includes an HTTP 429 rejection and separate timeouts before response
headers. The latter do not reveal their cause; they are not proof of a quota
rejection. Changing billing tier has not been tested as a latency fix.

Check the selected project's active model limits in AI Studio before a batch.
Google applies limits per project and model, including requests and input tokens;
creating another key in the same project does not add quota. Free access does not
establish enough capacity for a full evaluation plus Live sessions and auxiliary
media requests. Published capacity is not guaranteed. See
[Google's rate-limit guide and active-limit link](https://ai.google.dev/gemini-api/docs/rate-limits).

| Symptom | Next step |
|---|---|
| Doctor reports missing key | Set `THREAD_API_KEY` in the file that the selected profile actually loads. For a judge process, inject `SECRET_GEMINI_API_KEY`. |
| Doctor reports conflicting aliases | Remove the unused alias or make the two values identical, including process overrides. |
| Key is present, but Google rejects authentication/access | Check the project, key type, API restrictions, and model access in AI Studio. Follow the linked key-migration guidance for older keys. |
| Model is unavailable or the request settings are rejected | Check the exact model ID and supported API/settings. A listed model is not proof of this project's access. |
| Quota or HTTP 429 error | Check the affected model's limits and reset/retry guidance. Stop repeated attempts until the limit is resolved. |
| Timeout | Retain the failed attempt. Check provider/network conditions; a longer timeout would change the evaluation contract. |
| Browser works, phone fails | Configure the phone separately and check its internet and microphone permission. |

Google's [current model list](https://ai.google.dev/gemini-api/docs/models) was
checked on 2026-09-23. It limits 2.5 access to prior users and directs new projects
to 3.5 Flash-Lite or 3.8 Flash. Both have free standard input/output access in the
[official pricing table](https://ai.google.dev/gemini-api/docs/pricing).
The repository retains its implemented Live configuration. Updating
to [3.8 Live](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-live) requires
checking changed function-call and interruption behavior, not only changing a name.
The selected 3.5 Flash-Lite setup profile is unqualified; native audio, images,
deadlines and full acceptance require their own recorded checks.
