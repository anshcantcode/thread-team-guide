# What works, and what each claim means

[Home](../README.md) · [Start here](START_HERE.md) · [Setup](RUN.md) · [Code map](CODE_MAP.md) · [Team plan](TEAM_PLAN.md)

This guide describes the application inspected on **16 September 2026**, including Android **0.6.0**. The status below comes from implementation and recorded project verification. It does not mean that every combination has been freshly tested today.

## Conversation and task handling

| Capability | What is implemented | Boundary |
|---|---|---|
| Live voice | Continuous microphone streaming and model audio replies, with local speech detection and playback control. | New voice understanding and replies depend on Gemini, network access, and quota. |
| Interruptions | Pause speech on suspected user speech; confirm genuine input; retain or replace relevant task state. | Human accent, echo, room-noise, and physical latency testing remain important. |
| Corrections | Retain unaffected details and supersede dependent pending work. | Supported task schemas and bounded interpretation; not perfect understanding of every phrase. |
| Action control | Current-result checks, explicit authorization, duplicate suppression, and outcome tracking. | A submitted external effect cannot be undone simply by stopping speech. |
| Task inspection | Native task card/detail sheet, retained/changed constraints, operation state, and pause/resume/stop controls. | These are distinct task controls; a confirmed effect needs its own reversal when supported. |
| Shared context | Camera, photo picker, and Android share entry points for deliberately supplied context. | No silent inspection of other apps or continuous screen surveillance. |

## Useful result families

The shared capability layer has **14 consumer capability definitions**, plus **3 fictional service scenarios**. A capability definition is not a count of independent integrations or fully tested user journeys.

| Family | What the user gets | Data and limits |
|---|---|---|
| Weather | City forecasts, weather details, and widget content. | Open-Meteo; named city/country, up to seven days. |
| Sports | Team/player profiles, dated results, sport-specific statistics, portraits and source identity where available. | Public sources including ESPN and Cricbuzz; coverage varies by sport and record. Missing rows must remain explicit. |
| Web and news | Source links, snippets, publisher information, and available timestamps. | Separate source discovery; snippets are not full articles. |
| Research | Encyclopedia, scholarly-paper, and book discovery. | Wikipedia, Crossref metadata, Open Library. Not automatic full-paper analysis. |
| Calculation | Arithmetic, percentages, splits, and supported mathematical functions. | Bounded local calculator; no arbitrary code execution. |
| Unit conversion | Compatible physical-unit conversion. | Unsupported or incompatible conversions are rejected. |
| Currency | Amount conversion with a dated rate. | Frankfurter reference rates; not a live bank quote or a financial transaction. |
| Date arithmetic | Add days, compare dates, and count weekdays. | Weekday counting excludes weekends, not public holidays. |
| Time conversion | Convert a specified date/time across time zones. | Uses IANA zones and checks daylight-saving ambiguity. |
| World clocks | Current time in one to four locations. | Native TextClock widgets continue ticking locally after setup. |
| Workspace timer | A visible countdown. | Does not ring as a background alarm. Use Android Clock for an actual alarm/timer. |
| Working documents | Plans, itineraries, checklists, recipes, comparisons, writing, study material, code drafts, and briefs. | AI drafts; generating a plan does not book travel, send messages, or execute code. |
| Notes | Preview, then explicitly save a note to the local notebook. | Persistent local write; requires current authorization. |
| Saved-note search | Search or list notes deliberately saved in THREAD. | Does not search another app's notes, phone files, or private messages. |

Cards are more than a title and paragraph: the app supports dedicated result views, detail navigation, source links, saved Library content, and appropriate widget layouts. Their content should stay personal through the user's request and saved work, without pretending we have access to undisclosed personal data.

## Android integrations and workspace

