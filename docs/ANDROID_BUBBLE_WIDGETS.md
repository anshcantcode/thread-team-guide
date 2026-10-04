# Android floating bubble and Widgets 2.0

## Scope and source

Engineering work in an isolated checkout, based on integration commit `665b646`.
The named base did not yet contain the orb, so the orb commit
`d05efe75ea0ed84a52c0a1179ed282ca63ada927` was cherry-picked unchanged. No other worktree, benchmark source, private `.thread-run` state,
credentials or release configuration was edited. Local commits only.

Targets the existing minSdk 31 / targetSdk 36 app. Physical qualification on the
Galaxy S24 (Android 14+) is **not established** by JVM tests or APK assembly.
No emulator, device, GPU, benchmark or hosted-model run is part of this task.

## Features and engineering boundaries

### Floating bubble (off by default)

- Settings → **Floating bubble** explains captions, overlay permission, microphone
  behavior and the persistent Stop notification. There is also a direct link to
  Android's **Display over other apps** permission screen. Permission by itself
  does not opt in. Notification denial leaves the toggle off.
- A 64 dp `ComposeView` renders the shared `LivingSphere` → `ThreadOrb`. It uses the
  same `ThreadModel`, phase mapping, levels, event counts and expressive setting
  as the main app. No replacement artwork, color/preset changes or new audio
  recorder are introduced.
- Tap an idle bubble: bring THREAD onscreen, obtain any outstanding consent and
  microphone permission, then start voice. A new Android 14+ microphone foreground
  service is not started from an overlay-only background context. Tap an already
  active microphone session: unmute; when speaking, use the existing floor-yield
  and playback-interruption path. No synthetic transcript or text command is sent.
- Long-press opens THREAD. Drag moves the bubble; release snaps it to the nearest
  safe left/right edge. Position is saved. The bottom **×** appears only while
  dragging; dropping on it removes the bubble, ends voice and clears opt-in.
- The latest actual caption appears in a separate, non-touchable two-line chip
  above the bubble. It is not an action receipt. Empty captions show no chip.
- Bounds include status/navigation bars, display cutouts and gesture insets; the
  system's reported IME inset is also respected, and the non-focusable windows
  are explicitly layered below the keyboard (`FLAG_ALT_FOCUSABLE_IM`). The overlay is non-focusable,
  hidden on screen-off/keyguard, and recreated on configuration changes without
  creating another session. It never draws above privileged system windows.
- Accessibility actions expose Talk/interrupt, Open THREAD, Dismiss/end voice and
  moving to either edge. No animated snap or entrance is added.
- Light tick on listening entry; confirm only on a **new stored completed phone
  receipt**. Both honor the existing Haptic feedback setting. Historical receipt
  load, repeated snapshots, captions, requests, prepared operations and unverified
  handoffs do not trigger receipt confirmation.

`ThreadApplication` owns the shared `ThreadModel` through a process-lifetime
`ViewModelStore`. MainActivity, widget configuration and the bubble use that same
instance. Activity recreation no longer owns microphone teardown. `VoiceService`
must successfully enter microphone foreground mode before capture is enabled.
Duplicate `live_ready` events cannot allocate another `LiveAudio` pipeline.
Opening Kitchen through its widget ends the normal conversation before Kitchen
can start its separate, pre-existing host-backed session.

**Stop behavior:** the bubble notification's **Stop** and drag-to-× end voice and
remove/disable the bubble. Turning off the toggle removes only the overlay; an
existing voice conversation retains its own **End conversation** notification.
Neither service is sticky. There is no boot receiver or automatic microphone
restart. An enabled bubble may be restored when the user next opens THREAD.

### Reduced motion API addition

