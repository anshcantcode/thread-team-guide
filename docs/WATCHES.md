# THREAD Watches and bounded app actions — S6

Implementation branch: an isolated feature branch based on the catch-up source at `aebf6b3`.
Verified implementation commit: `5618756ef12465eedc27400e0bc5bc771f4cca06`. A following documentation-only
commit records these results; it does not change the packaged executable source.
These are consumer features, not a new benchmark result. No benchmark adapter, official tool semantics,
grading rules, or public-item answers were changed. Implementation and tests were AI-assisted (see the
[AI disclosure](submission/AI_DISCLOSURE.md)); device qualification belongs to the owner.

## What a Watch does

A Watch fetches **Google News RSS search**, without an API key or a language model:

```text
https://news.google.com/rss/search?q=...&hl=en-IN&gl=IN&ceid=IN:en
```

- The **first successful check is a silent baseline**. Existing headlines are saved for reading, not
  announced as new. A failed first check does not create an empty successful baseline.
- Later checks compare persisted link identities **and normalized title/source identities**. Only
  newly discovered reports are eligible for an Android notification. This is report de-duplication,
  not a claim that two differently titled articles contain different facts.
- Headline, source, link, publication timestamp (or explicitly unavailable), last check, next target,
  and check outcome are saved. “No new updates” and fetch failures appear in history without alerts.
- The fetch has a 15-second overall bound, a 512,000-byte response limit, at most 100 parsed items,
  and no article fetching or redirects. XML DTDs/entities and unsafe links are rejected.
- The source may omit reports, change its feed, rate-limit, or return old/incorrect headlines. These
  are attributed headline reports, not adjudicated facts or summaries of the articles.
- No digest/model call runs in the background. The optional generated-summary feature is deliberately
  omitted. Headlines remain useful without the host or an inference quota.

## Voice / typed-in-conversation tools

The same four names are declared in the existing consumer Gemini Live setup for Android and browser:

| Tool | Arguments in addition to normal turn metadata | Meaning |
|---|---|---|
| `create_watch` | `topic`; exactly one of `every_minutes` or `every_hours`; optional `stop_after` | Save a standing news Watch. `stop_after` is a **duration in minutes**, not a count or ISO time. |
| `list_watches` | None | Return compact Watch summaries with actual schedule/check state. |
| `stop_watch` | Exact `topic` or `id`, or neither for a single active Watch | Stop future checks, retaining history. Multiple active Watches require a target. |
| `check_watch_now` | Same target rules | Host: fetch now. Android: enqueue a network-constrained check; receipt says **queued**, not completed. |

Cadence: **15–10,080 whole minutes** (up to seven days). Fractional hours are accepted only when they
convert to whole minutes. `stop_after`: 1–525,600 minutes. No expiry is invented when omitted.
The 20-saved-Watch limit includes stopped Watches; recreating the same stopped topic resumes it and
keeps its de-duplication history. Changing an active Watch's schedule requires stopping it first.

Exact supported examples:

- “Every 2 hours, give me updates on Manchester City's 115 charges.”
- “Watch Manchester City 115 charges every 15 minutes for one day.”
- “List my watches.”
- “Check my watch now.” (one active Watch)
- “Check watch Manchester City 115 charges now.”
- “Stop watching Manchester City 115 charges.”
- “Stop watching.” (one active Watch)

Creation confirms the saved topic and cadence, the silent baseline, and the new-report-only policy.
If Android notifications are disabled, the receipt explicitly says that updates are saved but alerts
need permission. **A plain “stop” interrupts the current work; it does not silently stop every standing Watch.**

Tools keep the existing `base_revision`, `input_token`, and exact verified `user_request` requirements.
The cadence, topic, recipient, and new app-action destinations are bound to the current user words.
Unresolved references ask for repair rather than selecting an arbitrary Watch, contact, or app.

## Android ownership and background behavior

`LiveConversation` → `PhoneBridge` → existing `device_action` WebSocket message → `ThreadModel`
turn-id check → `WatchRuntime` / `WatchStore` → `device_result` → the existing action receipt/card.
The Watch actions use an IO executor so storage and WorkManager registration do not block the microphone/UI.
They do **not** use an extra phone server, a new socket, a host-owned shadow Watch, or a cloud job service.

