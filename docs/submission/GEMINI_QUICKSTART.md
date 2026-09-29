# Gemini participant quickstart

Use this guide for `participant.agent:ParticipantAgent`, the judge's queue
interface. Use Python 3.11 with a Gemini API key and the submission dependency pins.
No GPU, local weights, audio decoder or application server is required.

This profile is a **reproducible, unqualified setup candidate**. Current model
access does not establish task correctness or deadline performance. No completed
passing repeated public batch exists. As of 23 September, one earlier build
passed all nine original cases once, then failed its repeat batch. The latest
experimental-audio diagnostic passed four of nine at 71.5/100 weighted; native
response deadlines remain unresolved. Offline installation and configuration
checks do not override those failures. Registered team metadata is still required.

## Install outside the package

Run from the source checkout or extracted package root. Keep the environment,
real key file and output in a sibling directory so the package remains immutable.
On Windows PowerShell:

```powershell
py -3.11 -m venv ../thread-judge-local/venv
& ../thread-judge-local/venv/Scripts/python.exe -m pip --isolated install --index-url https://pypi.org/simple -r requirements-submission.txt
& ../thread-judge-local/venv/Scripts/python.exe -m pip check
if (!(Test-Path -LiteralPath '../thread-judge-local/.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '../thread-judge-local/.env'
}
notepad ../thread-judge-local/.env
```

On Linux/macOS:

```sh
python3.11 -m venv ../thread-judge-local/venv
../thread-judge-local/venv/bin/python -m pip --isolated install --index-url https://pypi.org/simple -r requirements-submission.txt
../thread-judge-local/venv/bin/python -m pip check
test -e ../thread-judge-local/.env || cp .env.example ../thread-judge-local/.env
```