`ThreadOrb(..., motionEnabled: Boolean = true)` and the forwarding optional
`LivingSphere(..., motionEnabled: Boolean = true)` preserve existing call sites.
The overlay observes Android's animator-duration setting and passes the current
motion preference. Disabled motion freezes the shader frame clock and suppresses
event pulses; the original shape, shader source, palette and phase presets are
unchanged. The Android 12 artwork fallback is also stationary. Previously, the
shader's background clock kept advancing even when its speed was set to zero.

### Widgets

The existing `RemoteViews` layouts, artwork, configuration flow and one-tap Talk
widget are retained. Widgets are **not** animated Compose surfaces. Add the new
providers from the launcher's THREAD widgets or from THREAD → Widgets.

| Widget | Real source | Behavior |
| --- | --- | --- |
| Now doing | `files/workspace.json`: task, active action, workspace receipts | Task/request plus last stored phone-action receipt. Disconnected state is labeled saved; a running request is never called completed. Handoffs remain explicitly unverified. Tap opens task details. |
| Talk | Existing direct activity PendingIntent | One tap opens THREAD's consent/permission-aware voice path. Reuses an existing session; it does not start another recorder. |
| Watches | `WatchStore`, `files/watches.json` | One row per Watch, selecting the latest retained article referenced by a successful check's `new_ids`. Baseline articles are not promoted to new updates. Tap a row opens that Watch; header opens all Watches. Failed checks and stopped Watches retain honest labels. |
| Kitchen checklist | Active `fdb3-client.session` and `fdb3-<session>.items` private preferences | Count of actual checked booleans and next unchecked step. Read-only widget; tap opens Kitchen. Does not instantiate `Fdb3ClientStore`, change input authority, replay a tool or submit any checklist action. |

Saving workspace state, a successful Watch-store mutation or a checklist change
triggers a coalesced local widget update. A single low-priority worker performs
widget reads/rendering. New widgets also refresh on launcher update/resize and
have a 30-minute platform fallback; Android may defer that fallback. Rendering
does not perform a network request or create a Watch check. Missing state has a
useful empty message; unreadable state says unavailable and is not deleted.

## Permissions and service declarations

New manifest permissions:

1. `android.permission.SYSTEM_ALERT_WINDOW`: explicitly granted in Android
   settings for the opt-in overlay.
2. `android.permission.FOREGROUND_SERVICE_SPECIAL_USE`: Android 14+ foreground
   overlay lifetime. `FloatingBubbleService` declares `specialUse` and the required
   `android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE` description identifying the
   user-enabled overlay controls/captions and separate microphone service.

Existing permissions reused: `FOREGROUND_SERVICE`,
`FOREGROUND_SERVICE_MICROPHONE`, `RECORD_AUDIO`, `POST_NOTIFICATIONS`, and
`VIBRATE`. `VoiceService` remains `microphone`; the overlay service itself never
captures audio. Services are non-exported. Widgets need no overlay permission.
The stop notification is required for enabling the bubble in this implementation.

The split follows Android's [foreground service type requirements](https://developer.android.com/develop/background-work/services/fgs/service-types)
and [while-in-use microphone/background-start restrictions](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start).
Play distribution and review of the `specialUse` declaration are not claimed.

## CPU-only verification

Run one Gradle invocation at a time across tasks. Atomically acquire
the shared `gradle.lock` file, write this task's name, run the
launcher at BelowNormal priority, and remove only that owned lock in `finally`.
From `android/`:

```powershell
.\gradlew.bat :app:testDebugUnitTest :app:assembleDebug --max-workers=1 --no-daemon -Dorg.gradle.jvmargs=-Xmx1536m -Dkotlin.compiler.execution.strategy=in-process
```

New pure Kotlin/JVM tests cover safe-area clamping and snapping, rotated/tiny
bounds, dismiss-target proximity, opt-in/permission and microphone-service gating,
haptic transition/replay behavior, stored task/receipt selection, Watch baseline
versus real new articles across restart/failure, store update callbacks, and
checklist progress/invalid state. The full existing Android JVM suite is also run.

