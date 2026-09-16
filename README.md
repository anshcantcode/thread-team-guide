# THREAD

### Ask. Interrupt. Keep going.

THREAD is a real-time voice assistant that keeps the underlying task consistent when you change your mind. It has a native Android app, a browser workspace, rich result cards, home-screen widgets, and a shared task engine.

This repository is the **team onboarding guide**. Start here to understand what we have, try the important flows, and choose a part of the project to work on. The runnable application source and build artifacts are a separate handoff from Ansh; cloning this guide alone will not install the app.

**Project snapshot:** 16 September 2026 · Android **0.6.0** · Samsung PRISM **Theme 05** · four-person team.

## The idea in one conversation

> **You:** Find flights from Chennai to Delhi, tomorrow after nine.
>
> **You, while the search is running:** Actually Mumbai. Keep the date and time.
>
> **THREAD:** Changes the destination, preserves the other details, and excludes the obsolete Delhi result.

The flight inventory is fictional. What matters is the real controller behavior underneath it: an old answer or an old permission must not cause the wrong action. A later correction cannot undo an action already submitted, so the engine also tracks outcomes and reports uncertainty honestly.

That is our central hackathon story. Weather, sports, research, useful documents, phone actions, and personal widgets make the same interaction useful in daily life.

## Start here

| You want to… | Read this |
|---|---|
| Understand the product and try it in 15 minutes | [Start here](docs/START_HERE.md) |
| See what works, what is simulated, and what still needs work | [Capability and status guide](docs/WHAT_WORKS.md) |
| Run the browser app, install Android, or run a first check | [Setup and troubleshooting](docs/RUN.md) |
| Find the right files without reading the entire codebase | [Code map](docs/CODE_MAP.md) |
| Pick a team responsibility and prepare the demonstration | [Team plan and demo](docs/TEAM_PLAN.md) |

**Recommended first session:** read this page → try the five-minute tour → open the code map → pick one small task with a visible result.

## What we have today

| Area | Current position |
|---|---|
| Android app | Native Kotlin/Jetpack Compose app. The shared Python backend runs inside the app. Verified on a Galaxy S24. |
| Live conversation | Gemini Live audio, local speech detection, interruption handling, typed input, and an active voice dock beside results. Internet and API quota are required for new model requests. |
| Useful results | Weather, sports, source discovery, calculations, conversions, clocks, documents, and saved notes. Coverage and data freshness depend on the specific provider. |
| Personal workspace | Library, checklists, and Android widgets created from one or two supported result cards. Saved content persists locally. |
| Android actions | Bounded handoffs and device controls: search tabs, app opening, Clock, Maps, dialer, message/calendar drafts, media volume, and flashlight. |
| Task engine | Retained corrections, obsolete-result rejection, explicit action authority, duplicate protection, and outcome reconciliation. |
| Hackathon scenarios | Fictional flight booking, meeting-room booking, and device-support services for testing task behavior. |
| Spotify | Integration implemented; real account authorization and playback still need a registered Developer app and verification. |
| Presentation media | A 43-second landscape product film and a separately composed vertical cut exist in the application workspace. |

## What the team should focus on

1. **Prove the interruption behavior.** Show what happens to pending work, selected results, permissions, and effects when the user corrects a request.
2. **Make the real phone experience dependable.** Test actual speech, interruptions, noisy environments, and provider failures on the S24.
3. **Connect the submission to the organizer's requirements.** Validate the official evaluation interface and execution rules when the exact kit is available.
4. **Show useful outcomes clearly.** A result, its source, and the next action should be understandable without a technical explanation.

The large feature catalog in the application workspace is a backlog. It is not a list of completed features. The internal test reports are development evidence, not a Samsung score or a guarantee of winning.

## Getting the application

Ask Ansh for the **full application checkout** or the current review APK. The source checkout must include `thread_agent/`, `android/`, `web/`, `tests/`, and `scripts/`. Follow [Setup](docs/RUN.md) from that checkout's root.

To get a local copy of this guide once your GitHub account has repository access:

```powershell
git clone https://github.com/anshcantcode/thread-team-guide.git
```

This repository contains documentation only. No API keys, personal notebook, device logs, or application commit history are included.
