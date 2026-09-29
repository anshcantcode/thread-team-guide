# THREAD on the phone — Android 0.6

THREAD's task engine, validation, provider adapters and notebook run inside the Android app. The laptop and USB relay are no longer needed for normal use. **Gemini still runs in Google's cloud**, so real-time voice, interpretation and new AI content require Wi-Fi or mobile data and available API quota.

## Use it

1. Open THREAD. The installed S24 has its existing Gemini configuration migrated into encrypted private storage.
2. Tap **Start talking**, or **Type instead**. The backend starts automatically when needed.
3. Unplug USB and use the phone normally. Public-source widget refreshes also use the phone's connection.
4. To replace a key later, open **Settings → Your phone, independent**. Saving or removing a key ends the active conversation first.

On another phone, install the APK and enter that phone owner's Gemini key in Settings. No personal key is included in the APK. API quota and billing belong to that key's Google project; this migration does not change or enable billing.

## What runs where

| Component | Runtime | Internet needed? |
|---|---|---|
| Compose UI, microphone, playback, Silero speech detector and Android actions | Native Android | Native controls/detection work locally; new voice commands still need Gemini |
| Task state, constraint repairs, revision checks, authorization and tool execution | Embedded Python in the Android app process | Controller and local tools run locally |
| Gemini Live voice and multimodal interpretation | Google, contacted directly by the phone | Yes |
| Weather, sports, search, rates and Spotify APIs | Named external providers, contacted by the phone | Yes |
| Saved Library cards, text, checklist state and notebook | App-private phone storage | Existing saved content is local |
| World-clock widgets | Android TextClock | No, after setup |
| Desktop website and provisional hackathon adapter | Existing optional laptop runtime | Independent of the installed phone app |

There is no hosted proxy to deploy and no Termux session or separate phone server app to keep alive. This is the same Python controller used by the desktop and Theme 05 adapter, packaged for Android with a small validation compatibility layer.

## Runtime and storage

Chaquopy 17 embeds Python 3.11. The native client starts one Uvicorn thread inside its own process, bound only to `127.0.0.1:8767`. HTTP and both WebSocket paths require a random per-process native-client token. Native requests attach that token only to this exact origin and do not follow redirects. The callback described below is the single public route and still requires the one-use OAuth state before an account can connect.

The startup call executes on the HTTP worker thread. Android may reclaim an idle app process; the next app request or scheduled widget job starts the backend again. The existing microphone foreground service remains responsible for an active voice call. This is not a boot-time daemon or an always-on wake word. In-memory conversations and Spotify tokens reset on process death; saved Library content and notes survive normal app restarts and upgrades.

- Gemini configuration: AES-GCM encrypted preferences, with the encryption key in Android Keystore. Android backups are disabled for this app. Decryption failure requires entering the Gemini key again.
- Notebook: `files/backend/notebook.sqlite3` under the Android app's private directory. Explicit note saves use the same SQLite-backed capability as before.
- Library and widget state: existing app-private files/preferences, preserved during upgrade.
- Local auth token: generated fresh in memory per process, never included in exports or APK resources.
- Raw microphone audio: streamed, never saved. The Android backend logs only three aggregate voice durations when a connection closes, for release diagnostics.

Clearing app data or uninstalling removes local content and configuration. A replacement device does not automatically inherit the notebook. This iteration adds local ownership, not cross-device synchronization or a guaranteed background process.

## Build and install

Requirements: Android Studio JDK/SDK, the existing Gradle 8.14.3 wrapper distribution, Python 3.11 on the build machine, and USB debugging for installation.

```powershell
.\scripts\build-android.ps1 -Release -Install
```

The current review APK is signed with the existing local development certificate so it upgrades the already installed app. A public Play release still needs its own distribution signing and release process.

Only `thread_agent/**/*.py` is staged as application Python code. `.env`, the laptop notebook, reports and website assets are excluded. Portable dependencies are pinned in `android/requirements-phone.txt`: Pydantic 1.10.26 and jsonschema 4.17.3 avoid unavailable Rust extension wheels, while the desktop keeps its original dependency stack. The adapter preserves required values, native JSON types, closed-model validation, identifier checks and independent Live schemas. Android has separate native Pillow wheels. [Chaquopy Android configuration](https://chaquo.com/chaquopy/doc/current/android.html), [supported versions](https://chaquo.com/chaquopy/doc/current/versions.html).

## One-time development migration

Use this only on your own attached development phone. Normal users can enter a key in Settings. The migration reads the local `.env`, streams the selected configuration over adb's non-PTY stdin into a debug app's private directory, and launches THREAD to encrypt and delete the import. It never puts a secret in command arguments, intents, shared storage or printed output.

```powershell
.\scripts\build-android.ps1 -Install
.\.venv\Scripts\python.exe scripts/provision_phone.py --serial YOUR_ADB_SERIAL --migrate-notes
# Verify the import was consumed, then install the final non-debuggable APK.
.\scripts\build-android.ps1 -Release -Install
```

Existing encrypted phone credentials are preserved unless `--replace-key` is supplied. An existing phone notebook is never overwritten. SQLite's backup API produces a consistent snapshot of the old notebook. The phone receives a complete temporary database before it is renamed into place. The development import is disabled in release builds, and `run-as` is unavailable on the final non-debuggable app.

## Spotify

The phone callback is now **`http://127.0.0.1:8767/api/spotify/callback`**. Register that exact address in the Spotify Developer app, then enter its public client ID in THREAD Settings. The browser returns to the backend on the same phone. No developer app has been registered for this project yet, so actual Spotify account authorization and playback remain unverified. Premium alone does not supply that registration.

The optional desktop website still uses port 8766. Desktop and phone have independent session memory and notebook locations.

## Verification

See [validation scope](docs/VALIDATION.md) for public-source checks and the separate historical device record. Raw device/provider logs are retained privately by the team; they are not relabelled as fresh checks of this checkout.

The default native suite includes the actual packaged Python backend, local HTTP/WebSocket authentication, encrypted credential loading, a local calculation and private notebook routing. The opt-in SmartActionsLiveDeviceTest uses real Gemini requests and real Android handoffs. The separate release check uses the actual minified APK and microphone, with the laptop backend stopped and USB backend mappings absent:

`-Release -Test` installs a small, separate `com.thread.probe` test helper. It observes only named call buttons through Android accessibility, runs in its own process and is excluded from the THREAD APK. Normal installation/use does not need this helper. The check reads fresh accessibility nodes because the generic Android UI dump can time out while live captions and animation are updating.

```powershell
.\stop-thread.ps1
# Remove an old mapping only if adb reverse --list shows one.
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" reverse --list
.\scripts\build-android.ps1 -Release -Test
```

No measured acoustic latency or battery-life claim follows from these functional tests. Network quality, API limits and the cloud provider still affect live conversation quality.
