# THREAD — smart actions and personal task cards

This is the focused action roadmap requested on 14 September 2026. It covers commands that span apps, preserve context and survive corrections. The much broader card catalog remains in `features.md`. These are implementation targets, not claims that every integration exists.

## Build order and scope

1. Bring the reviewed controller into the Android experience: current task, retained/changed details, real action outcomes, pause/resume/stop, and a phone-side stale-command check.
2. Implement Google search destinations (all/images/videos/news), follow-up tab changes with the previous query, and YouTube/Spotify search handoffs.
3. Connect Spotify using OAuth PKCE, resolve a top track from the user's authorized history, play on an explicitly identified active device, set repeat and verify each outcome.
4. Expand only after the first workflows work on the S24. Keep the frozen Theme 5 candidate and its score separate from this Android iteration.

The user has Spotify Premium but has not registered a Spotify Developer app yet. End-to-end account authorization and playback cannot be claimed until that setup and a real account test succeed. No developer secret belongs in the APK or this document.

## What “smart” means here

- Resolve the desired final state. “Search Google for cats and open the videos tab” needs a Google videos search for cats. It does not require pretending to tap two pages when a native URL handoff reaches the same destination.
- Keep a small current task: goal, relevant entities, filters, source, completed steps, next step and actual outcome. “Images instead” should preserve the previous query.
- Distinguish planning, opening an app, a draft, a submitted action and verified completion. Never announce playback just because Spotify opened.
- Apply a correction to the affected work. Keep unrelated constraints; stop remaining old steps before they cause an effect.
- A clear compound request can authorize a bounded predefined workflow. It does not grant arbitrary later actions or arbitrary UI access.
- Check user authority again at each effect boundary. Read-only retrieval can precede an action, but retrieved page text cannot authorize one.
- Show a partial outcome if one step succeeds and another fails. If playback started but repeat failed, say exactly that. Do not replay the whole chain.
- Use explicit shared content, public Android intents and authorized provider APIs. There is no invisible access to every app, contact, notification, account or screen.

## First workflows

| User says | Intended behavior | Honest completion evidence |
|---|---|---|
| On Google search for cat images and open the videos tab. | Keep the query and open Google's videos results. | Android accepted the specific search URL; page loading itself is not verified by a handoff. |
| Images instead. | Change only the last Google search's tab. | Same query, new tab, native handoff receipt. Ask for a query if this conversation has none. |
| Search Google for robotics news. | Open the requested search destination. | Query and URL in the receipt. |
| Search YouTube for repairing a bicycle chain. | Open YouTube search, with browser fallback if available. | Search destination opened; no claim a particular video played. |
| Search Spotify for Daft Punk. | Open Spotify's search destination. | App/browser handoff only. |
| Open my most played on Spotify and play it on loop. | Use Spotify's top-track ranking for the chosen period, play it, enable repeat-one, verify the track and repeat state. | Spotify playback-state read-back. Its ranking is affinity, not an exact lifetime play-count export. |
| Play my top Spotify track from this month. | Use approximately four weeks of affinity data. | Source period, actual returned track and playback state. |
| Pause Spotify. | Pause the current active device. | Playback is not playing on read-back. |
| Resume Spotify. | Resume on the active device. | Playback is playing on read-back. |
| Put Spotify on repeat one. | Change repeat mode only. | `repeat_state=track`. |
| Turn off Spotify repeat. | Set repeat off. | `repeat_state=off`. |
| Wait, stop the task. | Stop unfinished controller work; preserve actual completed effects. | Controller state and action receipts, not just stopped speech. |

## Expansion catalog — planned unless marked as implemented in the build notes

The implementation boundary is explicit so this list stays useful rather than becoming a list of imaginary buttons.

