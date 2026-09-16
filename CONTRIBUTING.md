# Contributing to THREAD

Start with the [product tour](docs/START_HERE.md), [setup](docs/RUN.md), and [code map](docs/CODE_MAP.md). Keep changes tied to an observable user outcome or a reproduced defect.

## Development workflow

1. Create a branch from the current `main`.
2. Describe the behavior you are changing and the boundary it affects.
3. Read the relevant implementation and existing tests before editing.
4. Make the smallest complete change, including failure and empty states.
5. Run focused checks, then the wider suite when shared behavior changed.
6. Open a pull request with the problem, resulting behavior, verification, and remaining limitations.

## Contracts to preserve

- A result must belong to the current request/revision before it can drive an action.
- Permission is tied to a specific current action. Acknowledgment is not blanket authorization.
- Submitted effects stay accounted for across interruptions and uncertain responses.
- Provider failures must not become fabricated facts or silent success receipts.
- Saved user content, keys, and raw microphone audio must not enter source control or public reports.
- A new capability needs an explicit result contract, source/provenance rules, and a usable native/browser representation where supported.

## Checks

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
node tests/audio-check.mjs
node tests/live-audio-check.mjs
node tests/workspace-check.mjs
.\.venv\Scripts\python.exe scripts/check_theme5.py --seeds 50
```

Android build and device checks are documented in [android/README.md](android/README.md). Use the optimized-release microphone check for changes to audio, native dependencies, or shrinking rules; debug instrumentation does not cover that path.

Tests that call a real provider or change a device are opt-in. Read their setup and effects before running them. Do not remove assertions to obtain a passing result.

## Reporting an issue

Include app/source version, device, typed versus spoken input, exact reproduction steps, expected behavior, actual behavior, and whether an action really occurred. Share a minimal screenshot or redacted error. Keep credentials and unrelated personal content out of reports.

## Documentation and assets

Update capability status when behavior changes. Keep generated drafts, simulated services, recorded data, and live outcomes clearly distinguished. Preserve bundled third-party notices and record new asset sources in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
