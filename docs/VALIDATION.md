# Validation and evidence scope

[Home](../README.md) · [Setup](RUN.md) · [Capabilities](WHAT_WORKS.md) · [Code map](CODE_MAP.md)

## Public-source preparation · 16 September 2026

The application was copied into a clean source checkout, with a newly created Python 3.11 virtual environment and a fresh installation from `requirements.lock`. No development `.env`, personal notebook, device credentials, or existing build output was copied into that checkout.

| Check | Result | Scope |
|---|---|---|
| Python regression suite | **605 passed** | Backend, authority, protocol, providers under controlled responses, private package checks, widgets, and embedded-runtime contracts. |
| Browser audio suite | **Passed** | WAV encoding and microphone permission/lifecycle behavior. |
| Live browser audio suite | **Passed** | PCM playback, interruption/pause/resume, continuation, and late-permission cleanup. |
| Workspace renderer/export suite | **72 checks passed** | Structured result rendering and export behavior. |
| Deterministic Theme 05 replay | **Passed** | 6 families × 50 seeds = 300 scenario/seed combinations; 1,200 paired/fresh-process executions with matching logical traces. |
| Android optimized release | **Build passed** | `:app:assembleRelease`, including `lintVitalRelease`, from the separate source checkout. No phone was required for this build. |
| HTTP startup and assets | **6 checks passed** | Fresh server startup, configuration, homepage, brand image, font, and browser scripts; no cloud request. |
| Publication scan | **Passed** | Reviewed staged files checked against the configured private key, common credential formats, private/generated paths, personal filesystem references, and unwanted attribution metadata. |

The machine-readable [validation record](../reports/public-source-validation.json) contains aggregate results and source hashes. Raw logs and provider/device exports are deliberately kept out of public source history.

The [GitHub Actions workflow](../.github/workflows/ci.yml) runs the Python/browser/replay checks on Windows and Linux, plus Android debug build/lint on Linux. Consult the repository's Actions page for each remote run's actual result; a workflow file alone is not evidence that a run passed.

## Reproduce the local checks

```powershell
.\.venv\Scripts\python.exe scripts/verify_workspace.py
.\.venv\Scripts\python.exe scripts/check_theme5.py --seeds 50
.\scripts\build-android.ps1 -Release
```

The first command requires Node.js as well as the installed Python dependencies. It produces `reports/verification-expanded.json`. The replay produces `reports/theme5-replay.json`. These generated files remain local unless reviewed for publication.

## Historical device evidence

The team's Android 0.6 development record includes 28 passing native checks, real typed Gemini/Android handoff checks, and two passing optimized-release microphone lifecycle cycles on a Galaxy S24. These establish particular recorded behaviors on that device. They are not newly executed phone checks of this public checkout.

Earlier headless model acceptance results and authored multimodal cases retain their original source/model scope. The test fixtures in `evaluation/` are included so the harness can be inspected and rerun; original model quota, timing, and failure observations should not be extrapolated into general reliability claims.

## Limits

- Scripted controller replays do not measure language understanding or physical microphone latency.
- A build/lint result does not replace device testing of the minified microphone path.
- Google handoff receipts do not prove a page finished loading; compose screens do not prove messages were sent.
- Spotify account authorization and playback remain unverified until the Developer app is registered and an actual account/device test succeeds.
- Flight, meeting-room, and device-support services are fictional evaluation environments.
- The exact Samsung kit, final execution requirements, and container execution still need their own checks.
- Human speech/echo/noise, network transitions, long-session stability, battery endurance, and production distribution remain separate work.

No internal grade, model-assisted review, or development test count is a Samsung evaluation result.