| # | Natural request | Task/card experience | Integration needed |
|---|---|---|---|
| 1 | Search for cats, then show only videos. | Search query plus selected result category; correction keeps query. | Google URL handoff. |
| 2 | Same search, but news. | One changed filter; no repeated dictation. | Previous authorized search context. |
| 3 | Open the second source from that answer. | Named source card, exact URL. | Bind to actual returned result IDs. |
| 4 | Compare these two pages I shared. | Side-by-side claims with original links. | Android sharing plus bounded retrieval. |
| 5 | Find a tutorial for this error message. | Shared error, relevant sources, source dates. | Shared screenshot/text and web lookup. |
| 6 | Search YouTube for a ten-minute explanation of this. | Carry over the explicitly shared topic. | Search handoff; duration filter needs supported search integration. |
| 7 | Find the official manual, not another blog post. | Source provenance and matching model number. | Authorized retrieval and model identity. |
| 8 | Keep this research and let me continue tomorrow. | Saved findings and unresolved questions. | Persistent task state with explicit resume. |
| 9 | Play my most played song on loop. | Track, ranking period, device, playback and repeat state. | Spotify authorization and Premium. |
| 10 | Use this month's favourite, not the last six months. | Revise ranking period before playback. | Spotify top items; cancel stale selection. |
| 11 | Repeat this song, not the whole playlist. | Precise repeat mode with read-back. | Spotify player API. |
| 12 | Stop repeating, keep playing. | Change one playback property. | Spotify player API. |
| 13 | Play it on this phone, not my laptop. | Explicit device selector; no arbitrary device fallback. | Spotify available devices and transfer. |
| 14 | Queue that song after this one. | Current queue and requested addition. | Spotify queue API with duplicate guard. |
| 15 | Find the song I played yesterday evening. | Time-bounded listening-history candidates. | Spotify recently played; disclose coverage. |
| 16 | Save this song to a playlist I choose. | Selection and playlist destination. | Spotify library/playlist scopes and explicit action. |
| 17 | Start a focus session with a timer and quiet music. | Separate timer and music receipts, partial outcomes. | Clock intent plus authorized music control. |
| 18 | When the timer ends, stop the music. | Scheduled dependency visible to the user. | Durable Android scheduling and fresh provider access. |
| 19 | Find a cafe near the place I shared and open directions. | Place context, selected cafe, route handoff. | Place search plus maps; no assumed live location. |
| 20 | Walking directions instead, same destination. | Preserve place and revise transport mode. | Maps destination/mode support. |
| 21 | Add a stop at the pharmacy. | Route revision with both stops visible. | Maps multi-stop support. |
| 22 | Find a place open when I arrive. | Hours, arrival assumption and source freshness. | Reliable business hours/route APIs. |
| 23 | Keep that place for this weekend. | Saved destination and intended date. | Local note/task persistence. |
| 24 | Tell me when I need to leave for this event. | Event, travel estimate, reminder status. | Explicit calendar access, routing and alarm. |
| 25 | Draft a message saying I'll be late. | Editable message plus chosen recipient. | Android messaging draft; recipient resolution required. |
| 26 | Make that message shorter, keep the time. | Show revised text and preserved detail. | Existing draft composition. |
| 27 | Email these findings with the links. | Source-linked email draft. | Actual source IDs plus native email composer. |
| 28 | Put this itinerary into Calendar. | Resolved dates/timezones and an event draft. | Native Calendar insertion. |
| 29 | Change it to tomorrow, leave the location. | Edit the prepared draft before handoff. | Explicit draft state. |
| 30 | Send it to my brother. | Ask which contact when unresolved. | Opt-in contact picker; never guess a number. |
| 31 | Turn this voice note into a checklist. | Native tickable checklist retaining details. | Existing document/checklist capability. |
| 32 | Make a packing list for the trip we planned. | Trip-linked checklist with editable assumptions. | Saved task context plus document generation. |
| 33 | Remove things I already packed. | Update checked items, preserve remainder. | Checklist persistence and explicit item selection. |
| 34 | Put the list on my home screen. | Real widget preview using saved result IDs. | Existing Android widget workflow. |
| 35 | Make a shopping list from this recipe. | Recipe ingredients linked to checklist. | Structured document composition. |
| 36 | We have onions already; update the list. | One item changed, other quantities preserved. | Entity/item binding. |
| 37 | Help me fix this, one step at a time. | Device, observed symptom, manual and attempted steps. | Shared camera image and supported manual retrieval. |
| 38 | The light on the right, not the left. | Change visual target and invalidate old evidence. | Current-frame grounding. |
| 39 | I tried that already. | Record attempted step and find the next supported step. | Persistent guided-task progress. |
| 40 | Pause this while I find the cable. | Resume from the same verified step. | Controller pause and saved state. |
| 41 | Show me the exact manual page. | Source page and section. | Document provenance. |
| 42 | Explain that more simply. | Rephrase the current step without changing the action. | Same grounded evidence. |
| 43 | Watch this price and tell me if it drops. | Target, threshold, source and schedule. | Durable monitoring; not available from a one-time lookup. |
| 44 | Compare these products within my budget. | Criteria, real prices and source timestamps. | Reliable product retrieval; no fabricated availability. |
| 45 | Save the better option; don't buy it. | Saved choice with no purchase authority. | Local persistence. |
| 46 | Show only products that meet these three requirements. | Explicit filter reasons and missing evidence. | Structured sourced comparison. |
| 47 | Follow my team and show their next game. | Personal team selection with real fixture source. | Existing sports data coverage; explicit preference save. |
| 48 | Same player, just T20. | Preserve player, change format. | Existing cricket format filtering. |
| 49 | Make a widget with weather and that match. | Two actual result sources in one widget. | Existing composition and native widget preview. |
| 50 | Remind me before the match starts. | Fixture-linked alarm with timezone. | Reliable schedule plus Android Clock. |
| 51 | Read this document and quiz me on it. | Shared source, questions and marked answers. | Document sharing and persistent study state. |
| 52 | Skip what I already know. | User-confirmed progress, revised lesson. | Study state; do not invent proficiency. |
| 53 | Translate this and keep the important names. | Original and translated text together. | Multilingual evaluation before broad claims. |
| 54 | Summarize what changed since we last looked. | Stored baseline versus fresh source. | Versioned source snapshots. |
| 55 | Lower media volume and open my notes app. | Bounded two-step action with two receipts. | Explicit composite action support; not arbitrary chaining. |
| 56 | Open Bluetooth settings so I can connect headphones. | Settings handoff and next step. | Existing native settings action; no false “connected” claim. |
| 57 | Make this my default morning view. | User-selected personal card composition. | Persisted preference, existing widgets, future scheduling. |
| 58 | Stop talking, keep working. | Speech stops while authorized reads continue. | Existing speech-only controller semantics. |
| 59 | Stop the search, keep the booking. | Correct scope of stopping. | Existing effect lifecycle. |
| 60 | What actually happened while I was away? | Action receipts and unresolved outcomes. | Durable task history; never infer success from narration. |

