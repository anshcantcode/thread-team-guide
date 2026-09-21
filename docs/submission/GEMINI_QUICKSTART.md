# Gemini participant quickstart

The official entry is `participant.agent:ParticipantAgent`, using the evaluator's
queues. Use this route for the judge package. The browser and Android app are
separate product interfaces; their startup does not prove participant acceptance.
See [Gemini setup](../GEMINI_SETUP.md) for creating a key and troubleshooting access.

This is setup guidance for the integrated Gemini candidate. The candidate-009
README and evidence remain historical: its completed public batch scored 62.6,
with 6/27 mandatory and 4/27 full passes. New setup documentation and offline
checks do not replace that record or establish a passing new live run. The
manifest still requires the team's registered identity before final submission.

## Install and configure

Use Python 3.11 and the participant's pinned dependencies, in a separate environment
from the browser app. No weights, GPU, CUDA, local audio decoder, or local model
server is required. Run from the source checkout or the extracted package root.
Keep the virtual environment, real key file, and output **outside** that root.
The commands below use a sibling `thread-judge-local` directory so they also work
with an immutable package whose manifest rejects extra files:

```powershell
py -3.11 -m venv ../thread-judge-local/venv
& ../thread-judge-local/venv/Scripts/python.exe -m pip install -r requirements-submission.txt
if (!(Test-Path -LiteralPath '../thread-judge-local/.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '../thread-judge-local/.env'
}
notepad ../thread-judge-local/.env
```

Put your key in `THREAD_API_KEY`. The shared example explicitly chooses
`gemini-2.5-flash`, `PARTICIPANT_THINKING_BUDGET=0`,
`PARTICIPANT_PREWARM=0`, and `PARTICIPANT_IMAGE_EMBEDDING=0` for the bounded
Gemini candidate. Audio and images remain actual inputs to Gemini. These settings
do not establish that media requests finish within their normal deadlines.

Explicitly select the configuration file in the same PowerShell session:

```powershell
$env:PARTICIPANT_ENV_FILE = (Resolve-Path -LiteralPath '../thread-judge-local/.env').Path
& ../thread-judge-local/venv/Scripts/python.exe -B scripts/check_gemini_config.py --profile participant
if ($LASTEXITCODE -ne 0) { throw 'Fix the configuration failures above.' }
```

The participant does not automatically read the app's `.env`. A judge deployment
can instead inject `SECRET_GEMINI_API_KEY`, as declared in `submission.yaml`, and
the selected model/options directly into its process environment. In that route,
omit `PARTICIPANT_ENV_FILE` and leave personal `.env` files out of the archive.
Process configuration overrides the entire file alias group. Within the selected
tier, `SECRET_GEMINI_API_KEY` and `THREAD_API_KEY` must agree if both are nonblank,
as must `PARTICIPANT_MODEL` and `THREAD_MODEL`. An explicitly blank process key
alias suppresses file fallback. The doctor never displays configured values.

On macOS or Linux:

```sh
python3.11 -m venv ../thread-judge-local/venv
../thread-judge-local/venv/bin/python -m pip install -r requirements-submission.txt
test -e ../thread-judge-local/.env || cp .env.example ../thread-judge-local/.env
```

Edit `../thread-judge-local/.env`, then select it and check:

```sh
export PARTICIPANT_ENV_FILE="$(cd ../thread-judge-local && pwd)/.env"
../thread-judge-local/venv/bin/python -B scripts/check_gemini_config.py --profile participant
```

## Verify the offline contract

Set the path to your separately retained, unchanged official participant kit:

```powershell
$kit = 'C:/absolute/path/to/unchanged/participant-kit'
& ../thread-judge-local/venv/Scripts/python.exe -B scripts/verify_samsung_submission.py --kit $kit --submission . --out ../thread-judge-local/participant-offline.json
```

Use `../thread-judge-local/venv/bin/python -B` and your kit's absolute path on
macOS/Linux. Choose a new output filename when retaining another verification run.
The verifier checks the submission's imports, dependency declarations, official
admission gates, and injected exchanges while blocking external requests. It
does not measure provider quality or end-to-end scenario success. Keep the
original kit separate so its bytes can be compared with the packaged copy.

## Before a live evaluator run

The official `eval_submission.py` runner lives in the generated kit-based package;
an ordinary app checkout need not contain it. Packaging/acceptance owns the exact
run command, source freeze, selected settings, request cap, and preserved output.
Use the package's unchanged official instructions and the acceptance owner's
approved run plan. Do not start the entire public batch as an installation check.

Confirm project quota for the selected model and auxiliary requests, then use
the bounded actual-participant text/audio/image checks before a full batch.
The current development key is owner-confirmed free API tier. An observed 429
and a timeout before HTTP headers are different outcomes; the timeout's cause
is unknown. No paid-tier latency improvement has been established.
Normal planning/audio deadlines and the official scorer stay unchanged. Model
metadata, doctor success, and an offline verifier pass cannot establish live
availability, latency, or task correctness. Preserve every timed-out or rejected
attempt alongside successes.
