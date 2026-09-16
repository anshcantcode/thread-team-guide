# THREAD Android 0.6.0

Native Kotlin / Jetpack Compose application for Android 12+ (API 31+), tested on Samsung Galaxy S24 SM-S921B, Android 16 / API 36, One UI 8.5. All six visual flow boards were approved before implementation. The generated sphere is a transparent image asset with audio-driven native motion; controls, results, transitions, sheets and widgets are actual UI.

The backend now runs inside the Android app using embedded Python. Voice, smart actions and public widget refreshes work without a laptop or USB forwarding. Gemini and fresh public data still need internet access. The phone keeps its own encrypted Gemini key and private notebook. See [standalone phone setup and architecture](../PHONE_BACKEND.md) and [validation scope](../docs/VALIDATION.md).

## Smart actions iteration

The 0.5 build exposes the reviewed task controller in a native task card and detail sheet: current constraints, changed versus retained values, selection, operation status, unresolved effects and explicit pause/resume/stop controls. Saved cards remain inspectable from Home. Workspace-only sports refreshes preserve the current task. A device action also carries the exact local input ID; a queued action is refused if typing, new speech or ending the conversation has superseded it.

Google search handoffs support all/images/videos/news. A tab-only follow-up retains the query from the current live connection. A fresh search requires its own query; the model cannot replace a requested tab or provide an arbitrary destination URL. YouTube and Spotify search use native destinations with web fallback. Handoff receipts confirm Android accepted the destination, not that a web page finished loading or music played.

Spotify top-track playback and pause/resume/repeat controls use a local OAuth PKCE connection. Register a Spotify Developer app with the exact redirect `http://127.0.0.1:8767/api/spotify/callback`, then enter its public client ID under Settings → Connected apps → Spotify. This callback reaches the backend on the same phone. No client secret is needed. The user grants history/playback scopes in Spotify's browser. Tokens remain in expiring app-process memory and are cleared on disconnect/restart. Connecting never replays an old command; start a fresh voice session and ask again. Playback needs Premium and an active controllable Spotify device. Top-track ranking uses Spotify affinity for the visible period, not exact lifetime play counts. A submitted-but-unverified effect is unknown; an actually confirmed play followed by failed repeat is partial.

The owner has Premium but has not registered the developer app. The integration's simulated-provider tests do not establish real account authorization or playback. See [smart action workflows](../SMART_ACTIONS.md), [ImageGen reference](../design/smart-tasks/reference.md), and [validation scope](../docs/VALIDATION.md). Historical Theme 05 results remain separate from later consumer-app verification.

For the opt-in real-Gemini/Google phone check, run `com.thread.app.SmartActionsLiveDeviceTest` through the same instrumentation runner as the checks below. It opens Google search results, tests tab correction, and exercises a fictional travel correction and native pause/resume. It does not play Spotify music. It is excluded from the default device suite.

## Build and run

From the workspace root, with Android Studio's JDK/SDK installed and the phone connected using USB debugging:

```powershell
.\scripts\build-android.ps1 -Release -Install
```

APK: `app/build/outputs/apk/release/app-release.apk`. The optimized release variant uses the local debug signing key for review, not a production distribution key. USB is needed only to install/test this way; it does not carry backend traffic. On a fresh install, add a Gemini key in Settings. The existing S24 configuration can be migrated with the development-only procedure in [PHONE_BACKEND.md](../PHONE_BACKEND.md). Cleartext networking is restricted to loopback; external destinations require HTTPS.

The app starts its private backend automatically. Android can stop the process when it is idle; opening THREAD or running a widget refresh starts it again. The existing foreground microphone service keeps an active conversation foregrounded. This does not add an always-listening wake word or make Gemini an offline model.

## Implemented behavior