## Personal cards should contain useful state

Search: query, provider, selected tab and exact destination. Music: real track, artist, ranking period, target device, play/repeat status. Travel: preserved origin/date/time and visibly changed destination. Troubleshooting: current device, attempted steps and source page. Draft: intended recipient, editable content and the external app's review step. Every action card needs a distinct failure/partial/unresolved state.

Do not decorate missing data with invented personal facts. A remembered favourite must come from a user preference or an authorized source. A generated mockup is not that source.

## Spotify setup and constraints

Android 0.6 uses `http://127.0.0.1:8767/api/spotify/callback` on the phone itself. Register that exact URI in a Spotify Developer app. Enter the public client ID in THREAD's Spotify connection settings. The user authorizes the requested scopes in Spotify's browser page. No client secret is needed for PKCE. The optional desktop website still uses port 8766; it is a separate runtime.

The embedded backend holds tokens only in memory with expiry. Restarting the app process requires reconnecting Spotify. This is a local development connection, not a deployed multi-user account service. Disconnecting removes the local grant; the user can also revoke access in Spotify account settings. Connecting must never automatically replay an old music command.

Spotify's top items endpoint supplies calculated affinity over a period, not exact play counts. Defaults must be visible. Playback requires Premium and an active controllable device. An unavailable device, expired consent, quota response or partially completed action must produce an honest card.

## Verification targets

- Existing controller and native-authority tests remain green.
- A queued Android action with the previous local input ID is rejected.
- Search query strings are encoded as data; only supported providers and tabs are accepted.
- A tab-only request cannot silently borrow another conversation's query.
- An acknowledgment, quotation, conditional or cancelled request cannot start playback.
- A correction during top-track retrieval prevents subsequent playback.
- Repeat cannot be reported as active without provider read-back.
- A lost playback response does not trigger automatic replay.
- Spotify OAuth state is one-use, time-bounded and separate from the opaque connection handle; tokens are never returned to the model, written to the card or logged.
- On-device tests distinguish fixture UI, native handoff, real provider and human microphone evidence.

## Reference and sources

- [ImageGen reference and exact prompt](design/smart-tasks/reference.md)
- [Android common intents](https://developer.android.com/guide/components/intents-common)
- [Spotify PKCE flow](https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow)
- [Spotify redirect requirements](https://developer.spotify.com/documentation/web-api/concepts/redirect_uri)
- [Spotify top items](https://developer.spotify.com/documentation/web-api/reference/get-users-top-artists-and-tracks)
- [Spotify playback](https://developer.spotify.com/documentation/web-api/reference/start-a-users-playback)
- [Spotify repeat](https://developer.spotify.com/documentation/web-api/reference/set-repeat-mode-on-users-playback)
- [Spotify July 2026 quota changes](https://developer.spotify.com/blog/2026-07-23-web-api-quota-updates)

See [validation scope](docs/VALIDATION.md) for the distinction between public-source checks and historical S24/model evidence. Original failed attempts remain in the team-held development records.