| Area | Current behavior | Status / limit |
|---|---|---|
| Google search | Query-preserving all/images/videos/news handoffs and tab corrections. | Actual typed-model/device sequence recorded. Handoff is not arbitrary website automation. |
| YouTube / Spotify search | Open the supported search destination, with web fallback. | Search handoff is separate from authorized Spotify playback. |
| Clock | Native alarms/timers through Android's supported destination. | Distinct from the visual workspace timer. |
| Phone destinations | Open an app, Maps, dialer, SMS/email compose, or a calendar draft. | Draft/open receipts do not mean a call happened, a message was sent, or an event was saved. |
| Device controls | Media volume, permissioned flashlight, and Android settings panels. | Bounded public Android APIs, not privileged control of every setting. |
| Library | Retained result cards, text, and checklist state. | Device-local storage; not cross-device synchronization. |
| Home-screen widgets | Preview and pin content from one or two result cards; supported clocks, sports, weather, checklists, sources and other layouts. | Samsung's final pin confirmation is required. Read-only refresh retains older data on failure and shows its age. |
| Phone backend | Python task engine embedded in the Android app with encrypted app-private configuration. | Android can reclaim idle processes. New cloud requests still require internet. |
| Spotify personal playback | PKCE authorization flow, top-track request, and playback/repeat controls are implemented. | **Pending real integration verification:** the owner has Premium but no Developer app is registered yet. |

Spotify's “top tracks” are a ranking for a requested listening period, not exact lifetime play counts. A developer registration, user authorization, and an active controllable playback device are still needed before an end-to-end success can be claimed.

## Fictional services used to prove the controller

| Scenario | What is simulated | What is real in the test |
|---|---|---|
| Flights | Inventory, fares, reservations, and service references. | Constraint correction, selection, authorization, cancellation, and outcome accounting. |
| Meeting rooms | Availability and reservations. | Schema-driven task state and bounded tool execution. |
| Device support | THREAD R1 device/manual and support tickets. | Current-image/target handling, evidence binding, and grounded responses to the supplied manual. |

These are not integrations with airlines, an office booking system, or Samsung customer support. Airline logos and sample details in presentation media do not change that status.

## Evidence worth knowing

| Recorded evidence | What it supports | What it does not establish |
|---|---|---|
| Android 0.6 final native suite: **28 passing checks** | Packaged backend, native behavior, storage/configuration checks, and supported fixture-driven flows. | Every provider, every device, or every spoken request. |
| Android 0.6 backend regression: **603 passing tests** in desktop and portable dependency environments | Broad backend regression coverage. | 603 independent real conversations or Android binary equivalence. |
| Two passing optimized-release microphone cycles | Capture, mute/unmute, end, and cold restart on the S24, with the embedded backend. | Human listening quality, measured barge-in latency, or battery endurance. |
| Actual typed Gemini/device sequence | Google tab correction, retained demo-travel correction, pause/resume, and Spotify connection-needed behavior. | Successful Spotify authorization/playback or acoustic-input evaluation. |
| Earlier Theme 05 deterministic replays | Six scenario families over 50 seeds; 300 scenario/seed combinations and 1,200 total repeated/fresh-process executions. | Model comprehension or Samsung's undisclosed evaluation suite. |
| Earlier 30-case model acceptance corpus | Authored text/audio/image regression behavior on its recorded source/model. | Population accuracy, fresh holdout performance, or automatic coverage of later Android changes. |

See [Validation](VALIDATION.md) for newly executed public-source checks. The device and historical model reports described above are team-held records, not included raw in this repository. Do not reuse a historical number as a fresh result for changed code.

## Still open

- Confirm the official Samsung evaluation kit, transport contract, permitted models/network access, and clean execution process.
- Run a deliberate human test session for speech timing, accents, speaker echo, noise, and interruptions during provider delays.
- Register the Spotify Developer app and verify real consent, playback, repeat, and failure behavior.
- Complete presentation/submission details with the team's actual names and required forms.
- Establish production signing, distribution, endurance, and operational readiness before treating the review APK as a public release.

Always-on wake words, offline Gemini, arbitrary control of third-party apps, live airline purchases, and the entire feature backlog are outside the current completed scope.