Each Watch has one uniquely named `PeriodicWorkRequest`, a connected-network constraint and its own
persisted ID. WorkManager owns process/reboot rescheduling. Checks directly use OkHttp and the native
RSS parser; they do not start the embedded Python or Gemini backend. A manual check uses unique one-time
work; overlapping manual/periodic fetches in the same process coalesce.
Opening THREAD also reconciles saved active Watches with WorkManager, repairing a process death
between saving a Watch and registering its work without creating duplicate named periodic jobs.

Data lives in app-private `files/watches.json`, written via an atomic replacement under a process-wide
store lock. Malformed files are retained and reported, never silently reset. The latest 100 items and
100 checks per Watch are displayed. Up to 20,000 persisted de-duplication identities are retained per
Watch; reaching that bound **stops** it with a recorded failure rather than forgetting identities and
re-announcing old reports. Clearing app data/uninstalling removes Watches. No cross-device sync exists.

The bell button in THREAD's header opens **Watches**. The screen supports creation without a voice
connection, a list/detail view, last/next checks, stop, check now, headline/source/link history and
**Open report**. Notification taps open the matching Watch. Android 13+ notification permission is
requested separately when needed; the screen also exposes **Enable notifications**.

Notifications use the separate **Watch updates** channel: `N new updates · topic`, with up to five
headline/source lines. No baseline, unchanged-feed, or failed-fetch notification is posted. A stopped,
expired or replaced Watch cannot publish the result of an old in-flight fetch.

