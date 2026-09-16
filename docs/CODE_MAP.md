# Find your way through the code

[Home](../README.md) · [Start here](START_HERE.md) · [What works](WHAT_WORKS.md) · [Setup](RUN.md) · [Team plan](TEAM_PLAN.md)

All code paths on this page are **relative to the separate application checkout**, not this documentation repository. Read one path for the behavior you care about; there is no need to open every file first.

## The whole system

```text
Android app                           Browser workspace
Compose UI / microphone / playback    HTML / JavaScript / audio
          |                                    |
Embedded Python backend               Desktop Python server
          |                                    |
          +-------- shared THREAD logic -------+
                             |
              Model interpretation / Live voice
                             |
              Task state and action authority
                             |
       Local tools / public providers / fictional services
                             |
               Structured results and outcomes
                             |
               Cards / voice / Library / widgets

Theme 05 adapter -> asynchronous event/action queues -> same task engine
```

The model proposes interpretations and tool requests. Controller and authority checks determine whether a result or action is valid for the current request. Native phone actions have their own checked handoff path.

## Core backend

| File | Why you would open it |
|---|---|
| `thread_agent/engine.py` | Task state, retained constraints, revisions, selections, pending work, and effect tracking. Start here for “what happens when I interrupt?” |
| `thread_agent/authorization.py` | Explicit permission and bounded action-language rules. Start here for “why did it execute/refuse a write?” |
| `thread_agent/planner.py` | Model interpretation, configuration, and provider-facing planning behavior. |
| `thread_agent/protocol.py` | Typed event/tool/manifest contracts and validation. |
| `thread_agent/adapter.py` | Asynchronous input/output queues and scenario isolation. |
| `thread_agent/stdio.py` | JSONL boundary for the provisional evaluation adapter. |
| `thread_agent/live.py` | Live audio session, tool dispatch, and native spoken-action verification. |
| `thread_agent/server.py` | Desktop HTTP/WebSocket entry points and app endpoints. |
| `thread_agent/android_backend.py` | Embedded phone-backend startup and phone-specific configuration/storage integration. |
| `thread_agent/media.py` | Deliberately supplied audio/image input processing. |
| `thread_agent/clock.py` | Real and virtual clocks used by runtime and replay. |
| `thread_agent/fixtures.py` | Fictional flight, room, and support scenario definitions. |
| `thread_agent/sandbox.py` | Mock services and inspectable action outcomes. |

## Tools and integrations

| File | Responsibility |
|---|---|
| `thread_agent/capabilities.py` | Consumer capability schemas, local calculations/conversions, weather/research, documents, and explicit notebook writes. |
| `thread_agent/sports.py` | Sports identity, provider data, coverage, and result shaping. |
| `thread_agent/cricket.py` | Cricket-specific records and filtering. |
| `thread_agent/online.py` | Online source discovery and related public-data behavior. |
| `thread_agent/phone.py` | Bounded Android action declarations and validation. |
| `thread_agent/spotify.py` | Spotify connection, API requests, playback state, and partial/unknown outcome handling. |

A new card should start with a real user job and a clear result contract. Add a provider/tool only when the required information is not already available. Keep source identity, dates, partial coverage, and actual effect status visible through to the UI.

## Android

The files below are under `android/app/src/main/java/com/thread/app/`.

| File | Responsibility |
|---|---|
| `MainActivity.kt` | Application entry point and activity integration. |
| `ThreadModel.kt` | Native application state and coordination. |
| `ThreadUi.kt` | Main Compose screens and result presentation. |
| `TaskCard.kt` | Task card and inspection UI. |
| `LiveAudio.kt` | Microphone/playback pipeline. |
| `NeuralVad.kt` | Local Silero speech detector through ONNX Runtime. |
| `VoiceService.kt` | Foreground lifecycle for an active microphone conversation. |
| `ThreadBackend.kt` | Embedded-backend bridge and private configuration integration. |
| `PhoneActions.kt` | Native handoffs and supported device controls. |
| `WidgetContent.kt` | Content and layouts for widgets. |
| `ThreadWidget.kt` | Widget providers, actions, and refresh behavior. |
| `WidgetConfigurationActivity.kt` | Launcher/widget configuration flow. |