- AudioRecord sends continuous 16 kHz PCM with platform echo cancellation/noise suppression when available. AudioTrack plays the model's 24 kHz native voice. Typed requests also produce voice without opening the microphone. A foreground notification can end an active microphone conversation.
- Bundled Silero VAD v6.2.1 runs locally through ONNX Runtime on the microphone thread, after platform echo/noise processing. It detects speech rather than treating loudness alone as speech. Model provenance/license are in `MODEL_NOTICES.md`. Suspected speech pauses unheard audio. Actual words confirm the interruption and optionally trigger a quiet native acknowledgment. An empty interruption can resume retained audio and request one guarded continuation. The sphere follows measured audio amplitude; reduced-motion and haptic system settings are respected.
- Native result views display sourced weather, multiple sports, research/web records, computed values, documents and correctly marked demo inventory. New informational results open their native detail screen during an active conversation, retaining the compact voice dock. Back returns to the listening screen and View result reopens the latest card. The Library retains results and text, not raw audio. Camera, photo picker and Android share intents provide deliberately shared context.
- Typed device actions use current-request evidence and revision checks, with duplicate suppression. Clock receives alarms/timers; app names are resolved locally. Maps, calls, SMS, email and calendar use their native destinations. Calls/messages/calendar drafts remain for user review. Media volume and permissioned flashlight use public device APIs. Protected settings open Android panels.
- Voice or the Widgets screen's request field can create a widget from one or two result cards. All requested source rows reach the renderer. Native RemoteViews collections scroll; the preview uses a real AppWidgetHostView. Samsung owns the final pin confirmation, whose callback persists the actual widget ID and content. Launcher configuration/reconfiguration is connected, including widgets added from its picker.
- World clocks support up to four IANA zones in one result. TextClock ticks on the phone and handles DST independently of the relay; one/two clocks use a compact 4×2 provider. Sports shows the returned match/innings/race records, dates, scores, available player metrics, and cached source badges/portraits. Other layouts cover forecasts, calculations, conversions, reference rates, source/news collections, saved notes, plans, recipes, comparisons and checklists. Checklist completion persists on the phone and provides a short haptic tick. Countdown widgets are visual and do not ring; use the phone Clock action for a real alarm/timer.
- Read-only public refresh is scheduled through JobScheduler. A failed refresh retains all previous data and displays its age. Composed documents stay explicit saved AI drafts. Item taps open the actual saved result, including full sports detail and source links. The tap-to-talk shortcut starts capture only after a tap.

This is not unrestricted automation of all third-party apps, an always-on wake-word assistant, or privileged AppFunctions access. See [current capabilities and boundaries](../docs/WHAT_WORKS.md) for the scope of this build.

## Verification

```powershell
.\scripts\build-android.ps1 -Test
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" shell am force-stop com.thread.app
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" shell am instrument -w -e class com.thread.app.ThreadLiveDeviceTest com.thread.app.test/androidx.test.runner.AndroidJUnitRunner
.\scripts\build-android.ps1 -Release -Test
```

The 0.5 default suite passed 26 S24 checks: four smart-action checks, seven existing native UI/action tests, three local neural speech checks, five native sports-profile/format checks, and seven real AppWidgetHost checks (clock timezones/device time, all five sports rows and scrolling, checklist PendingIntent taps and persistence, native detail navigation, replacing an existing widget, offline refresh retention, launcher configuration). The separate actual-model smart-action sequence passed Google videos → images, Spotify connection-needed, retained travel correction, and native pause/resume handlers. See [validation scope](../docs/VALIDATION.md). The opt-in `ThreadLiveDeviceTest` previously passed actual native AudioTrack playback, a fresh calculation, and Samsung Clock foreground handoff.