Edit the external file in your editor and set `THREAD_API_KEY`. Create your own key
through [Google AI Studio](https://aistudio.google.com/apikey), following
[Google's current key instructions](https://ai.google.dev/gemini-api/docs/api-key).
Never include a real key in the source, ZIP, shell command, screenshot or report.

## One supported setup profile

The defaults and example use the following exact settings. The offline verifier
checks these against the runtime and this guide:

| Setting | Purpose |
|---|---|
| `THREAD_PROVIDER=gemini` | Direct hosted Gemini REST API; no provider fallback |
| `THREAD_MODEL=gemini-3.5-flash-lite` | Planning on actual text/audio/image inputs |
| `PARTICIPANT_THINKING_LEVEL=minimal` | Explicit supported thinking level |
| `PARTICIPANT_TIMEOUT_SECONDS=4.5` | Whole planning budget; acoustic cap remains 3.5 seconds |
| `PARTICIPANT_PREWARM=0` | No setup metadata or generation requests |
| `PARTICIPANT_IMAGE_EMBEDDING=1` | Enable the eligible current-image embedding request |
| `PARTICIPANT_AUDIO_MODE=independent` | Default independent audio verification |

`PARTICIPANT_AUDIO_MODE` also accepts the explicit experimental value
`single_call_reads`. Two live diagnostics using this mode failed delivery; it is
not a recommendation or a qualified replacement for the default.
Values are case-sensitive and are not trimmed. An unset or empty value uses
`independent`; an empty process value overrides a value in the selected file.
The doctor accepts both modes and warns when the experimental mode is selected.

Remove the old `PARTICIPANT_THINKING_BUDGET` override. Do not substitute a Live
model, switch providers, or silently retry another model. The browser's
`THREAD_LIVE_MODEL` setting is unused by this participant.

Embedding uses the existing `gemini-embedding-2` endpoint and real current image
bytes. It is eligible only when an offered tool declares an `image_embedding`
number array. A returned 768-dimensional vector can be attached only to a compatible
tool and matching current-image SHA-256. Planning never waits for it, and cancels
unfinished work. Enabling this setting does not establish successful embedding or
bonus eligibility; live acceptance must retain the actual returned-vector evidence.
See [Google's embedding guide](https://ai.google.dev/gemini-api/docs/embeddings).

As checked on 23 September 2026, Google limits 2.5 access to prior users and points
new projects to 3.8 Flash or 3.5 Flash-Lite. Both are listed with free standard
input/output access. This package configures only the profile above; it has no
alternate-model fallback. See Google's [model list](https://ai.google.dev/gemini-api/docs/models),
[pricing](https://ai.google.dev/gemini-api/docs/pricing) and
[thinking-level table](https://ai.google.dev/gemini-api/docs/thinking).

## Select and check the configuration

Windows, in the same PowerShell session:

```powershell
$env:PARTICIPANT_ENV_FILE = (Resolve-Path -LiteralPath '../thread-judge-local/.env').Path
& ../thread-judge-local/venv/Scripts/python.exe -B scripts/check_gemini_config.py --profile participant
if ($LASTEXITCODE -ne 0) { throw 'Fix the configuration failures above.' }
```

Linux/macOS:

```sh
export PARTICIPANT_ENV_FILE="$(cd ../thread-judge-local && pwd)/.env"
../thread-judge-local/venv/bin/python -B scripts/check_gemini_config.py --profile participant
```

The participant reads no automatic `.env` file. A judge may instead inject only
`SECRET_GEMINI_API_KEY`, as declared in `submission.yaml`, leaving
`PARTICIPANT_ENV_FILE` unset; the same runtime defaults then apply. Required HTTPS
access is to `generativelanguage.googleapis.com`. No import or setup smoke call
checks the provider.

For each alias group, any process alias chooses the entire process tier over the
file, including an explicitly blank alias. Within that tier, nonblank
`SECRET_GEMINI_API_KEY` / `THREAD_API_KEY` values must agree, as must
`PARTICIPANT_MODEL` / `THREAD_MODEL`. A blank process key suppresses the file key
and fails the doctor. Blank non-key runtime options use their bundled defaults.
The doctor reports field names only. `GEMINI_API_KEY` / `GOOGLE_API_KEY` are not
used by this project's loaders. Remove stale process overrides without printing
the environment, then rerun the doctor.

## Verify offline

Keep the original, unchanged official kit separately. From the package root:

```powershell
$kit = 'C:/absolute/path/to/unchanged/participant-kit'
& ../thread-judge-local/venv/Scripts/python.exe -B scripts/verify_samsung_submission.py --kit $kit --submission . --out ../thread-judge-local/participant-offline.json
```

Use `../thread-judge-local/venv/bin/python -B` with an absolute kit path on
Linux/macOS. Use a new receipt filename each time. The verifier checks official
admission gates, exact pins, import origins, configuration consistency and
synthetic transport/queue exchanges under an external-network guard. It neither
uses your real key nor runs model inference. The official evaluator itself does
not install the declared requirements.

The verifier defaults to `--audio-mode independent`. To check the experimental
configuration offline, explicitly pass `--audio-mode single_call_reads`; inherited
participant settings are cleared. The receipt records the selected mode and the
actual runtime mode for explicit process and file setup, separately from the
key-only default check. This checks configuration binding, not native audio behavior
or qualification. Keep a distinct receipt for each selection.

For real evaluation, run from the extracted package root so relative `audio/` and
`frames/` references resolve. If using another working directory, set
`PARTICIPANT_MEDIA_ROOT` to the directory containing those folders. Keep the
original 300-second setup cap, 120-second scenario cap and 6000-ms tail.
[Package instructions](README.md) contain the exact build/evaluation commands.

Before live testing, confirm the selected project's own free quota and preserve
all outcomes. An HTTP 429 and a timeout before headers are different failures;
no quota cause can be inferred from the timeout. Stop on quota rejection and
follow [Google's reset/retry guidance](https://ai.google.dev/gemini-api/docs/rate-limits).
A new key in the same project does not add quota. Doctor success and offline
verification do not establish provider access, latency or correct task completion.