Build attempts and their failures are retained locally under `.runtime/`; generated
logs, caches, test reports and APKs are not committed. Final results are recorded
below after the verification run, without implying device checks passed.

Retained intermediate failures: attempt 1 stopped on an ambiguous platform/Compose
`WindowInsets` import; attempt 2 stopped on a Kotlin property-setter signature
collision. Attempt 3 compiled and ran 40 tests, with 38 passing and two existing
Watch tests failing because the newly added trailing constructor callback captured
the tests' clock lambda. The fix restored the original constructor unchanged and
made the optional notification callback a property. No existing test was weakened.
That failing XML/HTML report is kept in `.runtime/s5-attempt-3-test-*`, alongside
the attempt logs. Later review also separated bubble permission messages from the
voice retry flow and explicitly placed overlay windows below the IME.

## Galaxy S24 manual test script — not executed by this task

Use a development S24 on Android 14 or newer, the debug APK, and an owner-configured
voice backend/key. Live voice consumes the owner's existing quota; these steps
are a manual script, not authorization for this task to spend or run them.

1. **Install/upgrade and idle:** open THREAD, confirm existing results/Watches/
   Kitchen state survive. No bubble or microphone appears before opt-in. Add
   widgets with no stored data and check their empty states.
2. **Permission denial:** Settings → Floating bubble → Continue. Deny notification
   and then overlay permission in separate attempts. Toggle must remain off;
   no overlay, microphone or crash. Allow notifications and Display over other
   apps, return, and explicitly enable the toggle. Verify explanation and Stop.
3. **Idle bubble:** go Home and into another ordinary app. Verify a ~64 dp orb,
   no microphone privacy indicator and no new voice session. Long-press opens
   THREAD. Tap starts through THREAD and prompts for any missing consent/mic grant.
4. **Shared session:** start one conversation, return Home, speak. Compare orb
   state/level and last caption against THREAD. Reopen/rotate/recreate the activity;
   there must be no doubled playback, echo or second voice session.
5. **Barge-in:** while THREAD is audibly speaking, tap the bubble and give a
   correction. Playback must stop through the existing interruption path, old
   queued speech must not resume, and the new utterance must be handled once.
   Repeat with mute/unmute and while connecting; repeated taps must not add sessions.
6. **Position and system UI:** drag to all edges/corners in portrait/landscape,
   gesture and three-button navigation, enlarged fonts and a visible keyboard.
   Bubble/chip must remain clear of system bars/cutouts; release snaps to the
   nearest side. Other app touches outside the small overlay windows must work.
7. **Dismiss:** drag close to, but not onto, × and release (must snap, not dismiss).
   Drag onto × (must remove bubble, stop voice and clear opt-in). Re-enable; test
   notification Stop with THREAD backgrounded. Confirm microphone indicator ends.
8. **Toggle off during voice:** overlay disappears; the same voice session remains
   with its End conversation control. End it and verify capture stops.
9. **Lock/revocation:** lock/unlock while enabled; no orb or caption on the lock
   screen. Revoke overlay permission while running; overlay and its voice session
   must stop. Force-stop THREAD: no automatic restart or recording. Reopen and
   inspect the toggle/notification state. Check notification-channel denial too.
10. **Reduced motion and accessibility:** with the bubble showing, enable Android
    Remove animations / set animator scale to zero. It must stop continuous orb
    motion and pulses. Re-enable animations. With TalkBack, test named Talk,
    Open, Dismiss and edge-move actions. Check large-text caption truncation.
11. **Haptics:** enable Haptic feedback; entering listening gives a light tick and
    a genuinely completed stored phone action gives confirm. A request, caption,
    failed action or timer handoff must not produce receipt confirmation. Reopen
    the bubble: historical receipts must not vibrate. Disable haptics and repeat.
12. **Now doing/Talk:** pin both; perform an actual task and observe automatic
    saved-state updates. Check a pending/failed action and a handoff retain their
    true status. Tap Now doing for task details; tap Talk from idle and active
    sessions, including after denying microphone permission.