The final `-Release -Test` step installs the minified, non-debuggable APK and runs `scripts/check_android_release.py`. It also builds/installs the tiny `ui-probe` helper, which reads only named call controls through Android accessibility in its own process. It has no dependency on the production app and never loads the app's classes or changes its R8 rules. This avoids Android's idle-screen dump failing during animated captions. The check requires the unlocked phone, existing microphone/cloud consent, its saved Gemini key and internet. Stop the laptop server and remove any old backend reverse mappings first: this check asserts both are absent. It opens two real microphone conversations and checks sustained audio capture, mute/unmute, end, and cold restart. The embedded backend emits only duration counters for the test to collect from that process's Android log; raw audio and captions are not logged. The result is `reports/android-release-microphone-check.json`. Debug instrumentation and typed live requests do not cover this release microphone path. `--relay` preserves the old backend-counter mode for historical APKs and still uses the separate UI observer.

Keep the ONNX JNI preservation rule in `app/proguard-rules.pro`. Removing it allows R8 to rename Java classes the native tensor conversion code finds by name, causing a process abort when microphone inference first runs. This release-only failure was observed on 13 September 2026 despite passing debug tests. The rule follows [ONNX Runtime's Android build guidance](https://onnxruntime.ai/docs/build/android.html#note-proguard-rules-for-r8-minimization-android-app-builds-to-work).

The separate **opt-in** `WidgetLiveDeviceTest` submits the user's exact clocks and Barcelona requests through the native Android client and actual Gemini Live, then clicks the real app preview and Samsung launcher confirmation. It successfully pinned clock widget 59 and sports widget 60 on the attached S24; `reports/android-widget-live-device.json` records the IDs, sources and saved content. This test **adds widgets to the device home screen** and is excluded from the default suite. Do not rerun casually or describe it as a microphone/acoustic test: its request input is typed.

`reports/widget-request-contract.json` separately covers earlier actual Gemini requests for clocks, five matches and a packing checklist with simulated preview acknowledgments. Recorded tool outputs used by deterministic device tests are labelled fixtures, not fresh network retrieval. The 0.6 regression run passes 603 backend tests, with two additional package-check tests also passing. The earlier three JavaScript suites, including 72 rendering/export checks, are retained historical evidence; no JavaScript renderer changed in this iteration. The optimized 0.6 build passes `lintVitalRelease`; earlier full Android lint results are separate evidence.

The app remains installed after default tests. Run the release microphone check afterward before handing over the optimized variant. API credentials remain in encrypted app-private phone storage and are excluded from the APK. The live widgets and native detail screens are implemented; this is still a prototype with explicit provider coverage, not a promise of every sport's every historic match or arbitrary private-app integration.

Human speaking/listening tests are still needed for accents, speaker echo, conversational timing and subjective haptic feel. A configured 96 ms speech threshold is not a measured guarantee for this physical microphone.

## Sports profiles and screen coverage

The F3 family now has publisher portraits and identity fields, flat selected-record metrics, and separate basketball, cricket, tennis and F1 columns. The same components accept other source-returned athletes; no list of demo names selects the layout. Baseball, hockey and American football also have their own column mappings. Cricket ODI/T20/Test/All controls call the public-data relay directly, update the visible records, and retain the previous data on failure without starting a voice connection. Missing identity fields are omitted, and partial record counts remain explicit.

`reports/android-sports-device-tests.log` records 22 passing S24 checks. The sports tests use recorded public-source responses and real native controls; they do not simulate a successful Gemini voice call. Four representative sports screens and their scrolled records were captured and visually inspected. These checks do not establish visual coverage for every test case or every possible player/sport. `reports/android-sports-review.md` links the screenshots and scope.

The extra actual-Gemini composition test in `reports/widget-composition-contract.json` passes a single widget containing Chennai and Tokyo weather. Its phone-preview acknowledgment is simulated. Sequential lookups now retain both subjects, while a new spoken correction may still supersede a pending lookup.

`ThreadLiveDeviceTest#realSportsRequestOpensProfileKeepsVoiceAndPreviewsWidget` is an additional opt-in actual-Gemini check. It verifies automatic profile navigation, the active voice dock, back/reopen navigation, and a five-record native widget preview without pinning another home-screen widget. The default 22-test suite excludes this network-dependent check. Its report is `reports/android-sports-live-device.json`.