`android/app/build.gradle.kts` stages only the intended Python source into the app. `android/requirements-phone.txt` pins the phone dependency set. `android/app/proguard-rules.pro` includes necessary ONNX JNI preservation; removing it can break the optimized microphone path even when debug tests pass.

## Follow one correction end to end

Use “Chennai to Delhi” → “Actually Mumbai” as your reading exercise:

1. **Input arrives.** Identify the typed or spoken request and its current input/session identity.
2. **Interpretation is proposed.** Inspect the parsed change and retained context.
3. **Task revision changes.** The controller keeps origin/date/time and changes destination.
4. **Dependent work is superseded.** Old reads cannot deliver an active result just because their provider returns late.
5. **Result and selection update.** Actions must refer to the current result/option.
6. **Permission is checked.** Permission prepared for an obsolete selection cannot authorize the replacement.
7. **Submitted effects remain accounted for.** An unresolved service outcome is not permission to retry a write blindly.
8. **UI shows the real state.** Inspect the task card and outcome history, not only the assistant's words.

Start with `tests/test_theme5.py`, `tests/test_engine.py`, and `tests/test_authorization.py` to see the behavior in executable examples before editing the engine.

## Tests by area

| Your change | Start with |
|---|---|
| Task correction / effect handling | `tests/test_engine.py`, `tests/test_authorization.py`, `tests/test_theme5.py` |
| Spoken action permission | `tests/test_native_authority.py` |
| Provider errors / cancellation | `tests/test_provider_recovery.py` |
| Useful tools | `tests/test_capabilities.py` |
| Phone and smart actions | `tests/test_phone.py`, `tests/test_smart_actions.py` |
| Sports | `tests/test_multisport.py`, `tests/test_cricket.py` |
| Widgets / clocks | `tests/test_widgets.py`, `tests/test_world_clocks.py` |
| Embedded phone runtime | `android/app/src/androidTest/java/com/thread/app/PhoneBackendTest.kt` |
| Native results and widget interaction | `SportsProfileTest.kt`, `WidgetHostTest.kt` in the same Android test directory |
| Actual Gemini/device checks | Opt-in `ThreadLiveDeviceTest.kt`, `SmartActionsLiveDeviceTest.kt`, `WidgetLiveDeviceTest.kt`; read their scope before running. |

## Existing documents and evidence

| Application path | Use it for |
|---|---|
| `README.md` | Broad application setup and architecture. |
| `android/README.md` | Current Android build and device-test details. |
| `PHONE_BACKEND.md` | Embedded runtime, configuration, storage, and phone setup. |
| `SMART_ACTIONS.md` | Supported command flows and integration boundaries. |
| `EVALUATION.md` | Evaluation contract and test methodology. |
| `EVIDENCE.md` | Earlier reviewed Theme 05 candidate and precisely scoped historical evidence. |
| `reports/android-embedded-backend.md` | Android 0.6 installation, device, release-microphone, and package checks. |
| `reports/android-smart-actions.md` | Earlier smart-action iteration and actual-model/device checks. |
| `features.md` | Feature/card backlog; not a shipping-status document. |
| `THREAD_Product_Specification.md` | Product direction and design intent. |
| `motion/v2/SCRIPT.md` | Current 43-second film script. |
| `motion/v2/README.md` | Film outputs, rebuild path, and relationship to implemented behavior. |
| `motion/v2/VERIFICATION.md` | Export verification and review scope. |

For current Android setup, prefer `android/README.md` and `PHONE_BACKEND.md` over older demo instructions describing a laptop relay. A historical report or design document may accurately describe an earlier state without describing today's build.

`reports/` contains both successes and retained failures. `data/`, `.env`, `.runtime/`, and device-private storage are local state, not material to upload wholesale into a team guide.
