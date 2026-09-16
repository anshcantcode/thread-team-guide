# Run and explore the application

[Home](../README.md) · [Start here](START_HERE.md) · [What works](WHAT_WORKS.md) · [Code map](CODE_MAP.md) · [Team plan](TEAM_PLAN.md)

## Before you begin

This repository contains the full application source. Clone it and run the commands below from its root:

```powershell
git clone https://github.com/anshcantcode/thread-team-guide.git
cd thread-team-guide
```

The application root contains `run.ps1`, `.env.example`, `requirements.lock`, `thread_agent/`, `android/`, `web/`, and `tests/`.

Choose your route:

| Goal | What you need |
|---|---|
| Read and understand | The README and docs directory. |
| Try the already installed phone | THREAD on the S24, owner consent to use it, internet, configured Gemini key/quota. |
| Run controller checks | Full application checkout and Python 3.11. No cloud key for the deterministic checks below. |
| Run the browser workspace | Full checkout, Python 3.11, and Gemini configuration for model requests. |
| Build Android | Full checkout, Android Studio JDK/SDK, Python 3.11, Gradle download, and USB debugging for device installation. |

## Browser workspace on Windows

Open PowerShell in the **application root**. Create the environment and install the pinned dependencies:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
```

If `.env` does not exist, create it without overwriting an existing configuration:

```powershell
if (!(Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
}
notepad .env
```

Set `THREAD_API_KEY` locally. Use the current project's `.env.example` for model names and other defaults; model availability and quota belong to that provider project. Keep the real `.env` out of Git and out of messages/screenshots.

Start the workspace:

```powershell
.\run.ps1
```

Open **http://127.0.0.1:8766/**, unless you changed the port. The launcher also creates the environment when missing, waits for server readiness, and leaves the server running in the background.

Start with **Type instead**. Then choose **Start talking** and grant microphone access to test voice. Close the conversation when finished.

Stop the local server:

```powershell
.\stop-thread.ps1
```

The Android app has its own embedded backend and configuration. Starting this desktop server does not configure the phone.

## Android: install or build

### Install a supplied review APK

Use the current review APK supplied by Ansh. It is Android **0.6.0**, package `com.thread.app`, for Android 12+; the recorded verification device is the Galaxy S24.

On a fresh installation, enter a Gemini key in THREAD Settings. The APK contains no personal API key. The phone stores its configuration privately with Android Keystore encryption. New model requests and fresh public data need internet access.

The current APK uses a development signing certificate. It is a review build, not a Play Store release. A build signed on another developer's machine may not upgrade the existing installation. Do not uninstall an app holding wanted notes/cards just to bypass a signature mismatch; coordinate the signing/build handoff first.

### Build from source

The checked-in build helper respects `JAVA_HOME` and `ANDROID_HOME` (or `ANDROID_SDK_ROOT`), with these Windows fallback locations:

- Android Studio JDK: `C:\Program Files\Android\Android Studio\jbr`
- Android SDK: `%LOCALAPPDATA%\Android\Sdk`
- Android SDK platform **36**; minimum supported device API **31**
- Python **3.11** available to the build
- Gradle wrapper distribution **8.14.3**

Open the `android` directory in Android Studio and let Gradle sync/download the required SDK components. The helper uses the checked-in Gradle wrapper, which downloads its pinned distribution when needed. To inspect it separately:

```powershell
.\android\gradlew.bat --version
```

If your JDK/SDK lives elsewhere, set `JAVA_HOME` and `ANDROID_HOME` for your machine before using the helper.

Connect a development phone, enable USB debugging, and accept its debugging prompt. From the application root:

```powershell
.\scripts\build-android.ps1 -Release -Install
```

The full output path relative to the application root is:

```text
android/app/build/outputs/apk/release/app-release.apk
```

The build installs and opens THREAD. Its backend starts inside the app; USB forwarding and a running desktop server are unnecessary for normal phone use.

## First checks for a developer

Run these in the application root after dependency installation:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_theme5.py -q
.\.venv\Scripts\python.exe scripts/check_theme5.py --seeds 50
```

The replay uses scripted interpretations and a virtual clock. At 50 seeds it checks 300 scenario/seed combinations with paired and fresh-process executions. It tests the controller, without consuming Gemini quota. It writes a new `reports/theme5-replay.json`, so preserve any earlier report you need before rerunning it.

For a change to a particular area, start with that area's tests in [Code map](CODE_MAP.md). Run the broader suite when the change affects shared behavior:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

Do not start every live-provider script just to explore. Actual-model acceptance, responsiveness, voice, and some device checks consume quota. Some widget checks deliberately add home-screen widgets.

For Android development, the app's own `android/README.md` explains the debug device suite and the separate optimized-release microphone check. `-Test` installs test components and runs device checks; `-Release -Test` also needs an unlocked, configured phone and available cloud quota. They are not equivalent to a build-only command.

## Common problems

| Symptom | First thing to check |
|---|---|
| `run.ps1` or `requirements.lock` is missing | Check that you are at the repository root and have a complete checkout. |
| `py -3.11` is unavailable | Install Python 3.11 and confirm the Python launcher can find it. |
| PowerShell refuses a script | Follow your machine's execution-policy rules; do not change machine-wide policy casually. `start-thread.bat` is also supplied for the desktop launcher. |
| Port already in use | Check the message from `run.ps1`; use `run.ps1 -Port 8770` and open the corresponding address if needed. |
| UI opens but voice/model requests fail | Key configuration, internet, model availability, and quota. Phone and desktop settings are separate. |
| Android cannot be found | USB debugging, authorized device prompt, cable, and Android SDK platform-tools. |
| Gradle helper cannot find its distribution | Run `android/gradlew.bat --version` and check download/network errors, then retry. |
| APK will not update the installed app | Signing certificates may differ. Preserve local content and coordinate the build handoff. |
| Spotify asks to connect | Expected until the Developer app/client ID and user authorization are configured. Premium alone is insufficient. |
| A result is old or partial | Inspect source date, coverage, and refresh status. A failed refresh deliberately preserves the previous result. |
| A supposed timer never rings | Check whether it was a visual workspace countdown or a native Android Clock action. |

Desktop diagnostic logs live under `.runtime/`. Share a minimal redacted error, not an entire unreviewed log directory.