13. **Watches:** create two Watches. First checks silently save baselines; widget
    must not call those articles new. After a genuinely new item is stored, check
    each row and its exact Watch destination. Check stopped, no-new-news, offline
    failure and process-restart cases; previously saved updates should survive.
14. **Kitchen:** pin progress; open Kitchen and add/check steps through its real
    host-backed flow. Compare checked count/next item with stored checklist,
    including all-checked and empty. Tapping the widget must not itself write or
    replay anything. Opening Kitchen during a normal voice call ends that call.
15. **Widget lifecycle:** resize/remove/re-add all widgets, restart the launcher,
    and test without network. Data should remain local and labeled saved; missing
    or malformed test-fixture storage must show unavailable, not fabricated success.

## Known limits

- Physical touch/overlay lifecycle, One UI placement, audio/barge-in/acoustics,
  haptics, TalkBack and launcher behavior require the S24 script above. JVM tests
  cannot establish these. No GPU rendering or instrumentation was run here.
- Starting a **new** microphone session opens the activity; the overlay is not a
  background microphone-permission exemption. Background phone-app actions still
  need THREAD foregrounded, as before. The bubble does not grant extra authority.
- Only the latest two caption lines fit. Other apps can request that overlays be
  hidden. Keyboard inset reporting and OEM battery restrictions can differ.
- Now doing's receipt line currently selects stored **phone-action** outcomes;
  general research results and generated documents are not promoted to receipts.
  Watches can only show new articles retained in the bounded existing history.
- Widgets are local snapshots, not animated live voice visualizations. They are
  updated after durable saves, not at microphone frame rate. Periodic fallback
  timing is subject to Android/launcher scheduling.
- Kitchen progress covers the active app Kitchen session, not every diagnostic
  session. Its existing local host requirement is unchanged.
- Debug signing is for local review, not Play publication. No push, release,
  submission, live qualification or transferred benchmark score is claimed.

## Verification outcome

- Final source run: `.runtime/s5-build-attempt-6.log`, **BUILD SUCCESSFUL in 30s**.
  Both requested tasks completed with one Gradle worker, a 1536 MiB JVM cap,
  BelowNormal launcher/Java priority and the exclusive shared lock. The lock was
  released. An intervening lock contention returned without starting Gradle.
- **40 JVM tests passed, 0 failures, 0 errors, 0 skipped** across eight suites.
  This includes 14 new bubble/widget tests, three imported orb mapping tests,
  and the 23 existing Android tests. Reports are in
  `android/app/build/reports/tests/testDebugUnitTest/`.
- APK: `android/app/build/outputs/apk/debug/app-debug.apk`, **147,517,284 bytes**.
  SHA-256: `eed940dde3d3d1be777d0284786c80cb784ad008b59f68af89257b225b930e16`.
- APK ZIP integrity and v2 signing verification passed. Embedded manifest inspection
  confirms the non-exported overlay/voice services, `specialUse` subtype property,
  required permission declarations, application owner and all three new providers.
- All **33 embedded backend-source manifest hashes** match this checkout. The
  Chaquopy application payload contains 33 compiled files under `thread_agent/`,
  including its phone entrypoint. It does not contain raw `.py` source, so this is
  an input-manifest identity check, not a claimed source-byte/bytecode equivalence proof.
- Package name checks found no private state, signing keystore or private-key files.
  The initial checker falsely rejected the two bundled `cacert.pem` files; inspection
  confirmed public certificate bundles without private-key markers and that failure
  is retained in `.runtime/s5-package-check-attempt-1.txt`. No personal credential
  was read or used for this check. Accounting is in `.runtime/s5-verification.json`;
  signature/manifest inspection is in `.runtime/s5-apk-{signature,manifest}.txt`.
- No physical S24, emulator, instrumentation, GPU render, live microphone, hosted
  inference or benchmark check was run. Those outcomes remain **unverified**.
