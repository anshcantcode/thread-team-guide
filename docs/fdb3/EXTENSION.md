# Tethered kitchen checklist and timer handoff diagnostic

The desktop LiveKit audio path uses the same ParticipantAgent and ControllerBridge
as the benchmark. Its extension registry invokes a debug-only Android Activity on
an explicitly selected, owned emulator. This is not a standalone APK voice agent.

The native Activity persists checklist items, checked state and request receipts
inside the app. Timer requests reserve a durable journal entry before invoking
the existing PhoneActions Clock intent. `handed_off` explicitly does not confirm
that Clock created a timer. There is no Clock readback, update or cancellation API;
a second timer request in the same session is blocked after handoff or unknown
outcome. Do not imply that cleanup cancels a timer.

Speech about effects comes from actual native receipts. Model response and
clarification fields cannot assert device completion. Input changes invalidate
queued requests, and the registry checks the captured input sequence before
device submission. Already submitted effects retain their outcome. This is not
a distributed exactly-once guarantee across arbitrary device/system failures.

Current verification: provider-free Python regressions pass, including shared
controller integration, unknown outcomes, superseded commands and forged
completion prose. Android build and 7 JVM tests passed; all three authored
instrumentation tests passed on an owned read-only emulator. Instrumentation
tests inject a Clock callback and do not create a real timer.

A separate actual device probe verified a checked checklist survived app restart,
repeated request identity did not duplicate an item, and a replacement timer was
blocked. Its screenshot shows a 00:33 countdown labelled THREAD local diagnostic.
That observation is external evidence of a timer, not a new runtime readback API.
See `evidence/android-validation.json` and `evidence/native-extension001-device.png`.
Session cleanup returned nonzero and was retained; the owned read-only emulator
was then terminated. A later owned read-only emulator ran the actual audio route:
`extension-audio003` passed its basic checklist control, including received spoken
output and one separately logged read after restart. Its screenshot is the launcher,
not checklist proof. Correction004/007 failed; timer005 lost its receipt;006 is
invalid because source changed during execution. All remain in raw history.
Command-level transport evidence exposed an adb reconnect race; the new bounded
readiness wait does not replay actions. Latest-source timer/correction validation
and the interruption video remain incomplete.

Fresh timer010 passed the local handoff control after declaring the native
transport allowance: exactly one47-second/lentils request, successful Android
handoff receipt, and captured speech explicitly saying timer creation is
unverified. The controller retains its30.5-second cap and no-retry behavior.
Timer008's earlier unknown reply preceded its late successful receipt and remains
in history; an additional receipt inspection is explicitly counted. Correction009
failed0writes: correct replacement argument but fabricated quote, with an earlier
cancellation transcript dropped as stale. The correction and video gates remain
incomplete. These tethered synthetic-audio controls are not physical-device or
standalone Android-agent evidence.

After resource checks, build from the worktree root:

```powershell
$env:JAVA_HOME='C:\Program Files\Android\Android Studio\jbr'
$env:ANDROID_HOME='C:\Users\ANSH\AppData\Local\Android\Sdk'
.\android\gradlew.bat -p android --offline :app:assembleDebug :app:assembleDebugAndroidTest
```

Install only on the verified owned emulator. Run
`com.thread.app.Fdb3ExtensionDeviceTest` with AndroidJUnitRunner. Then use an
independently authored input recording with `scripts/fdb3_extension_run.py`
(`--serial`, `--adb`, `--audio`, `--whisper`, `--output`). Its help explains the
explicit session cleanup. Synthetic speech must be labeled synthetic; it cannot
substitute for consented human interruption evidence. G7 remains incomplete.