“Every two hours” is a **target interval, not an exact alarm**. Network availability, Doze, Samsung's
sleeping-app controls and OS scheduling can delay it. Swiping the app away differs from force-stopping
it: Android force-stop prevents background work until the owner reopens the app. Expiry prevents later
fetch/results; it does not promise an alarm at the exact expiry millisecond. WorkManager's persistence,
minimum interval and delay behavior follow the [Android scheduling guidance](https://developer.android.com/develop/background-work/background-tasks/persistent?hl=en)
and [PeriodicWorkRequest contract](https://developer.android.google.cn/reference/androidx/work/PeriodicWorkRequest).

## Browser / host API contract for S7

Browser voice (and typed input in a connected Live conversation) uses the same four tool names and the
same bridge validation. Its Watch store is `$THREAD_DATA_DIR/watches.json`, or the existing local `data/`
directory when that environment variable is absent. FastAPI lifespan starts one asyncio scheduler,
polling due Watches every 30 seconds with sequential bounded fetches. Restarting the host resumes due
work from disk; it does not replay every missed interval. **The host must remain running**. Closing a
browser tab does not stop host Watches; stopping the host does. No browser push/desktop notification
service or web Watch panel is claimed here; S7 can render the following same-origin API.

| Method / path | Request | Response |
|---|---|---|
| `GET /api/watches` | None | `{owner:"host", requires_running_host:true, watches:[...]}`; full display history, no private seen-ID set |
| `POST /api/watches` | `{"topic":"Manchester City 115 charges","every_hours":2}` (optional `stop_after`) | `{status:"completed", detail, watch:{...summary}}`; silent baseline will run when due |
| `POST /api/watches/{id}/check` | No body | `{status, detail, watch_id, new_items:[...]}`; `completed`, `failed`, or `cancelled` |
| `DELETE /api/watches/{id}` | No body | `{status:"completed", detail, watch:{...summary}}`; history retained |

All timestamps are **Unix milliseconds**; absent times are `null`. Watch fields:

```json
{
  "id": "opaque-watch-id",
  "topic": "Manchester City 115 charges",
  "active": true,
  "every_minutes": 120,
  "stop_after": null,
  "stop_at": null,
  "created_at": 1791030000000,
  "last_checked": 1791030000000,
  "next_check": 1791037200000,
  "baseline": true,
  "items": [
    {"id":"sha256", "story_key":"sha256", "title":"Example only", "source":"Example source",
     "link":"https://example.com/report", "published_at":1791030000000}
  ],
  "history": [
    {"checked_at":1791030000000,"status":"completed","detail":"No new updates.","new_count":0,"new_ids":[]}
  ]
}
```

This example is a schema illustration, **not a real report**. Lists are newest first for headlines and
check history. S7 should render these strings as text, open only the returned HTTP(S) links, label
`next_check` approximate, and show source dates separately from check dates. Polling can use the latest
`checked_at` and `new_ids` to present unseen updates, without inventing delivery acknowledgments.
The API returns 400 for invalid input/unknown or ambiguous targets, 403 for a mismatched Origin, and
409 on the embedded Android backend (to prevent two schedulers for one phone). Existing local-token
authentication remains in force on the phone. The API is local/single-owner, not a hosted multi-user service.

## App actions and chains

See [SMART_ACTIONS.md](../SMART_ACTIONS.md#s6-agent-abilities--3-october-2026) for exact phrases.
YouTube search is one `phone_media_search` call to the native YouTube results URI, with a web-link
fallback. `phone_open_app` rejects a compound “open … and search …” request so a mere app launch cannot
consume the command and masquerade as a search.

`phone_run_chain` admits 2–3 explicit, ordered steps. Earlier steps are `latest_news` or `set_volume`;
only the final step can hand off to another app. Supported final steps are WhatsApp draft, app/URL open,
media/Play Store search, directions, share text, or camera. The entire plan is validated before step 1.
For news → WhatsApp, the draft is bound to the **newest returned RSS headline + source + link**; there
is no fabricated body and no automatic send. Empty/failed lookup means no draft.

Each effect uses the existing device bridge and its own request ID. Between steps the controller checks
the original input epoch/token, task stop state, provider withdrawal and current speech/correction state.
The phone checks `client_input_id` again immediately before its local action. Corrections/stop cancel
remaining steps; earlier receipts remain. Failed, ambiguous, permission-needed and unknown outcomes
stop continuation. Tool redelivery returns the existing outcome rather than replaying steps.
Per-step snapshots are published as work finishes. Losing the voice connection preserves confirmed
earlier steps and marks an in-flight native effect **unknown**, not undone or successfully completed.

There is no rollback of an already opened app or prepared draft. Return to THREAD to revise an external
draft; THREAD cannot inspect or edit its current text through a public handoff. General unattended
multi-app screen navigation and accessibility-service automation are **not implemented**. A future
accessibility design would need its own scoped permission, visible controls and device/policy review;
it is not an implied capability of this build.

## S24 owner acceptance script (not a claim this was run)

Use the owner's existing configured Galaxy S24. No emulator, new key or account is required for Watch
screen/background checks. Voice requires the already configured consumer connection and available quota.
Keep a screen recording or note of actual receipts; never tap Send or Call as part of this script.

1. Install the built **debug** APK as an upgrade only if it matches the existing development signature:
   `adb install -r android/app/build/outputs/apk/debug/app-debug.apk`. Do not uninstall or clear app data
   to work around a signature error; that would erase owner state.
2. Open THREAD → bell (**Watches**) → New Watch. Enter a topic, 15 minutes. Deny notification permission
   once. Confirm the receipt/screen says alerts are off, not “you will be notified.” Enable permission
   from the Watch screen/Android settings, preserving the Watch.
3. With voice connected, say “Every 2 hours, give me updates on Manchester City's 115 charges.” Expect
   the correct saved topic and cadence, silent-baseline explanation and new-report-only policy. Open
   Watches and verify it. Repeating creation must not create a second identical Watch.
4. Say “List my watches.” With more than one active Watch, “Stop watching” must request a target rather
   than stop them all. Use “Check watch Manchester City 115 charges now.” The phone must say **queued**.
   Wait for history to show the result; first baseline must be silent. Check again; an unchanged feed
   must add “No new updates” history with no notification. Do not manufacture a live new-news event.
5. Close/swipe away THREAD (not Force stop), keep network enabled, and allow at least one 15-minute
   target plus OS delay. Reopen and inspect last-check/history. Reboot and repeat. When an actually new
   report appears, verify the count, headlines and notification tap → correct Watch → Open report.
   If no new report appears during the observation window, mark notification delivery **unobserved**;
   the saved-fixture tests cover the deterministic new-item decision, not physical delivery.
6. Temporarily disable the network. Confirm no false successful check/alert. Re-enable it and verify
   eventual history recovery. Restore the owner's network setting. Create a short stop-after Watch
   in voice (“Watch City council every 15 minutes for one hour”); verify expiry prevents later work.
7. Say “Open YouTube and search for Manchester City 115 charges.” Expect YouTube results for that
   query, or an explicit web fallback. Return to THREAD: receipt is `handed_off`, never “video played.”
   Repeat with “Search YouTube for City council updates” to confirm a fresh query. Check the fallback
   only if YouTube is already unavailable; do not uninstall the owner's app to force the case.
8. Try each action phrase in SMART_ACTIONS. For WhatsApp use **your own authorized number with country
   code**, not the fixture number. Inspect the draft, then back out without sending. Maps must preserve
   walking/driving mode; Play Store must not install; camera must not take a photo.
9. Say “Find the latest on Manchester City 115 charges and send it to [your number] on WhatsApp.” Inspect
   two receipts: RSS lookup then WhatsApp handoff. Match the draft headline/source/link to the returned
   RSS item. Nothing is sent until the owner acts outside THREAD.
10. Repeat step 9 and say “Stop” while lookup is pending. Also test a correction (“Actually, use a
    different topic”) during lookup. Expect the read's actual outcome plus cancelled/not-submitted
    later steps, with **no stale draft**. If the handoff already occurred, receipt must keep that fact;
    do not call it undone. The running task sheet also offers **Stop remaining steps**.
11. Stop test Watches by exact topic and verify stopped status/history after reopening. Preserve other
    owner Watches and settings. Record which items passed, failed or were not observed.

## Verification record

Saved synthetic XML fixtures are shared by Python and JVM tests. Tests never fetch the network.
CPU-only verification commands, from this isolated worktree:

```powershell
& 'C:\Users\ANSH\Documents\samsung voice interupt model\.venv\Scripts\python.exe' -m unittest discover -s tests
# Take the shared gradle.lock atomically; write S6; wait if held.
# Set the build process to BelowNormal priority. In android/, one build at a time:
.\gradlew.bat :app:testDebugUnitTest :app:assembleDebug --max-workers=1 --no-daemon -Dorg.gradle.jvmargs=-Xmx1536m
# Release only the lock owned by this build, including on failure.
```

Results for the implementation commit above, on 3 October 2026:

| Check | Actual result |
|---|---|
| Final Python base suite | **1,936 tests passed**, no failures/errors/skips; 233.961 seconds. Includes 18 Watch and 10 action-chain tests. |
| Android local JVM tests | **23 passed**, no failures/errors/skips: 8 RSS/store tests, 4 link/action tests, 11 existing camera/playback regressions. |
| Final debug build | `:app:testDebugUnitTest :app:assembleDebug` succeeded in 51 seconds, one worker, 1,536 MB Gradle heap, BelowNormal launcher priority, shared lock acquired and released. |
| Actual RSS smoke | **One request**, 2026-10-03 14:42:10 UTC; parsed **92 items** for `Manchester City 115 charges`. No loop, article fetch, key, model call or spending. |
| Embedded source identity | APK manifest hashes match all **32** checkout Python files; the actual embedded Python bytecode also matches compilation of those same sources. |
| APK package/signature | APK signature verifies using v2, existing Android Debug certificate. Private runtime filenames/notebook excluded; source-only Python payload verified. No personal key reference was read/provided, so the existing checker correctly reports that specific known-key comparison as **unknown**, not passed. |
| Scope and whitespace | All changed files LF; `git diff --check` clean; no protected benchmark paths or `.thread-run` changes. |

APK: `android/app/build/outputs/apk/debug/app-debug.apk` (**147,175,122 bytes**).

```text
SHA-256 38c22fe4c5ac261877d433fe24d54d9171b38b15b38f8448cb4f8601bb8ffd7a
Debug certificate SHA-256 197ae989e339077dfcfeee9ca3b29a5ffd3fc59e058b3ac55eef4dc40a52f68c
```

Local evidence is retained under the ignored `.runtime/agent-abilities/` directory, including
`python-full-2.log`, `gradle-2.log`, `rss-smoke.json`, `apk-verification.json`, `apk-signature.log`, and
the source hash snapshot. Earlier focused-test failures (boolean cadence validation, then a test-edit
placement error) and failed Windows process-launch attempts are retained there too. Both defects were
fixed and the final suites above rerun. Logs/runtime state are not committed or packaged as submission assets.

**Not run:** real Gemini calls, acoustic S24 verification, installation on the owner's phone,
reboot/notification delivery, external-app UI checks, emulator, GPU or WSL work. The debug APK is a
local review artifact, not a Play/release qualification. Run the owner script above to establish device
evidence. Historical benchmark scores do not transfer to this changed source.

Primary platform references: [Android common intents](https://developer.android.com/guide/components/intents-common),
[WorkManager release notes](https://developer.android.com/jetpack/androidx/releases/work), and
[Google Maps URLs](https://developers.google.com/maps/documentation/urls/get-started). No copied article content
or new paid provider is bundled; displayed source attribution and links remain with each RSS item.
