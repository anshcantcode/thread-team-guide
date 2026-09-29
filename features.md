# THREAD: Features Worth Building

**A product strategy, project audit, personal card catalog, and Samsung PRISM build plan.**

Prepared for Ansh and a team of **four total**, on **14 September 2026**. Hardware baseline: the connected **Samsung Galaxy S24 SM-S921B, Android 16 / API 36, One UI 8.5**. No watch, earbuds, SmartThings appliance, or additional phone is required for the recommended build.

**Meaning of “premium”:** rich, useful, interactive cards that feel personal. It does not mean a subscription tier.

**Status:** this is a researched proposal. The audit identifies existing implementation separately. Features described in the roadmap and catalog are proposed additions or upgrades, not claims that they have been built.

## Hackathon scope and product backlog

**Winning Theme 5 takes precedence over building a general consumer assistant. This decision supersedes the broader product roadmap, staffing schedule, eight-card target, and optional feature recommendations below.**

The project has a relevant interruptible-agent foundation. Expanding it into a Gemini/Alexa alternative before proving the evaluated behavior would be scope drift. The 160-card catalog is now a **deferred product backlog**, not the submission plan.

### Active submission priorities

1. **Evaluator-facing behavior:** integrate the official queues/events, end-of-turn semantics, manifest format, state snapshots, virtual clock and runtime limits when the kit is supplied. The current thread.v1 adapter is provisional.
2. **Fast and slow coordination:** measure and improve acknowledgment, interpretation and correction handling in the headless path. Its queued batch planner is different from the native Gemini Live conversation path; phone fluency alone does not prove evaluator performance.
3. **Cancellation and state correctness:** retain unchanged slots, cancel affected reads promptly, reject late stale results, prevent duplicate writes and reconcile unknown outcomes.
4. **Unfamiliar tools and multimodal evidence:** test new manifests, chained calls, ambiguous audio and corrected image targets with the actual supplied corpus/contract when available.
5. **Fresh-session isolation and reproducibility:** exclude consumer persistence from evaluation; prepare clean setup, Docker, the required repository/tag and honest measured evidence.
6. **A small demonstration of those behaviors:** use the existing UI to expose corrected constraints, relevant evidence and actual outcomes. Add a view only when it makes a scored behavior understandable.

### Submission demonstrations

- **Changed booking request:** revise destination/date/time while a lookup is pending; preserve unchanged details; handle stop-before-submit, late results and uncertain outcomes.
- **Corrected visual troubleshooting:** change the referenced indicator/device while manual retrieval is pending; ground the final answer in the corrected frame/target.
- **Unfamiliar tool:** load a previously unseen supported manifest and carry out a corrected, chained request without adding scenario-specific intent rules.

These are team demonstrations aligned to the guide, not claims about the unpublished canonical scenarios. Use organizer scenarios once available.

### Deferred consumer backlog

New sports coverage, additional lifestyle domains, universal card editing, a general multi-card planning engine, persistent personal memory, background monitors, SmartThings/health integrations, wake words and further visual redesign. Keep existing working features; avoid spending new submission time on them.

**Suggested effort split, not Samsung scoring:** approximately 70% agent/protocol correctness, 20% evaluation and failure analysis, 10% presentation and submission polish. The four builders should focus on controller/state, perception/fast-path behavior, harness/testing, and integration/reproducibility respectively.

**Gate for any new feature:** it must improve measured completion, recovery, latency, grounding, protocol compliance or the clarity of evidence. Otherwise defer it.

### Implementation checkpoint — 14 September

The active core now has a two-queue evaluator boundary, virtual-clock replay, preemptible interpretation, persistent floor ownership, current-frame dependencies, manifest-bound reconciliation and an independent command-evidence gate for writes and cancellations. The native Live receiver continues receiving interruptions while tool requests are pending. An actual provider error remains a failure, and unknown effects remain unknown.

[EVALUATION.md](EVALUATION.md) documents the provisional contract and rerunnable checks. [Validation](docs/VALIDATION.md) distinguishes current public-source verification from historical device/model evidence. The 160-card catalog remains proposed product work. The [technical demonstration plan](docs/TEAM_PLAN.md) focuses on corrected state, cancelled calls, and service outcomes.

## Start here

The remaining document preserves the broader product exploration. Read it under the hackathon-first decision above; its consumer roadmap is not an active commitment for 25 September.

**Build an assistant whose work stays coherent when life changes halfway through the request.**

The compelling moment is not “it answered a question.” It is:

> “Plan dinner for two after the match.”
>
> “Actually four. One person is vegetarian. We’re walking, and we have to be home by ten.”
>
> The meal, cost split, timing, and walking constraints update together. The chosen neighborhood stays. A reservation is still only a proposal. Ask a side question, then return to precisely the same plan.

That experience can feel substantially better than a voice interface that makes someone reconstruct their request after every correction. It also demonstrates the actual hackathon problem: concurrency, localized state changes, cancellation, and truthful outcomes.

There is no honest basis for guaranteeing a hackathon win or claiming no competitor can do any of this. The defensible ambition is narrower and stronger: **make THREAD unusually good at helping a person complete a changing task, with visible evidence that it respected the changes.**

### The recommended submission

Build **three hero experiences**, powered by the same controller:

1. **Change the Plan:** a personal outing or travel plan with linked cards, live constraint edits, side questions, and before/after changes.
2. **Show Me This One:** point to a device/manual or share an image; interrupt to change the target; the evidence and instructions follow the corrected target.
3. **Wait, Don’t Do That:** stop a prepared action, handle a late result, and show exactly whether the action happened. Include one true phone handoff and one explicitly labeled sandbox booking.

Give these experiences eight excellent card families first: **plan, weather window, calculation/split, shortlist/comparison, checklist, evidence/manual, action receipt, and clarification**. Keep existing sports profiles as a polished supporting example.

The catalog later in this document is a product opportunity map. It is not an instruction to implement 160 cards before 25 September.

### What I would prioritize

| Priority | Build | Why it earns its place |
|---|---|---|
| 1 | Official evaluation adapter and session isolation | The actual judged artifact must speak Samsung’s protocol and respect its state rules. |
| 2 | Interruptions that patch the current task and explain the change | Directly targets the largest technical scoring categories. |
| 3 | Personal constraint chips and stable card editing | Makes correctness legible and useful to an ordinary person. |
| 4 | A small linked plan with dependency-aware updates | One correction visibly updates related work instead of producing disconnected replies. |
| 5 | Side-question bookmark and return | Shows continuity beyond one memorized correction script. |
| 6 | Frame-specific pointing and manual evidence | Uses the phone camera for a meaningful multimodal task. |
| 7 | True action receipts, including “outcome unknown” | Demonstrates the difference between conversational confidence and completed work. |
| 8 | Human microphone tests and a clean reproducible release | A beautiful demo with weak audio or missing submission files still loses. |

## Navigation

- [1. What Samsung actually asks for](#1-what-samsung-actually-asks-for)
- [2. What the project actually contains](#2-what-the-project-actually-contains)
- [3. Competition and honest differentiation](#3-competition-and-honest-differentiation)
- [4. Product direction and personal context](#4-product-direction-and-personal-context)
- [5. Twenty-four standout features](#5-twenty-four-standout-features)
- [6. The interruption vocabulary](#6-the-interruption-vocabulary)
- [7. What makes a card premium](#7-what-makes-a-card-premium)
- [8. Eight card blueprints](#8-eight-card-blueprints)
- [9. The 160-card opportunity catalog](#9-the-160-card-opportunity-catalog)
- [10. Data and Samsung integration paths](#10-data-and-samsung-integration-paths)
- [11. Implementation plan against this codebase](#11-implementation-plan-against-this-codebase)
- [12. Four-person build plan](#12-four-person-build-plan)
- [13. The five-minute demonstration](#13-the-five-minute-demonstration)
- [14. Measurements that make the claims credible](#14-measurements-that-make-the-claims-credible)
- [15. What to postpone](#15-what-to-postpone)
- [16. Decisions still open](#16-decisions-still-open)

## 1. What Samsung actually asks for

### 1.1 Sources inspected

I read the supplied Theme 5 guide, the main brochure, the text of the submission deck, and the AI disclosure form in the folder you provided. I visually checked the guide’s scoring and execution-constraint pages. These supplied versions are the authority for this plan; dates are not a claim about later organizer announcements.

| Local source | Relevant material |
|---|---|
| organizer-supplied project brief | Pages 1–3: architecture, streams, scoring, runtime, and state restrictions. |
| organizer-supplied project brief.pdf>) | Pages 8–14: Theme 05, timeline, broader evaluation, team and submission rules. |
| organizer-supplied project brief | Existing solutions, architecture, walkthrough, impact, innovation, limitations, differentiation, and submission checklist. |
| organizer-supplied project brief | AI use for ideation, code, design, content, testing; feature origins, tools/prompts, outputs, and modifications. |

### 1.2 Two different scoring views matter

**Theme 5 scenario scoring, from the guide:**

| Category | Weight | Product implication |
|---|---:|---|
| Task completion | 40% | Correct arguments, actions, final state, and grounded answers matter most. |
| Interruption recovery | 35% | Cancel invalid work, exclude stale results, and keep the corrected state. |
| Response latency | 15% | Produce a substantive response promptly after input or interruption. |
| Safety and protocol | 10% | Avoid duplicate writes and emit valid schemas, IDs, and snapshots. |

The guide also specifies a **0.80×–1.20× quality multiplier** for naturalness, truthfulness, and relevance, and a **1.5× multiplier for multimodal hidden scenarios**. Do not invent an overall score formula beyond what the organizer publishes.

**Broader submission evaluation, from brochure page 11:**

| Category | Weight | Product implication |
|---|---:|---|
| Working prototype and functionality | 30% | Real behavior and reproducibility. |
| Technical depth and feasibility | 25% | Explain the controller, cancellation, and evidence. |
| Innovation and originality | 20% | Show a distinctive interaction, not a familiar feature checklist. |
| Relevance to theme | 15% | Interruptions must materially change the work. |
| Presentation and documentation | 10% | A clear narrative and a usable submission package. |

These are separate rubrics in separate documents. They should not be added together.

### 1.3 Requirements that change our roadmap

- Runtime is **Python 3.10–3.12**, with a **120-second scenario cap** and a **300-second setup/warm-up hook**.
- Evaluation memory is **session-scoped only; no cross-session caching**.
- Wake-word detection, voice-synthesis tuning, and UI design are **outside the Theme 5 technical scope**. UI can still help the broader presentation.
- Inputs include timestamped text chunks, audio clips, frames, interruptions, tool results, and scenario manifests.
- Outputs include explicit tool calls, cancellations, clarifications, and final responses with structured state snapshots.
- The guide describes nine public scenarios and approximately sixty hidden scenarios. The complete scenarios are not contained in the supplied guide.
- The evaluation kit is to be released after registrations. The exact runner integration remains unverified until that kit is available.
- The supplied Theme 5 materials do **not clearly settle cloud access, paid-model access, key provisioning, network availability inside evaluation, or a compulsory Samsung SDK**. Keep these as open organizer questions. Permission in another theme must not be transferred to Theme 5.

### 1.4 Dates and team

The brochure lists registration closing **16 September 2026 at 11:59 PM**, submission closing **25 September 2026 at 11:59 PM**, shortlist announcement on **9 October**, final demo on **15 October**, and final results on **24 October**. It marks the timeline tentative. The deadline text does not explicitly label a time zone; confirm the submission form’s time zone.

The team cap is **four people from one college**, one theme and one submission per team. Ansh confirmed **four total**, so the proposed staffing fits that cap.

The final submission requires a GitHub repository, reproducible README, Docker files/requirements, a demo video of at most five minutes, and a deck. The brochure requires the final release tag **PRISM_GENAI_HACKATHON_Y2026**, with referenced submission materials present in the tagged commit.

## 2. What the project actually contains

### 2.1 Audit method and limits

This was a project-wide architecture and product audit: source inventory; a structural parse of all **38 Python files** under the application, scripts, and tests; inspection of the main controller, voice relay, schemas, providers, native Android UI/audio/actions/widgets, browser renderer/audio, launch/build paths, product/design documents, and selected verification reports.

I reran the existing offline Python suite and all three JavaScript checks. I inspected the connected phone’s model, OS, installed app version, and current THREAD screen. I did not run a new human speech benchmark, retrain a model, exercise every third-party provider live, or audit every generated media/binary asset. No claims below treat historical reports as fresh microphone measurements.

### 2.2 Current implementation map

| Area | Actual implementation | Consequence for new features |
|---|---|---|
| organizer-supplied project brief | Async work, slots, revisions, result relevance, selection, pauses, write preparation, outcome reconciliation, comparisons, and a bounded workspace. | Reuse this. The core differentiation already has a foundation. |
| organizer-supplied project brief | Gemini Live PCM relay, function declarations, captions, interruption/noise recovery, and later backend feedback. | Speech/understanding comes from Gemini; THREAD’s contribution is orchestration and product behavior. |
| organizer-supplied project brief and organizer-supplied project brief | Provisional thread.v1 events, validated manifests, explicit action streams. | Do not call it Samsung-compatible before integration with the official kit. |
| organizer-supplied project brief | Separate Gemini/local interpretation path, including optional local transcription/perception. | This is not an offline replacement for the current native Live audio path. |
| organizer-supplied project brief | Fourteen actual built-in manifests: web, sports, calculate, convert, currency, weather, research, dates, clock, world_clocks, timer, document, notes, library. | Much more than sports is available. The card experience can catch up before adding many APIs. |
| organizer-supplied project brief | Web/news RSS discovery, football identities and records. | Good source-card foundation; snippets are not full-article reading. |
| organizer-supplied project brief and organizer-supplied project brief | Multiple sport families, sport-specific records, identity clarification and coverage limits. | Reuse the design grammar, not football statistics for unrelated content. |
| organizer-supplied project brief and organizer-supplied project brief | Three fictional domains: travel, device support, and rooms, with latency/failure/cancellation modes. | Excellent interruption demonstration material when visibly labeled as sandbox data. |
| organizer-supplied project brief and organizer-supplied project brief | Thirteen bounded actions, revision/request evidence and duplicate suppression; actual status returned by Android. | Strong action-receipt foundation. Draft/opened is different from sent/saved. |
| organizer-supplied project brief and organizer-supplied project brief | AudioRecord/AudioTrack, local Silero VAD through ONNX, platform echo/noise effects when available, buffer retention and interruption confirmation. | You already have real streaming infrastructure. Improve semantics and measurement before changing models. |
| organizer-supplied project brief | Native Compose screens, sports profiles, weather, numbers, source rows, documents, phone receipts, and widget preview. | Sports has the deepest specialized treatment. Other domains are not absent, but many interactions are generic. |
| organizer-supplied project brief | Local library of up to forty results, recent transcript persistence, live connection and result navigation. | Saved display history is not a synchronized personal task database. |
| organizer-supplied project brief and organizer-supplied project brief | Real RemoteViews previews/pinning, clocks, lists, checklists and bounded read-only refresh. | Keep these as compact projections of cards; they cannot support every in-app interaction. |
| organizer-supplied project brief | More specialized document layouts, sources, timers, arithmetic, sports, exports, escaped content. | Some native/browser behavior already differs; define one data contract. |
| organizer-supplied project brief | Continuous PCM, playback state, noise recovery and microphone lifecycle handling. | Keep behavior aligned with Android without assuming identical detectors. |
| organizer-supplied project brief | Localhost restrictions, session endpoints, artifact export, media validation and widget refresh. | A deployed consumer relay needs authentication and a deliberate hosting change. |
| Tests, scripts, reports, design assets | Extensive deterministic checks, optional live/device checks, build helpers and approved visual references. | Preserve the visual identity; spend effort on behavior and evidence. |

The count is **14 built-in manifests + 3 sandbox domains**, plus **13 phone actions**. The README’s older “sixteen capabilities” wording should be reconciled with current code when documentation is next updated.

### 2.3 Strong foundations worth keeping

- Read relevance is checked against arguments, not only one global revision number.
- Prepared actions can be held while the user speaks.
- Submitted actions remain accounted for even if the conversation changes.
- Noise can pause speech without immediately throwing away all unheard audio.
- Public data, local computations, AI drafts, and synthetic inventory carry different provenance.
- The current UI already has an intentional visual identity. Another redesign of the sphere is low priority.
- Native widgets actually pin and retain useful data, instead of being static mockups.
- The app does not embed its Gemini API key in the APK.

### 2.4 The biggest gaps before adding a feature festival

| Finding | Evidence and practical meaning | Recommended action |
|---|---|---|
| **Official runner compatibility is still provisional** | Current timestamps/timers use wall-clock mechanisms; Samsung describes a virtual-clock harness and its own streams. | Add the exact adapter and clock seam once the kit arrives. Keep the product core reusable. |
| **One active domain is not a linked multi-task plan** | Session uses one active domain/slot set; prior task slots are keyed by domain. | Start with one explicit plan containing a few stable subtask IDs. Do not promise arbitrary concurrent projects. |
| **Same-kind cards can replace each other on the server shelf** | Workspace key is domain, or document domain plus document kind. Android separately retains result IDs. | Introduce stable card/task identity and revision-aware updates before building “my whole day.” |
| **Editing a document currently republishes the full draft** | Native instructions request complete revised document content. | Add stable item IDs and targeted edits so checked items, selection, and scroll position survive. |
| **Native document interactivity is uneven** | Native DocumentDetail displays numbered items; interactive checklist state exists in widget paths. | Make the main checklist and widget share item identities and completion state. |
| **The provider receive loop can wait on phone outcomes** | receive_provider awaits handle_tool; phone execution can wait for a device result for up to thirty seconds. | Test delayed device replies under interruption; keep provider ingestion responsive and represent pending work explicitly. This is a code-path risk, not a newly reproduced acoustic failure. |
| **Speculation is not uniformly implemented across voice paths** | The controller has a 350 ms provisional-input path; Live captions do not automatically become those partial-input events. | Demonstrate partial-input behavior separately and connect only bounded read speculation where it helps. |
| **Connection continuity needs work** | Live config enables context compression but does not configure provider session-resumption handles. | Add resumable transport without replaying submitted actions or treating reconnection as permission. |
| **Personalization is mostly settings and saved content** | Voices/haptics, a notebook, local result/transcript persistence; no explicit reusable preference model with scope/expiry. | Add small session preferences first; saved consumer preferences later. |
| **Hourly/actionable weather needs new fields** | Current adapter requests current conditions and daily forecasts. | Add hourly data before claiming “leave in a dry window” or “rain starts in twenty minutes.” |
| **Phone independence is incomplete** | Local relay is required. At audit time USB forwarding for port 8766 was not present. | Restore the normal dev setup before a live demo; deployment is a separate authenticated-relay task. |
| **Submission packaging is unfinished here** | This folder has no .git directory or Dockerfile. Its ignore rules exclude JSON reports. | Prepare the required repo/container/tag and intentionally include sanitized evidence selected for submission. |

A synchronous-only model tool interface is not the same thing as a requirement to block the application’s event loop. The current Gemini Live tool documentation marks Gemini 3.1 Flash Live function calling as synchronous-only; keep the existing “accepted/pending, then later evidence” pattern grounded in supported behavior and test it. [Gemini Live tool documentation](https://ai.google.dev/gemini-api/docs/live-api/tools).

Provider context compression and connection resumption solve different problems. Resumption support should follow the provider’s actual session-management protocol. [Gemini Live session management](https://ai.google.dev/gemini-api/docs/live-api/session-management).

### 2.5 Fresh verification from this audit

- **497 Python tests passed**, using the existing unittest discovery command, in approximately fourteen seconds on this machine.
- All three existing JavaScript suites passed: audio encoding/lifecycle, live-audio behavior, and workspace rendering/export. The renderer suite reports **72 checks**.
- ADB confirmed the S24, Android 16/API 36, One UI version value 80500, and installed THREAD version 0.4.0.
- The native THREAD opening screen was visually inspected. No microphone session was started for this audit.
- Historical native/device reports remain useful but are not fresh measurements. In particular, the selected current native-workspace report records **five executed cases**, not all thirty-four cases defined by its runner.

These are deterministic/controller/UI checks, not 497 successful natural-language conversations, independent users, or official Samsung scenarios.

## 3. Competition and honest differentiation

Research checked on 14 September 2026. Vendor announcements demonstrate prior art and stated capabilities, not equal availability in every country, account, or device. I did not run a controlled head-to-head benchmark.

| Existing product or research | What is already documented | Where THREAD can make a stronger specific demonstration |
|---|---|---|
| **Gemini Intelligence / Android** | App automation, informal multilingual dictation, and custom functional widgets described in natural language. | A visible, revision-aware plan where an interruption updates only affected work and clearly accounts for submitted actions. [Google announcement](https://blog.google/products-and-platforms/platforms/android/gemini-intelligence/). |
| **Gemini Live / Project Astra** | Camera/screen understanding, context, memory and action-oriented research. Astra remains a research prototype and feeds capabilities into Google products. | Explicit object/frame references, editable constraints, and measurable recovery under injected timing failures. [Project Astra](https://deepmind.google/models/project-astra/). |
| **Alexa+** | Personal memory, document context, calendars, recipes, routines, and actions; context can continue across supported surfaces. | A phone-centered work surface with precise changes, visible dependencies, and user-controlled attention. [Amazon feature catalog](https://www.aboutamazon.com/news/devices/new-alexa-top-features), [Alexa on the web](https://www.aboutamazon.com/news/devices/alexa-plus-web-ai-assistant). |
| **Samsung Galaxy AI / Bixby** | Now Brief/Now Nudge personalize context; conversational device assistance and web results are already part of Samsung’s direction. | Demonstrate the interruptible orchestration capability Samsung could integrate, rather than presenting another morning briefing as the breakthrough. [Samsung MWC overview](https://news.samsung.com/uk/samsung-advances-galaxy-ai-and-its-connected-ecosystem-at-mwc-2026). |
| **Be My Eyes / Be My AI** | Established visual assistance, human live video support and AI image descriptions with follow-up. | Focus on a bounded, revisable troubleshooting workflow with evidence and step state; do not claim visual assistance itself is new. [Be My Eyes guide](https://support.bemyeyes.com/hc/en-us/articles/360005528557-Getting-started-with-Be-My-Eyes). |

### 3.1 Claims we can defend

“THREAD keeps useful work consistent when the user changes the goal” is a claim we can test.

“THREAD has the first AI memory,” “no other assistant can be interrupted,” “Google cannot make custom cards,” or “works in every app” are not defensible claims.

A memorable product does not need every individual component to be original. The originality can be **the interaction, the combination, and the demonstrated reliability**. A judge can understand that in twenty seconds if the cards show the old constraint disappearing, the new constraint applying, and irrelevant results being excluded.

### 3.2 Why someone would open THREAD again tomorrow

The retention hypothesis is that a user comes back because:

1. Their unfinished work is immediately understandable.
2. They can change a detail in their own words.
3. Related information changes together.
4. The assistant produces something they can use or complete.
5. It is quiet when nothing needs their attention.

Validate that with users; do not confuse a long first conversation with ongoing usefulness.

## 4. Product direction and personal context

### 4.1 Initial audience

Until a different primary audience is selected, center the product on **everyday planning and hands-free task completion**, with accessibility as a core interaction requirement. Examples: leaving home, preparing dinner, fixing an unfamiliar device, organizing a trip, and recovering from a changed plan.

These are examples of intended use, not claims about Ansh’s private habits, diet, relationships, health, or schedule.

### 4.2 “Personal” must change the decision

Weak personalization: “Hello Ansh” above a generic weather card.

Useful personalization: “You said you’re walking at 6:30. The forecast has a drier period earlier; here are two alternatives.” The card explains the context it used and lets the user correct it.

Start with explicit inputs:

| Context | Example | Scope |
|---|---|---|
| Active goal | “Get me home by ten.” | Current task. |
| Hard constraint | “No stairs for this outing.” | Current plan, until changed. |
| Soft preference | “I’d rather walk.” | Current plan; can be relaxed visibly. |
| Resource limit | “₹1,200 total, four people.” | Current plan, including per-person calculations. |
| Response preference | “Just the short answer for now.” | Current conversation or until reset. |
| Chosen interest | “Follow this team.” | Current session; saved only through an explicit consumer feature. |
| Shared evidence | A user-selected menu or manual page. | Associated task and attachment. |
| Temporary exception | “Today I’m taking a cab.” | Today/current task; does not silently replace a lasting preference. |

### 4.3 Two explicit operating modes

**Evaluation mode:** fresh per-scenario state; supplied manifest/corpus; session preferences only; no local notebook search, old widget data, previous-user preferences, or other cached personal context leaking into a scenario. Persisting a trace as an output is distinct from reading it as future task memory.

**Consumer mode:** optional saved preferences and useful artifacts, with clear controls for scope, source, editing, expiration, and deletion. Reuse SQLite for a small explicit data model. There is no need for a vector database just to remember a city, a team, or a preferred unit.

The present external adapter flag alone is not proof of complete evaluation isolation. Treat isolation as an acceptance test.

### 4.4 The personal card contract

Each personal card should be able to answer:

- What is this helping me do?
- Which facts came from me, a source, a computation, or an AI draft?
- What changed since I last saw it?
- How old is the relevant evidence?
- What is the next useful action?
- Can I change this by voice or touch?
- What will remain if I leave the conversation?

No permanent personal fact should be inferred from a single hypothetical question. “Find vegan recipes for a friend” is not “I am vegan.” “I’m exhausted today” is not a medical diagnosis or a permanent user trait.

## 5. Twenty-four standout features

Effort estimates below are rough **focused engineering days for a narrow prototype**, assuming familiarity with this codebase. They are not guarantees, do not include account approval delays, and overlap when features share infrastructure. Do not add all estimates and treat the result as the four-person schedule.

**Build** means recommended for the submission. **Choose** means select if the core is stable. **Later** means a product opportunity after the submission baseline.

### F01. Live Plan Repair

**Build. Extends existing slot correction; linked planning is new. Estimate: 2–4 days after stable task/card IDs.**

“Move dinner to eight, but keep the budget and the restaurant.”

The timeline moves, the preparation window changes, and any dependent reminder becomes a proposed update. The budget and chosen place remain. A previously fetched forecast can remain if its location/time coverage still applies.

Make the change visible as a short annotation: **Dinner 7:00 → 8:00 · budget kept · departure needs review**. Update the existing card instead of filling the library with near-duplicates.

Smallest useful build: one outing plan with three dependent components: a timeline, a budget, and a checklist. Use typed dependencies for time, participants, place, and amount. Recompute deterministic fields locally. Ask the model only to revise genuinely textual material.

**Proof:** change participants twice while one source is delayed. Totals and checklist quantities match the final participant count, and the old response never replaces the latest plan.

### F02. Undo the Last Change

**Choose. New task-history feature. Estimate: 1–2 days.**

“No, undo just the budget change.”

Maintain a small bounded history of accepted task patches. Restore the previous budget while preserving a later venue change. A visible changes sheet lets a user inspect what will be restored.

The unit of undo is an identified change, not an arbitrary rewind of the entire world. If an action has already been submitted, say which part can be restored in the plan and which requires a separate cancellation or compensating action.

Smallest useful build: ten session-only patches, each with changed fields, previous values, input evidence, and resulting revision. Undo must itself create a new revision.

**Proof:** undo participant count after a new weather result arrives; keep the weather result, restore the count, recompute the split. Do not repeat a previously submitted booking.

### F03. Branch the Plan

**Choose. Extends side comparisons. Estimate: 2–3 days.**

“What if we go tomorrow instead? Don’t change tonight yet.”

Show two versions side by side, with only meaningful differences emphasized: forecast, available time, estimated cost, and unresolved availability. The active plan remains selected until the user adopts a branch.

This is useful for comparing budgets, venues, departure times, recipes, or meeting slots. It removes the fear of experimenting with a plan the assistant has already assembled.

Smallest useful build: a single active branch and one alternative within one session. Comparison reads may run independently; neither branch may submit a new action implicitly.

**Proof:** a result for the alternative returns late. It stays in the alternative card. “Use tomorrow” copies the selected branch’s approved fields, invalidates stale proposals, and requests only necessary new work.

### F04. Side Question, Then Right Back

**Build. Extends previous-task handling. Estimate: 1–2 days.**

While receiving troubleshooting instructions: “Wait, what does that symbol mean?”

THREAD answers, then returns to **step three, the exact component, and the still-relevant evidence**. The user should not have to explain the device again.

Smallest useful build: a depth-two bookmark stack with task ID, selected item, current step, paused speech position or summary, and current constraints. A breadcrumb says **Back to: connecting the router**.

Distinguish a side question from an actual goal switch. When unclear, offer “Keep this plan open?” once rather than silently abandoning it.

**Proof:** ask a calculation during a plan, correct the calculation, then say “continue.” The plan resumes unchanged; the side calculation does not inherit flight or recipe slots.

### F05. Point and Correct

**Build. Extends deliberate image sharing; explicit pointing is new. Estimate: 2–3 days.**

“What does this light mean?”

“No, this one on the left.”

The user taps a region on the shared photo. A small visible marker becomes part of the request, alongside the frame ID and timestamp. THREAD replaces the target, fetches the matching manual evidence, and keeps unrelated device facts.

Smallest useful build: still photo plus user-selected point/rectangle. There is no need for continuous camera tracking or AR to make this impressive.

A new photo invalidates old coordinates. If labels are unreadable, show the uncertain region and ask for the missing label.

**Proof:** the old manual lookup returns after the correction. It is excluded. The final answer cites the corrected target and does not infer blinking from one still image.

### F06. Wait, Don’t Do That

**Build. Strongly extends an existing capability through better presentation. Estimate: 1–2 days plus verification.**

The assistant prepares a booking or note save. The user interrupts before submission, after submission, or after completion. The resulting receipt shows **not submitted**, **cancellation requested**, **cancelled**, **completed**, or **outcome unknown** as appropriate.

Make this feel useful, not like a developer console: “I stopped it before submission” is different from “I asked the service to cancel; I’m still checking.”

Use a deterministic sandbox booking for late/uncertain outcomes. Use a real local note save or phone handoff for another outcome. Label each correctly.

**Proof:** duplicate result notifications, lost replies, and repeated stop commands cannot create a second write. A failed cancellation never turns into a green success card.

### F07. Cards You Can Talk To

**Build. New shared voice/touch targeting. Estimate: 2–3 days across the first card families.**

“Make that one cheaper.”

“Delete the second item.”

“Keep the venue, change the time.”

Touch selection should give voice an unambiguous reference. Voice edits should update the exact selected item. The same command can apply to a meal, a source shortlist, a checklist, or a travel option, using that card’s supported operations.

Smallest useful build: selection context containing card ID, revision, and item ID; a small allowed-action list per family. Do not execute model-generated UI code.

**Proof:** say “the second one” after the list has reordered. Use the visible item identity or clarify; do not act on a different item because it occupies the same array index.

### F08. Non-Negotiables

**Build. New user-facing layer over existing constraints. Estimate: 1–2 days.**

“Under ₹1,500 total. Walking only. Home before ten.”

Display a small strip of constraint chips. Mark which are hard requirements and which are preferences. If no result satisfies all hard requirements, show the conflict instead of quietly relaxing one.

A correction such as “we can spend another two hundred” edits the budget and nothing else. “A cab is okay if it rains” creates a conditional preference, not an unconditional transport switch.

Smallest useful build: explicit numeric/time constraints plus a small set of boolean/categorical constraints for one hero task.

**Proof:** every displayed recommendation either satisfies the current hard constraints or clearly states the exact unresolved/violated constraint. A user not repeating a constraint does not remove it.

### F09. The Assistant That Waits Properly

**Build. Extends audio/floor handling. Estimate: 2–4 days for bounded behavior and real speech checks.**

“Set it for… um… Thursday, actually Friday…”

Hold the conversational floor through an unfinished phrase. Distinguish acknowledgment, hesitation, a corrective interruption, and an explicit stop. Give a visible “I’m listening” state without spraying filler words.

Do not claim that Silero VAD understands intent. VAD estimates speech activity; transcript/context and a bounded policy handle the meaning.

Smallest useful build: an adjustable patient mode, tests for hesitant dates and names, and a clear “I’m finished” option for users who prefer it. Avoid per-person learned voice profiles in evaluation.

**Proof:** hesitations do not submit an action; a real “stop” still cuts playback promptly. Test Hindi/English self-repairs with consenting speakers, not just English text fixtures.

### F10. Tell Me Only What Changed

**Build. New delta-oriented presentation. Estimate: 1–2 days.**

“What’s different from before?”

Instead of rereading a full itinerary, THREAD says: “The departure moved twenty minutes earlier. The venue and total stayed the same.” Cards highlight those fields and offer the detailed before/after record.

This is valuable for refreshed weather, a reworked budget, a changed meeting, and a sports result. It also reduces repeated speech after interruptions.

Smallest useful build: compare typed fields of the old and current card revision, with deterministic handling of numbers and dates. Use short model wording only after the difference is computed.

**Proof:** an irrelevant metadata refresh does not produce a spoken alert. Missing data is described as missing, not interpreted as zero or a negative change.

### F11. Attention Contract

**Choose for a bounded in-session demo; persistent monitoring later. Estimate: 2–3 days in-session.**

“Keep an eye on the plan, but only interrupt if I need to act.”

Let the user choose a condition, deadline, and delivery mode. Example: “Tell me if the event time changes before I leave; otherwise just update the card.”

The monitor card must show what is watched, the last successful check, when monitoring ends, and whether a notification path is active. A refresh animation is not a monitor.

Smallest useful build: one deterministic in-session event source and one threshold. Persistent background checks need scheduling, expiry, connectivity handling, and permission-aware notifications.

**Proof:** repeated unchanged observations remain silent. One material change produces one alert. Dismissal or “stop watching” actually stops future checks.

### F12. Share Anything Useful Into a Task

**Build for text/images; choose PDF import. Estimate: 1–3 days.**

Share a menu, event poster, screenshot, or message into THREAD. It extracts relevant fields into a reviewable card rather than leaving the attachment buried in chat.

“Plan around this.”

“That’s the old date; use the date I just said.”

Keep the original excerpt/crop attached to each extracted field. User corrections can supersede the extracted value without deleting the source.

Smallest useful build: existing Android share target plus structured extraction for one format, such as an event poster. File import, PDF parsing, and durable attachment storage are additional work.

**Proof:** uncertain OCR does not silently become a confirmed address or time; pasted instructions inside the image cannot authorize a phone action.

### F13. Leave at the Right Time

**Choose. New composition of several data sources. Estimate: 2–4 days with a route provider; simpler manual-duration version in 1–2.**

“I need to reach the library by six, and I’m walking.”

Show latest departure, preparation time, route duration, weather coverage, and the assumptions used. “I’m taking a cab instead” changes the appropriate fields.

Begin with a user-supplied journey duration if route integration is not ready. Label it **your estimate**. A public map launch alone cannot supply a verified ETA.

The personal value comes from the combined decision: when to leave and what to take. A temperature reading alone does not make this feature.

**Proof:** change destination during the route lookup. Only the corrected route can set departure time. Stale or unavailable routing cannot produce a confident deadline.

### F14. Dinner Rescue

**Choose. Strong everyday hero alternative. Estimate: 2–4 days.**

“I have these ingredients and twenty-five minutes.”

“Wait, no oven. And make it for four.”

Produce a recipe timeline, scaled ingredient checklist, and independent timers. Voice advances the current step, explains an unfamiliar technique, and resumes the cooking flow.

Smallest useful build: user-entered or photographed ingredient list, explicit equipment constraints, a drafted recipe, deterministic quantity scaling for supported units, and the existing phone Clock timer handoff.

A photo cannot establish food freshness, exact weight, allergy safety, or a cooking temperature. Mark uncertain quantities; do not let unsupported estimates become safety claims.

**Proof:** removing an ingredient updates the relevant recipe draft; it does not reset an already running real timer or automatically issue another one.

### F15. Personal Decision Table

**Build with user-provided options; live commerce later. Estimate: 1–2 days.**

“Which of these three works best for me?”

Compare options against explicit criteria: budget, time, portability, compatibility, or venue accessibility. Show the evidence behind each comparison and allow the user to change priorities.

“Ignore looks. Battery matters more.”

Re-rank the same options transparently. Keep missing specifications blank and explain when the evidence is insufficient.

Smallest useful build: existing document comparison tables plus typed criteria and option IDs. Use user-provided facts or cited source fields.

**Proof:** reweighting changes ranking without inventing new specifications. A source snippet alone cannot become a verified claim about an uninspected product manual.

### F16. Explain the Card at My Level

**Choose. Extends voice and existing document/source content. Estimate: 1–2 days.**

“Just give me the conclusion.”

“Now explain why.”

“Use an example from what I’m doing.”

The assistant changes explanation depth while keeping the underlying result intact. Selecting a chart point, formula term, manual sentence, or table row grounds what “this” means.

Smallest useful build: brief/detail controls and one selected evidence anchor. Store response-depth preference for the session.

**Proof:** asking for simpler wording does not alter numeric values, switch units, or trigger unrelated tool calls. A ten-second spoken summary and the visible card agree.

### F17. Live Form Repair

**Choose. New structured form interaction. Estimate: 2–3 days.**

“Write a support request. The model is A15—sorry, A16—and it started yesterday.”

Fields fill as the user speaks, but uncertain values remain provisional. Edits are local and the final review shows exactly what will be submitted or handed off.

Useful domains include support tickets, meeting drafts, expense notes and travel requests. This demonstrates generalization without third-party screen automation.

Smallest useful build: render a supplied closed schema as labels and editable fields. For the hackathon, use the supplied unfamiliar capability manifest to choose fields rather than hardcoding a support-only form.

**Proof:** the corrected model number appears in the actual tool arguments. Saying “yes, that date is right” does not independently authorize submission.

### F18. A Personal “Where Were We?” Card

**Build for current-session tasks; saved consumer continuity later. Estimate: 1–2 days.**

After a side question or reconnect, show: **You were choosing an option · budget fixed · date unresolved · no action submitted**.

This is a compact view of actual state, not a speculative chat summary. It should let someone continue with one sentence.

Smallest useful build: derive the card from selected task state, current result, unresolved action receipts, and missing required fields. On reconnection, reconcile uncertain submitted work before offering a retry.

**Proof:** a reconnect cannot silently reauthorize an old action. Ending a session in evaluation clears this card before the next scenario.

### F19. Personal Memory You Can Inspect

**Later; session version belongs in the initial build. Estimate: 2–3 days for a small consumer preference store.**

“Use Celsius.”

“Remember this for trips, not for everything.”

Each saved preference records its source, scope, and optional expiry. A “Why this?” control says which preferences affected the card. The user can edit or delete the fact directly.

Smallest useful build: explicit fields such as units, named city, favorite teams, budget conventions and response style. Reuse SQLite; use exact filters before semantic retrieval.

**Proof:** a temporary exception does not overwrite the default. Deleting a preference removes it from future prompts and dependent personalization. Evaluation never reads this store.

### F20. Offline Continuity

**Choose for results; later for offline voice. Estimate: 1–2 days for clearer degradation, substantially more for local speech.**

If the network disappears, keep the plan, calculations, clocks and already downloaded evidence usable. Explain which fields are stale and which actions still work locally.

The attractive behavior is continuing useful work without pretending the cloud is available. A saved weather report remains old weather. An unsent action stays unsent.

Smallest useful build: durable card state, deterministic local controls, last-updated labels, and explicit reconnect. Existing local widgets/clocks provide a foundation.

**Proof:** going offline cannot erase checklist progress, show a fake fresh result, or repeat an external write on reconnect. Do not call current Gemini voice offline because its VAD runs locally.

### F21. Meeting and Conversation Repair

**Later, or a short text-based showcase. Estimate: 3–5 days for a controlled live session.**

In a user-started meeting capture: “The deadline is Friday—actually Monday.”

The action item changes in place, with the correction attributed to the relevant turn. A tentative assignment stays tentative until accepted by the responsible person. No automatic email is sent.

Smallest useful build: participant-entered names and a live action-item board for one consented session. Diarization, calendar accounts, multi-party identity and long recording retention add real complexity.

**Proof:** a quoted earlier deadline does not supersede the current one. The system distinguishes a suggestion from a commitment.

### F22. Real-World Checklist

**Choose. Extends images, documents and checklists. Estimate: 2–3 days.**

“Help me pack from this list.”

The phone shows a large checklist. Voice marks an item done; a deliberate camera check may propose that a visible object matches an item. “That’s the wrong charger” unchecks the proposed match and preserves the rest.

Smallest useful build: user-driven completion first, optional image-assisted suggestions. Never silently mark important items packed because a similar-looking object appeared in a photo.

**Proof:** changing the trip from two days to four updates quantities while preserving manually completed items whose meaning has not changed.

### F23. Describe a Small Tool

**Choose. Extends existing structured documents/widgets. Estimate: 2–3 days for a few approved templates.**

“Make me a trip cost calculator with fuel, tolls, and four people.”

THREAD instantiates a known calculator template with editable fields. “Five people” changes the model and output immediately. The user can pin a compact summary.

The power comes from a useful custom control surface backed by deterministic operations. It does not require arbitrary generated JavaScript, Kotlin, or a generic app-builder platform.

Smallest useful build: bill split, date planner, packing quantities, and comparison scorecard templates.

**Proof:** generated configuration passes a closed schema; unsupported calculations are rejected clearly; tool output and spoken values match.

### F24. Break THREAD

**Build. Extends the existing challenge concept and sandbox. Estimate: 1–2 days.**

Give the evaluator a controlled challenge: “Change any two details while it’s working.” Let them delay a result, duplicate a notification, or stop a prepared action.

The product screen remains understandable. A separate evidence view shows changed slots, affected calls, excluded results, and final action status. Record failures honestly.

The novel impression comes from allowing interruption to be the demonstration, not the thing the team hopes the judge avoids.

**Proof:** the visible outcome is derived from actual events. A challenge cannot be marked passed because the assistant merely said the right sentence. Do not reveal or speculate about hidden organizer cases.

## 6. The interruption vocabulary

An interruptible product needs a vocabulary of meaning, not one generic cancel button. These are proposed behavioral acceptance cases; some already have controller support, and others need extension.

| User says | Intended operation | What must remain correct |
|---|---|---|
| “Mumbai, not Delhi.” | Replace a field. | Date, origin, people and other unchanged constraints. |
| “Make that Friday.” | Correct a referenced date. | Resolve which active date; preserve other dates. |
| “Actually four of us.” | Change participants. | Update dependent quantities/splits, not unrelated preferences. |
| “Wait.” | Hold work at a safe boundary. | Retain results and account for submitted actions. |
| “Stop talking, keep searching.” | Stop speech only. | Current relevant read continues. |
| “Cancel the whole plan.” | Cancel the task scope. | Unrelated notes or other tasks remain. |
| “Never mind the budget limit.” | Remove an explicit constraint. | Require evidence of removal; no silent deletions. |
| “Don’t remove the budget.” | Preserve a constraint. | Negation must not become permission to remove it. |
| “Uh-huh.” | Acknowledge. | Do not treat it as authorization to write. |
| “Um… one second.” | Hold the floor. | Do not endpoint the unfinished instruction as complete. |
| “No, this one.” + tap | Replace referenced item. | Use stable item ID and current card revision. |
| “What does that mean?” | Side explanation. | Preserve task, step and selection. |
| “Continue.” | Return to bookmarked work. | Resume from current valid state, not a stale script. |
| “Compare tomorrow, keep today.” | Branch a read-only alternative. | Do not alter the active plan. |
| “Use the cheaper version.” | Adopt a selected branch. | Revalidate relevant facts before new actions. |
| “Undo the last time change.” | Reverse one task patch. | Later unrelated corrections survive. |
| “Keep the top two.” | Filter a visible collection. | Identity remains stable after filtering. |
| “Same, but for my return trip.” | Create a related task. | Explicitly swap/resolve directional fields; no inherited mistakes. |
| “Say less.” | Change response style. | Do not cancel or modify work. |
| “I only have five minutes now.” | Change an available-time constraint. | Revise relevant plan steps; do not erase required steps silently. |
| “Not today—remember it for next week.” | Rescope a proposal. | Saved/monitor behavior exists only if the user enables the relevant consumer feature. |
| “Did it actually happen?” | Reconcile/check status. | Separate provider evidence from the assistant’s earlier words. |
| “I didn’t say anything.” | Noise recovery. | Resume unheard audio only when no real correction or stop superseded it. |
| “Ignore that sound; carry on.” | Explicit recovery. | Do not repeat completed actions or already heard content unnecessarily. |

Test corrections during perception, planning, reads, prepared writes, submitted writes, generated audio, buffered playback, and reconnection. A feature that only works after the assistant finishes speaking does not demonstrate the intended interaction.

## 7. What makes a card premium

### 7.1 A premium card is a small working surface

It combines **a decision, a compact visualization, editable inputs, and the next useful action**. It should not be a paragraph inside a rounded rectangle.

The current sports work demonstrates useful principles: recognizable subject identity, a strong headline metric, domain-specific detail, and expandable evidence. Transfer those principles to other subjects without giving everything a scoreboard.

### 7.2 Anatomy

| Layer | What belongs there | Example |
|---|---|---|
| Personal context | A short explanation of relevant explicit context. | “For your 6:30 walk.” |
| Primary answer | One decision or quantity worth noticing. | “Leave by 5:50.” |
| Supporting visual | A timeline, range, comparison, chart, or step indicator. | Travel + preparation + buffer. |
| Editable inputs | Touch targets that voice can also reference. | Destination, travel mode, arrival time. |
| Main action | One dominant, honest next step. | “Open route” or “Prepare reminder.” |
| Secondary controls | A few relevant alternatives. | Compare, pin, explain, change units. |
| Evidence | Source, observed time, retrieved time, uncertainties. | “Duration from your estimate; forecast checked at…” |
| Change annotation | The latest material update. | “Walking → cab; arrival target kept.” |
| Persistence | What survives leaving the screen. | Saved checklist; live source needs refresh. |

### 7.3 Eight design rules

1. **The result gets the space.** After a result arrives, let the compact voice dock accompany it. Avoid forcing users to stare at the sphere while their actual task is hidden.
2. **Use subject-appropriate layouts.** A recipe needs steps and timers; a forecast needs a time band; a comparison needs aligned attributes.
3. **Personalize through relevance.** Lead with the user’s active decision, not a synthetic personality profile.
4. **Animate the changed part.** Preserve visual identity, scroll position, checked items, and selection. Respect reduced motion.
5. **Keep units and time zones explicit.** A beautiful but ambiguous number is not premium.
6. **Build empty, partial, stale, and failed states.** Those states should remain usable and visually intentional.
7. **Use large reachable controls and semantic labels.** Support TalkBack, large text, touch, and voice as real interaction paths.
8. **Make content density adjustable.** Compact, comfortable, and detailed modes can use the same underlying card.

### 7.4 Use a small number of renderer families

Start with reusable families, not one new screen class per topic:

| Family | Appropriate content |
|---|---|
| Metric | Amounts, dates, conversions, countdowns and simple status. |
| Timeline | Trips, preparations, cooking stages and schedules. |
| Collection | Sources, matches, products, places and saved items. |
| Comparison | Options, scenarios and before/after decisions. |
| Checklist | Packing, ingredients, troubleshooting completion and tasks. |
| Stepper | Guidance, recipes, forms and learning sequences. |
| Evidence | Excerpts, image crops, tables, citations and source disagreement. |
| Action receipt | Drafted, prepared, submitted, completed, failed or unknown outcomes. |
| Clarification | Ambiguous people, places, dates, objects or units. |
| Chart | Time series, distributions and trends with actual numeric data. |
| Spatial | Map/route or a user-selected image region; no invented geometry. |
| Monitor | Condition, last check, expiry and delivery policy. |

A sports card can be a specialized combination of collection, metric, and chart. A “leave now” card can combine timeline, weather data, and an action. Sharing primitives does not mean every card looks identical.

### 7.5 One contract for voice, touch, Android and widgets

Suggested fields to add incrementally:

| Field | Purpose |
|---|---|
| card_id / task_id | Stable identity across updates, as distinct from one returned result batch. |
| revision | Reject taps or commands based on superseded state. |
| family / schema_version | Choose a supported renderer and validate its payload. |
| title / summary / payload | Present the actual result. |
| inputs / constraints | Make assumptions and editable values visible. |
| item_ids | Keep a particular row stable when sorting or refreshing. |
| source_records | Link important fields to source IDs, observed dates and retrieved dates. |
| personal_context | Only the explicit scoped facts used to personalize this card. |
| actions | Allowed typed operations with required fields and real outcome semantics. |
| dependencies | A small explicit list of fields/results this card depends on. |
| status / freshness | Loading, partial, current, stale, failed, unavailable or completed. |
| delta | User-visible material change from the prior accepted revision. |

Do not let model output define arbitrary executable UI or arbitrary tool URLs. It chooses among reviewed families and actions.

### 7.6 Voice and touch must update the same state

A checklist tick on Android must refer to the same item as “mark charger packed.” A widget should use the same state where synchronization is supported. If a widget has only a saved snapshot, say so and reconcile deliberately on reopening.

Current widget check state and native document state are not yet one universal model. Do not describe this consistency as already implemented.

### 7.7 Freshness has three dimensions

- **When the fact happened:** match date, published date, weather observation time.
- **When THREAD retrieved it:** the fetch timestamp.
- **Whether it still applies:** an old result can be irrelevant even if it was fetched seconds ago.

“Retrieved now” does not turn yesterday’s match, a stale gate notice, or an old price into current truth. Card refresh should preserve prior valid data during failure and disclose its age.

### 7.8 Personalization without silent surveillance

Use a visible “Why this?” sheet: **You said walking · you selected this venue · arrival target is six**.

Offer “only for this task,” “for this session,” and, in consumer mode, “save as a preference.” Offer deletion and expiration. Exclude private details from exported/shared cards unless the user intentionally includes them.

Do not assume access to notifications, contacts, email, calendars, health history, location, or other app screens. The current application does not have those integrations. A shared screenshot can be a useful starting point without broad account access.

## 8. Eight card blueprints

All values below are **illustrative design examples**, not current readings, bookings, private user facts, or measured timings.

### B01. The Plan Card

**Example:** an outing for four people, home before ten.

Display a compact timeline with three stages, a total budget, per-person split, and pinned constraints. Each stage has a stable ID, editable start/duration, and a completion state. The voice dock stays available at the bottom.

Main action: **Review next step**. Secondary actions: compare a version, edit constraints, open the relevant source.

Interrupt: “Skip the café.” Remove only that stage, recompute the available time, and preserve the dinner choice. Completed steps do not return to “not started.”

Failure state: a missing route is explicitly labeled; the card can still show user-supplied durations.

### B02. The Weather Window Card

**Example:** a user says they plan to walk this evening.

Lead with a decision-relevant forecast summary, then an hourly precipitation/wind band and the chosen time range. Personal context reads “For the walk you planned,” not “we detected your routine.”

Main action: **Use this time in the plan**. Secondary actions: change activity, location, or units.

Interrupt: “Tomorrow, and I’m cycling.” Change date and relevant weather dimensions; fetch the appropriate hourly coverage.

Failure state: retain the older forecast, display its age, and disable unsupported precise recommendations. Current daily data alone is insufficient for this blueprint.

### B03. The Split and Budget Card

**Example:** ₹1,200 shared by four people.

Use a large per-person amount, total, participant chips, and an optional breakdown. Show rounding explicitly when individual shares do not sum evenly.

Main action: **Use in plan**. Secondary actions: add an expense, change the split, copy the breakdown.

Interrupt: “One person already paid two hundred.” Ask whether that means an advance payment or a smaller share if unclear; do not silently choose.

Failure state: invalid inputs remain visible with a clear correction. This is arithmetic and a settlement suggestion, not a payment transfer.

### B04. The Personal Shortlist

**Example:** three places or products supplied by the user or a verified provider.

Show two or three comparable attributes per option, a “fits your constraints” explanation, and missing-data indicators. A preference slider or chip can re-rank only supported fields.

Main action: **Choose this option**. Selection does not purchase or reserve.

Interrupt: “Only compare the first and third.” Keep their IDs, reflow the table and retain sources.

Failure state: show unavailable criteria rather than an invented all-in-one score. A score must expose its assumptions and weights.

### B05. The Living Checklist

**Example:** packing for a four-day trip.

Use grouped items with stable IDs, quantities, checked state, and a clear remaining count. Voice commands, touch ticks and supported widget interactions refer to those IDs.

Main action: **Continue packing**. Secondary actions: change duration, add an item, pin summary.

Interrupt: “Actually only two days.” Revise quantities, preserve completed items, and flag items whose meaning changed enough to require review.

Failure state: local interaction continues offline. A new model draft cannot silently overwrite manual progress.

### B06. The Evidence Card

**Example:** the selected indicator in a device photo and the associated manual page.

Show the source crop or excerpt, a visible target marker, and a concise explanation. Distinguish user-reported symptoms from visible labels and sourced instructions.

Main action: **Try the next supported step**. Secondary actions: select another region, view the source, explain a term.

Interrupt: “I meant the lower light.” Change target and manual lookup, retaining the known device model when still supported.

Failure state: offer a clearer-photo or missing-label clarification; do not invent what cannot be read.

### B07. The Action Receipt

**Example:** a calendar draft opened in Android, or a sandbox booking that is pending.

Show the intended action, exact material details, current status, and available next step. Provide a short expandable history: prepared, submitted, acknowledged, reconciled.

Main action depends on state: **Review in Calendar**, **Check status**, or **Request cancellation**.

Interrupt: “Wait, wrong date.” Stop an unsubmitted action; if already handed off or submitted, disclose that boundary and handle the supported correction path.

Failure state: “outcome unknown” stays neutral and actionable. Do not replace it with “failed” merely because the reply timed out.

### B08. The Clarification Card

**Example:** two cities with the same name, or an ambiguous spoken time.

Show the smallest set of meaningfully different choices, each with the distinguishing field. The voice question is short: “Manchester in the UK or the US?”

Main action: **Select a candidate**. The user can also say it.

Interrupt: “Neither; Manchester, Jamaica.” Accept a new explicit value and validate it. A multiple-choice display is not a closed universe of allowed answers.

Failure state: if the user’s answer does not resolve the ambiguity, explain exactly what is still missing without repeating the entire request.

## 9. The 160-card opportunity catalog

This is a broad, deliberately finite catalog across twenty domains. There is no literal exhaustive list of every useful future card. These 160 concepts cover ordinary daily use and several distinctive opportunities without pretending they are all implemented.

**Every row describes a proposed card or upgrade.** The route column identifies the underlying path:

- **E — Extend:** some source/tool/UI foundation already exists; the proposed behavior still needs work.
- **N — New local behavior:** deterministic logic, session state, or a new renderer; no new external account is inherently required.
- **D — Draft/import first:** useful with explicit user data or AI-drafted material; no implied live facts or external action.
- **I — Integration:** a real data provider, account authorization, device capability, or external receipt is required.
- **P — Consumer persistence:** a saved preference, background monitor, or cross-session/shared state feature; exclude it from evaluation memory.

Routes can be combined. Effort and access vary within each family. A “monitor” row always means an actual scheduled or event-driven implementation with expiry; it does not describe current widget refresh as a general monitoring service.

### 9.1 Conversation and task control

| ID / Card | Personal, useful behavior | Signature interaction | Route |
|---|---|---|---|
| C001 · Current mission | Active goal, progress, missing detail, and your fixed constraints in one place. | “Change the destination, keep everything else.” | E + N: session state and stable task identity. |
| C002 · Change receipt | The precise fields your latest correction changed, plus what stayed. | “Why did the total change?” opens computed differences. | E + N: slot events and typed deltas. |
| C003 · Branch comparison | Your actual plan next to one alternative, with meaningful differences. | “Try tomorrow without replacing today.” | E + N: comparison reads and branch state. |
| C004 · Side-question bookmark | Current step, selected item, and the task waiting underneath a side discussion. | “Continue where we were.” | E + N: bounded task stack. |
| C005 · Non-negotiables | Editable hard constraints and softer preferences, with conflict markers. | “Cab is okay, but keep the cost limit.” | E + N: constraint priority and evidence. |
| C006 · Action receipt | What you asked to happen, actual submission status, and available recovery. | “Did it really save?” checks evidence. | E: operations and phone outcomes; richer renderer. |
| C007 · Clarify one detail | A small set of relevant candidates with the exact difference highlighted. | “The one in the UK.” | E + N: candidate IDs and targeted questions. |
| C008 · Capability card | Shows what the currently supplied unfamiliar tool can really do and which fields it needs. | “Use this new service for the same request.” | E + N: dynamic manifests, schema form. |

### 9.2 Your day and time

| ID / Card | Personal, useful behavior | Signature interaction | Route |
|---|---|---|---|
| C009 · Today’s plan | A timeline built from the commitments you shared, with realistic buffers. | “Move lunch, keep my appointment fixed.” | D + N; I for calendar reads, P for daily continuity. |
| C010 · Next free window | Find usable time between your supplied commitments, including a chosen buffer. | “I need forty minutes, not twenty.” | N from entered intervals; I for live calendars. |
| C011 · Leave-by countdown | Arrival target minus travel, preparation and buffer, with assumptions visible. | “I’m walking now.” | N + I for sourced route duration; D for your estimate. |
| C012 · People’s world clocks | Clocks for the cities you named, with working-hour overlays. | “Add Tokyo; show overlap tomorrow.” | E: world clocks; N for availability bands. |
| C013 · Event countdown | Time until a named event with preparation milestones. | “The event moved to Sunday.” | E + N; P for persistent reminders. |
| C014 · Focus session | One task, chosen duration, pause state and a return note. | “Give me five more minutes.” | E: timer; N for task linkage. |
| C015 · Schedule conflict | Explain why two commitments overlap and show bounded repairs. | “Keep the meeting; move the errand.” | N from supplied times; I for account calendars. |
| C016 · Day recovery | Re-plan the remaining day after a delay, preserving fixed commitments. | “I lost an hour; what should change?” | D + N; I only for fresh outside information. |

### 9.3 Weather and being outside

| ID / Card | Personal, useful behavior | Signature interaction | Route |
|---|---|---|---|
| C017 · Activity weather | Relevant forecast fields for your named walk, ride or outdoor event. | “Same time, but cycling.” | E + I: extend weather fields and activity rules. |
| C018 · Rain window | Hourly precipitation band around the time you intend to leave. | “Show two hours later.” | I: hourly forecast extension; not current daily-only data. |
| C019 · Air-quality window | Sourced air-quality readings with time and location, for a chosen outdoor period. | “Compare morning and evening.” | I: AQ provider; no medical interpretation. |
| C020 · Sun and UV planner | Daylight/UV fields aligned to your chosen outdoor schedule. | “Move the picnic into shade hours.” | I + N: forecast coverage and stated assumptions. |
| C021 · What to take | An editable weather-related checklist for your actual outing. | “I’ll have a car, remove walking gear.” | E + D + N: weather plus checklist. |
| C022 · Two-place weather | Compare origin and destination conditions side by side. | “Keep home on the left; change destination.” | E + N: two stable weather cards. |
| C023 · Stargazing conditions | Cloud/daylight conditions for a user-selected place and time. | “Only show a clear interval after ten.” | I: appropriate astronomy/cloud data; coverage disclosed. |
| C024 · Weather change watch | Watch a condition for a user-requested event and alert only on material change. | “Only tell me if I need to move indoors.” | I + P: threshold, expiry, scheduler, notifications. |

### 9.4 Commute and local movement

| ID / Card | Personal, useful behavior | Signature interaction | Route |
|---|---|---|---|
| C025 · Route choice | Routes compared against your time, budget and travel-mode constraints. | “Avoid tolls; keep arrival before six.” | I: route provider; E for map handoff. |
| C026 · Errand sequence | Order your selected stops around hours and a chosen finishing point. | “Skip the pharmacy, add groceries.” | D + N; I for current hours and routing. |
| C027 · Transit departure | Relevant next departures for a selected stop and destination. | “Show the accessible route instead.” | I: operator/GTFS coverage, verified accessibility fields. |
| C028 · Pickup spot | A shared pickup location, meeting instructions and map handoff. | “Use the west entrance.” | D + E; I for live pickup or ride state. |
| C029 · Parking bookmark | A place you explicitly save, optionally with a photo and note. | “That was level two, not three.” | D + N + P; optional location permission. |
| C030 · Last-mile plan | The final walking or transit segment from your arrival point. | “Less walking, even if it takes longer.” | I for routes; D for supplied instructions. |
| C031 · Accessibility route notes | Evidence about steps, lifts or entrances for a chosen journey. | “The lift is unavailable; revise it.” | I/D: official/user-reported status separated; no guarantee. |
| C032 · Commute change | Explain a material change between the plan and a new traffic/transit observation. | “Keep watching until I leave.” | I + P; current map launch is insufficient. |

### 9.5 Travel and bookings

| ID / Card | Personal, useful behavior | Signature interaction | Route |
|---|---|---|---|
| C033 · Trip timeline | Flights/trains, stays and activities from your imported itinerary. | “Move the museum, keep the train fixed.” | D + N; I for live inventory/status. |
| C034 · Flight shortlist | Compare actual requested constraints with sourced or clearly sandbox options. | “After nine, still nonstop.” | E for labeled sandbox; I for real availability. |
| C035 · Train journey | Imported station, service, date, coach/seat and departure details. | “That’s the return ticket.” | D; I for authorized live rail data. |
| C036 · Boarding companion | Relevant booking excerpt, terminal/gate data and journey milestones. | “The gate changed; update only that.” | D + N; I for verified live gate/status. |
| C037 · Stay comparison | Your chosen stays aligned by location, amenities, dates and evidence. | “No stairs and a private bathroom.” | D; I for current price/availability. |
| C038 · Packing planner | Quantities and categories based on duration, activities and explicit needs. | “Four days, with one formal event.” | E + N; P for personal reusable lists. |
| C039 · Travel money | Reference currency conversion and an editable trip budget. | “Use a larger food allowance.” | E + N; reference rates, not bank execution. |
| C040 · Disruption recovery | Options after a user-reported delay, with original commitments protected. | “Keep the hotel; change transport.” | D + N; I for rebooking and live availability. |

### 9.6 Food and kitchen

| ID / Card | Personal, useful behavior | Signature interaction | Route |
|---|---|---|---|
| C041 · Cook with what I have | Recipe suggestions from your supplied ingredients and equipment. | “No oven, and I’m missing tomatoes.” | D + E + N: structured recipe and constraints. |
| C042 · Live recipe steps | Current step, next step, ingredients needed now and related timers. | “Explain sauté, then continue.” | E + N: step state and side-question return. |
| C043 · Serving scaler | Scale supported ingredient quantities while preserving units and exceptions. | “Make it for five instead.” | E + N: deterministic arithmetic. |
| C044 · Grocery checklist | Grouped quantities from the chosen recipes, with what you already have removed. | “We have rice; leave it off.” | E + N; P for persistence, I for cart writes. |
| C045 · Menu decision | A shared menu compared against your budget and stated dietary preferences. | “One vegetarian option for the group.” | D + N: OCR review; never guarantee allergen absence. |
| C046 · Meal-week board | Your proposed meals, leftovers and prep tasks in a compact schedule. | “Wednesday needs to be a ten-minute meal.” | D + E + N; P for recurring planning. |
| C047 · Cooking timers | Separate labeled timers linked to steps, with actual Clock handoffs. | “Add two minutes to the pasta proposal.” | E + N; verify support before editing external timers. |
| C048 · Pantry expiry notes | User-entered package dates, quantities and suggested use order. | “That date is the packed-on date.” | D + N + P; no freshness assessment from photos. |

### 9.7 Money and shopping

| ID / Card | Personal, useful behavior | Signature interaction | Route |
|---|---|---|---|
| C049 · Bill split | Per-person shares, rounding and explicit participant adjustments. | “Split food equally, drinks separately.” | E + N: bounded arithmetic, new split inputs. |
| C050 · Expense receipt | Extracted amount, date and category from a deliberately shared receipt. | “That number is the tax, not the total.” | D + N; P for an expense ledger. |
| C051 · Budget remaining | Sum of entered expenses against your stated event/trip limit. | “Increase the limit by two hundred.” | E + N; no bank account inference. |
| C052 · Product comparison | Evidence-based attributes aligned with your actual selection criteria. | “Prioritize repairability over looks.” | D + N; I for current commerce information. |
| C053 · Price watch | A user-requested target price with source, checking interval and expiry. | “Only notify below this amount.” | I + P: permitted feed and actual monitoring. |
| C054 · Subscription review | Renewal dates and costs from details you supply, with possible duplicates flagged. | “That one is annual, not monthly.” | D + N + P; I for accounts/cancellation. |
| C055 · Return window | Receipt-linked return dates and policy excerpts for your purchase. | “Use the delivery date, not order date.” | D + N; I for verified current policy/status. |
| C056 · Wish-list tradeoff | Your selected purchases compared against a savings target and priorities. | “Keep the headphones, postpone the rest.” | D + N + P; planning, not financial advice or purchases. |

### 9.8 Work and administration

| ID / Card | Personal, useful behavior | Signature interaction | Route |
|---|---|---|---|
| C057 · Meeting preparation | Agenda, supplied background, decisions needed and your speaking notes. | “Focus on the budget discussion.” | D + E; I for account documents. |
| C058 · Action items | Owner, deadline and status extracted from an explicit meeting session. | “Monday, not Friday; keep the owner.” | D + N; I/P for shared task systems. |
| C059 · Follow-up draft | A concise draft grounded in decisions you supplied. | “Less formal, same commitments.” | E + D; phone compose handoff, no implied send. |
| C060 · Calendar draft | Editable event fields with time-zone resolution and conflicts if known. | “Move it thirty minutes later.” | E; I for reading/saving a real account calendar. |
| C061 · Project next steps | A small plan with dependencies, owners and the next unblockable task. | “The API isn’t ready; reorder the work.” | D + N; P for ongoing/shared state. |
| C062 · Approval request | Exact proposal, material details and the decision being requested. | “Approve the draft wording, not submission.” | N: explicit intent and action boundaries. |
| C063 · Support ticket | Symptoms, device identity, attempted steps and evidence attachments. | “That fix failed; keep it in the history.” | E for sandbox; I for an actual support system. |
| C064 · Deadline rescue | Remaining work sorted against your available time and non-negotiable deliverables. | “We lost a day; what can move?” | D + N: user-supplied estimates, no false forecasts. |

### 9.9 Learning and research

| ID / Card | Personal, useful behavior | Signature interaction | Route |
|---|---|---|---|
| C065 · Concept explanation | A concise concept, chosen depth and a relevant example. | “Use a different example, keep the definition.” | D + E; evidence needed for factual claims. |
| C066 · Practice question | One question at a time, hints, attempts and the current learning objective. | “Give a hint, not the answer.” | D + N: session learning state. |
| C067 · Worked calculation | Expression, checked result and a step explanation tied to exact values. | “Use centimetres instead.” | E + N: bounded calculator and unit conversion. |
| C068 · Revision plan | Topics and time blocks based on an explicitly supplied exam date/syllabus. | “I only have two evenings.” | D + N; P for long-term progress. |
| C069 · Paper shortlist | Real publication metadata with dates, DOI links and relevance notes. | “Only papers after this year.” | E: Crossref metadata; new filtering when supported. |
| C070 · Claim evidence | A claim beside the actual supporting or conflicting excerpt. | “Show the source behind that sentence.” | D + N; I for permitted full-text retrieval. |
| C071 · Source comparison | Compare dates, methods and scope from actually read source material. | “Exclude the opinion piece.” | E + D; snippets must stay labeled as snippets. |
| C072 · Flashcard stack | Cards from material you supplied, with correction and optional practice history. | “That answer is too vague; revise it.” | D + N; P for spaced repetition. |

### 9.10 Books, media and entertainment

| ID / Card | Personal, useful behavior | Signature interaction | Route |
|---|---|---|---|
| C073 · Book shortlist | Real titles/editions matched to your topic, level and preferred length. | “More practical, less theoretical.” | E: Open Library metadata; no unverified reading claims. |
| C074 · Reading companion | Notes, selected passages, questions and a current reading bookmark. | “Explain this paragraph without spoilers.” | D + N + P; use supplied/permitted text. |
| C075 · Movie night | Compare user-selected films by duration, genre and stated preferences. | “Under ninety minutes.” | D; I for metadata and current availability. |
| C076 · Where to watch | Region-specific streaming availability with a checked date. | “Use India, not the US.” | I: permitted availability provider; no universal feed assumed. |
| C077 · Music queue | Your proposed tracks grouped by context, with ordering and duration. | “Keep the first three, calmer after that.” | D + N; I for real playback/account actions. |
| C078 · Podcast chapter | A supplied transcript/excerpt with topics, notes and playback references if available. | “Go back to that explanation.” | D; I for licensed transcript/playback access. |
| C079 · Event night | Your chosen event, travel plan and preparation notes in one surface. | “We’re going tomorrow’s show instead.” | D + N; I for tickets/current event data. |
| C080 · Spoiler boundary | A user-set progress point that controls displayed summaries and sports/media detail. | “No results until I finish watching.” | N + P; enforce across all relevant card text and alerts. |

### 9.11 Sports and fandom

| ID / Card | Personal, useful behavior | Signature interaction | Route |
|---|---|---|---|
| C081 · Player form | Existing sport-specific recent records, with a chosen player and time/filter scope. | “Only T20 bowling innings.” | E: existing adapters; preserve innings/match distinctions. |
| C082 · Team match room | Recent games, scores and source links for your selected team. | “Compare away games.” | E + N; add only filters the feed can support. |
| C083 · Next fixture | Upcoming schedule in your selected time zone, with source date. | “Show local time where I’ll be traveling.” | I: upcoming-fixture support beyond recent completed logs. |
| C084 · Live game companion | Current match state and meaningful updates during a user-started watch session. | “Only interrupt for a major event.” | I + P: reliable live feed; current logs are not live scores. |
| C085 · Two-player comparison | Comparable dated metrics from compatible competitions and sample sizes. | “Same format and same number of innings.” | E + N; disclose incomplete coverage. |
| C086 · F1 weekend | Practice/qualifying/race schedule, driver results and chosen time zone. | “Only race results, exclude sprints.” | E for supported race history; I for extra sessions/live timing. |
| C087 · Fan briefing | A brief focused on teams/players you explicitly selected. | “Less transfer news, more actual match analysis.” | E + D; I for additional licensed data; P for saved interests. |
| C088 · Watch-together plan | Match time, participants, food, budget and reminders in a shared plan. | “Two more people are coming.” | D + N; I/P for shared coordination and verified schedules. |

### 9.12 Wellness and personal routines

These are planning and self-tracking ideas, not diagnostic products. Health-related data requires explicit access and careful interpretation.

| ID / Card | Personal, useful behavior | Signature interaction | Route |
|---|---|---|---|
| C089 · Walk plan | User-chosen distance/duration with time, route and weather context. | “Only twenty minutes today.” | D + N; I for routes or health records. |
| C090 · Activity summary | Authorized steps/activity records compared with your own chosen goal. | “Show the week, not today.” | I: Health Connect or approved Samsung path. |
| C091 · Workout session | Your selected routine, sets, rest timers and progress. | “Skip this exercise and keep the rest.” | D + N; no medical suitability claim. |
| C092 · Wind-down routine | A sequence you choose, with local timers and optional quiet reminders. | “Start later tonight.” | E + N + P; device settings only where supported. |
| C093 · Hydration log | User-entered intake and a self-selected reminder routine. | “That was two hundred millilitres.” | N + P; avoid invented medical targets. |
| C094 · Appointment preparation | Questions, symptoms you entered, documents and appointment details. | “Add this question for the clinician.” | D + N; do not diagnose or change treatment. |
| C095 · Medication reminder list | A user-entered schedule copied from their existing instructions, with confirmation of entries. | “Change the reminder time, not the dose.” | D + N + P; high-reliability reminders need careful validation. |
| C096 · Personal check-in | A private self-reported note and optional next action chosen by the user. | “Just save my words, no interpretation.” | D + P; no inferred mood/health profile from voice. |

### 9.13 Home and device support

| ID / Card | Personal, useful behavior | Signature interaction | Route |
|---|---|---|---|
| C097 · Device identity | Shared model label, image region and verified manual reference. | “It’s the A16 variant.” | E + N; real manual import/search beyond fictional R1. |
| C098 · Guided troubleshooting | Current step, attempted steps, observed result and supporting instruction. | “I already tried that.” | E + N; I/D for a relevant authentic manual. |
| C099 · Settings route | A supported settings panel with the actual next action explained. | “Open display instead.” | E: public settings intents, not silent protected toggles. |
| C100 · Maintenance log | User-entered service dates, consumable changes and supporting receipts. | “That was a filter clean, not replacement.” | D + N + P. |
| C101 · Appliance timer | A named household task with an actual timer handoff or verified device status. | “Remind me in fifteen minutes.” | E for Clock; I for appliance telemetry. |
| C102 · Home device control | Authorized device state and a bounded supported command. | “Only the living-room light.” | I: SmartThings; hardware/account access required, later. |
| C103 · Home energy | Meter/appliance readings with dates and a user-chosen comparison interval. | “Compare weekdays only.” | I: available authorized energy data, not an assumed SDK field. |
| C104 · Home inventory | Explicitly saved item locations, manuals, warranty notes and photos. | “Move the spare keys to the drawer note.” | D + N + P; no automatic visual certainty. |

### 9.14 Phone actions

| ID / Card | Personal, useful behavior | Signature interaction | Route |
|---|---|---|---|
| C105 · Alarm proposal | Exact time, repeat days, label and actual Clock handoff status. | “Weekdays only, and 6:45.” | E; verify receiving-app behavior and avoid duplicate handoffs. |
| C106 · Timer control | Duration, label, real action status and a visible local representation. | “Wait before starting it.” | E + N; do not assume universal external timer edit APIs. |
| C107 · App chooser | Actual installed candidates, clearly differentiated by app name. | “The work version.” | E: local app resolution; no access to private app data. |
| C108 · Call preparation | Supplied number and reason, with an honest dialer action. | “Wrong number; use this one.” | E; contacts lookup is a separate permissioned integration. |
| C109 · Message draft | Recipient, body and tone, with review before native send. | “Keep the facts; make it warmer.” | E + D; compose is not delivery. |
| C110 · Email draft | Subject, recipient and body grounded in current task context. | “Send the agenda as text—prepare it first.” | E + D; attachment/account sending needs integration. |
| C111 · Phone quick control | Supported media volume/torch control with actual feedback. | “Half as loud.” | E; media volume is not alarm or ringer volume. |
| C112 · Widget builder | Preview one/two existing result sources with honest update behavior. | “Keep the clocks, replace the other panel.” | E + N: source selection and stable card references. |

### 9.15 People and communication

| ID / Card | Personal, useful behavior | Signature interaction | Route |
|---|---|---|---|
| C113 · Reply options | Several drafts grounded in a message the user deliberately shared. | “More direct, still polite.” | D + E; no automatic private inbox access. |
| C114 · Commitment tracker | Promises explicitly made in a supplied conversation, with uncertainties shown. | “That was only a suggestion.” | D + N + P; no silent interpersonal monitoring. |
| C115 · Find a time | Overlap among time windows participants actually supplied. | “One person is in London.” | E + N; I for authorized calendar availability. |
| C116 · Group outing | Participant requirements, shared plan, split and unanswered choices. | “One person will join after dinner.” | D + N; I/P for real collaboration. |
| C117 · Important-date note | A date the user chooses to save, optional preparation checklist and reminder. | “Only remind me a week before.” | D + N + P. |
| C118 · Gift shortlist | Options based on recipient facts explicitly supplied for this task. | “Avoid gadgets; they already have one.” | D + N; I for current products/prices. |
| C119 · Handoff summary | Selected task context packaged for a human who will continue it. | “Include the attempts, omit my private notes.” | D + N; user-reviewed sharing. |
| C120 · Conversation interpreter | A deliberate bilingual session with captions and editable translations. | “Translate that literally, not casually.” | D + I: actual language capability/latency validation. |

### 9.16 Visual capture and understanding

| ID / Card | Personal, useful behavior | Signature interaction | Route |
|---|---|---|---|
| C121 · Ask about a region | A tapped image area and grounded follow-up with visible coordinates. | “The label below it.” | E + N: image IDs, regions and clarification. |
| C122 · Screenshot-to-plan | Extract relevant dates, places and actions from a shared screenshot. | “Use the updated time I just said.” | E + D + N. |
| C123 · Document fields | Structured fields from an imported form, ticket or page, with source anchors. | “That is the reference number.” | D + N; PDF import/OCR is additional work. |
| C124 · Label reader | Large readable text, pronunciation and user-controlled explanation. | “Read only the ingredients.” | E + I for reliable OCR; preserve uncertainty. |
| C125 · Visual comparison | Two deliberately supplied images, with observable differences highlighted. | “Compare the ports, not the color.” | D + N: multiple attachment identity. |
| C126 · Assembly step | A current manual step beside the user’s image and a progress state. | “Mine has a different connector.” | D + N; bounded nonhazardous guidance. |
| C127 · Object location note | User-approved description of where an item was placed in a supplied photo. | “Actually the lower shelf.” | D + N + P; not continuous tracking. |
| C128 · Camera change log | A short user-started sequence of frames tied to one task and explicit timestamps. | “Use the frame before I moved it.” | N + I: capture session and retention policy; later. |

### 9.17 Personal memory and life administration

| ID / Card | Personal, useful behavior | Signature interaction | Route |
|---|---|---|---|
| C129 · Remember this note | Exact note preview and explicit saved state. | “Save the corrected version.” | E; extend editing without accidental duplicate notes. |
| C130 · Preference receipt | The fact you chose to remember, its source, scope and expiry. | “Only for trips.” | N + P; evaluation uses session-only variant. |
| C131 · Why this is personal | Visible preferences and evidence used by the current card. | “Stop using that preference.” | N; P only when persistence is enabled. |
| C132 · Forgotten thread | A saved unfinished plan with its next unresolved decision. | “Resume the packing plan.” | E + N + P; saved display history alone is insufficient. |
| C133 · Warranty and service | Purchase date, serial details supplied by the user, policy source and service history. | “That warranty applies to the other device.” | D + N + P; no invented coverage. |
| C134 · Document deadline | Expiry/due dates copied from a deliberately supplied document. | “This is the issue date, not expiry.” | D + N + P; verify extraction and reminder delivery. |
| C135 · Borrowed and lent | User-entered items, people and expected return dates. | “They returned the book, not the charger.” | N + P; no contacts access assumed. |
| C136 · Personal export | A user-selected subset of preferences and artifacts for export or deletion. | “Export plans but leave private notes out.” | E + N + P; redact and preview deliberately. |

### 9.18 Accessibility and language

| ID / Card | Personal, useful behavior | Signature interaction | Route |
|---|---|---|---|
| C137 · Patient conversation | Floor-holding preference and visible unfinished-turn state. | “Let me finish before responding.” | E + N: bounded speech timing policy. |
| C138 · Large-print answer | Adjustable reading size, contrast and a clear selected section for speech. | “Read just this section.” | N: native accessibility and selection. |
| C139 · Live captions | Readable captions linked to the current answer/task, with correction visibility. | “Show the last thing I said.” | E + N; caption accuracy still needs human testing. |
| C140 · Pronunciation clarification | Candidate spellings for names/terms the model heard uncertainly. | “I’ll spell it.” | N + D; no invented transcript confidence score. |
| C141 · Code-switch control | A chosen mix of spoken/display language and stable native names/numbers. | “Hindi explanation, English technical terms.” | E + N; verify model/language behavior. |
| C142 · Step-by-step mode | One action at a time with an explicit continue/skip/repeat interaction. | “Repeat this step, slower.” | E + N; preserve current task and evidence. |
| C143 · Quiet interaction | Touch/text input with visual responses and optional speech control. | “Show me, don’t read it aloud.” | E + N; ensure no accidental microphone activation. |
| C144 · Companion instructions | A user-approved handoff card for someone helping with a task. | “Share only the setup steps.” | D + N; user-controlled sharing, no silent caregiver alerts. |

### 9.19 Creativity and hobbies

| ID / Card | Personal, useful behavior | Signature interaction | Route |
|---|---|---|---|
| C145 · Creative brief | Audience, constraints, tone and deliverables for something the user is making. | “Same idea, different audience.” | D + E + N. |
| C146 · Script rehearsal | Selected script sections, timing estimates and deliberate practice notes. | “Skip the introduction; rehearse this part.” | D + N; real timing measured during rehearsal. |
| C147 · Shot list | A filming plan with scenes, needed props and user-set time limits. | “We only have this room.” | D + E + N; no location inference. |
| C148 · Music practice | User-chosen exercises, repetitions, tempos and a practice timer. | “Slower, keep the same exercise.” | D + N; instrument grading needs separate validated audio work. |
| C149 · Hobby material list | Quantities, available tools and ordered steps for a selected project. | “Use the materials I already have.” | D + E + N. |
| C150 · Game-night plan | User-entered rules, participant scores, rounds and timing. | “Undo that score, not the whole round.” | N: small deterministic game templates. |
| C151 · Language practice | A selected scenario, correction style and current conversational objective. | “Let me finish, then correct me.” | D + N; verify language quality. |
| C152 · Idea branches | Two creative alternatives with retained constraints and selective adoption. | “Use that ending with this opening.” | D + N: section identities and branch merging. |

### 9.20 Community and specialized everyday tasks

| ID / Card | Personal, useful behavior | Signature interaction | Route |
|---|---|---|---|
| C153 · Local service shortlist | Options for a task/location with hours, distance and real sources. | “Only places open after work.” | I: places/service provider; D for user-supplied options. |
| C154 · Community event plan | A supplied event notice turned into attendance, travel and preparation cards. | “I’m volunteering, not attending.” | D + N; I for live event registration. |
| C155 · Appointment queue | Your actual appointment or ticket state with a source and update age. | “Only alert when I need to leave.” | I + P; no invented queue position. |
| C156 · Delivery tracker | An authorized carrier/order status, relevant instructions and last check. | “Use the office address in my note.” | I + P; changing a note does not reroute a shipment. |
| C157 · Pet routine | User-entered feeding, walking and appointment routines with checklists. | “Only this evening’s walk changes.” | D + N + P; no veterinary diagnosis. |
| C158 · Garden care notes | User-described plants, tasks, photos and weather-informed planning. | “That plant is indoors.” | D + E + N + P; no certainty from an unclear image. |
| C159 · Preparedness checklist | A user-chosen household/travel checklist with sourced instructions where needed. | “Adapt it for this trip.” | D + N; not emergency detection, dispatch or navigation. |
| C160 · My small calculator | A described calculator made from reviewed templates and editable inputs. | “Add tolls and split among five.” | E + N: closed schemas and deterministic math. |

### 9.21 The strongest personal combinations

The best experiences connect several cards around one goal:

| Experience | Connected cards | The correction that makes it memorable |
|---|---|---|
| Outing that survives changes | C001 + C005 + C016 + C025 + C049 | “Four of us now, and we’re walking.” |
| Dinner without starting over | C041 + C042 + C043 + C044 + C047 | “No oven, no tomatoes, still twenty-five minutes.” |
| Troubleshooting that follows your finger | C097 + C098 + C121 + C006 | “Not that indicator; the lower one.” |
| Trip that stays coherent | C033 + C038 + C039 + C011 | “One extra day, same budget.” |
| A less exhausting meeting | C057 + C058 + C059 + C004 | “The owner stays; move only the deadline.” |
| A match night with real life attached | C083 + C088 + C044 + C049 | “Two friends are joining after kickoff.” |
| Reading that remembers your place | C074 + C065 + C004 + C080 | “Explain that term, then go back without spoilers.” |
| A respectful personal assistant | C130 + C131 + C007 + C008 | “Use that preference only for this task.” |

Do not present imported, drafted, local, live, and externally executed parts as if they all had the same data guarantees. Put the distinction where it matters to the decision.

## 10. Data and Samsung integration paths

### 10.1 Build from the access we actually have

| Need | First practical path | Additional requirements / honest limit |
|---|---|---|
| Calculations, quantities, dates, clocks | Existing local executors. | Add specific typed calculations; do not execute arbitrary model code. |
| Plans, recipes, checklists, comparisons | Existing structured document tool plus user inputs. | These begin as drafts. Connect actual source records when claims need grounding. |
| Weather windows | Extend the existing Open-Meteo adapter with appropriate hourly fields. | Source availability, geography, terms and model resolution limit precision. [Weather API documentation](https://open-meteo.com/en/docs). |
| Air quality | Separate AQ request and a new sourced card. | This is additional data, not already returned by the weather tool. [Open-Meteo AQ documentation](https://open-meteo.com/en/docs/air-quality-api). |
| Route durations | Route API after credential/terms verification; user-entered duration for the first prototype. | Map opening is not route computation. [Google Routes overview](https://developers.google.com/maps/documentation/routes/compute-route-over). |
| Places and opening hours | A verified place provider, with exact location identity. | Required fields, billing, attribution, freshness and regional coverage need checking before implementation. [Places API overview](https://developers.google.com/maps/documentation/places/web-service/overview). |
| Currency | Existing dated reference-rate adapter. | Do not present indicative conversion as a bank quote, trading price or payment. |
| Books and papers | Existing Open Library/Crossref discovery. | Metadata is not full-text access. Crossref documents retrieval of scholarly metadata. [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/). |
| General search/news | Existing attributed source discovery. | Excerpts stay excerpts. Build full-page retrieval only for permitted, relevant sources. |
| Sports | Existing adapters for demonstrated record types. | Unofficial feeds/HTML can change. Live scores, fixtures and licensed redistribution require separate validation. |
| Menu/receipt/manual text | Shared image plus reviewed OCR/extraction. | ML Kit offers Android text-recognition integration; choose the scripts/model packaging actually needed. [ML Kit text recognition](https://developers.google.com/ml-kit/vision/text-recognition/v2/android). |
| Alarms, maps, dialer, email/SMS/event drafts | Current Android intents and bounded phone bridge. | Receiving-app behavior matters. A handoff does not prove the user finished the external action. [Android common intents](https://developer.android.com/guide/components/intents-common). |
| Personal calendar/email/contact data | Deliberate share/import first. | Account/API or Android permission work is new; request only the data needed for a chosen feature. |
| Flights, hotels, trains, delivery and live queues | Import existing user details first. | Real availability, booking or tracking needs an actual authorized provider. There is no generic “search” API that proves all of these. |
| Local personal memory | Reuse SQLite for explicit small records. | Add scope/expiry/deletion and a separate evaluation mode. |
| Persistent monitors | Scheduled checks or event subscriptions, keyed by monitor ID. | Require deduplication, expiry, app lifecycle handling, actual notifications and budget control. |

This is an integration shortlist, not a commitment to a new paid vendor. No paid account, purchase or subscription was created during this audit.

### 10.2 Samsung-specific without imaginary privileges

| Opportunity | Feasibility on the available S24 | Recommendation |
|---|---|---|
| Native Compose cards, haptics, microphone and share entry | Already largely present. | Build the hero experiences here. |
| Camera-region questions and deliberate image sharing | Present still-image input; region targeting is new. | High-value phone-only multimodal demonstration. |
| Clock/map/settings handoff | Already implemented through public Android surfaces. | Include one true handoff with accurate status. |
| Home-screen widgets | Already implemented, including native previews/pinning. | Use for a compact persistent view; do not make widget generation the originality claim. |
| Android Live Updates | Platform support has eligibility and OEM criteria. | Optional spike only for an ongoing user-started task; do not promise a Samsung Now Bar integration. |
| AppFunctions | Android 16+ API exists, but full agent integration is gated and requires caller permission. | Future compatibility path, not a way to give this APK unrestricted app control. |
| SmartThings | Requires an authorized account and supported devices/capabilities. No such hardware is available for this team. | Post-submission roadmap; no need to buy equipment for the main demo. |
| Samsung Health / Health Connect | Requires user-granted access and actually available records. | Optional future wellness surface; do not make it a dependency. |
| Galaxy Watch / Buds / Ring | No hardware available; no arbitrary gesture/data access should be assumed. | Future client surfaces after the phone experience works. |
| Samsung DeX / large screen | A layout opportunity when a compatible display/setup is available. | Reuse responsive cards; do not spend submission time obtaining another display. |

Android’s Live Update documentation describes ongoing, user-initiated, time-sensitive activities, requires supported notification styles, and allows OEM-specific restrictions. Arbitrary custom RemoteViews cards do not become promoted Live Updates. Use a regular notification/widget where appropriate. [Live Update documentation](https://developer.android.com/develop/ui/views/notifications/live-update).

AppFunctions remains an experimental integration with limited full-pipeline access. Preparing functions in an app and receiving privileged cross-app execution access are different things. [AppFunctions overview and access FAQ](https://developer.android.com/ai/appfunctions).

SmartThings uses scoped authorization. Its documentation states that newly created personal access tokens last twenty-four hours and recommends service integrations for ongoing access. A demonstration must not depend on a token that silently expires on presentation day. [SmartThings authorization](https://developer.smartthings.com/docs/getting-started/authorization-and-permissions).

Samsung Health Data SDK production access requires partner registration; developer-mode access is for development/testing. Health Connect uses per-data-type permissions and feature availability checks. Neither route implies this team already has health records or access to every Samsung-specific metric. [Samsung Health app verification](https://developer.samsung.com/health/data/guide/app-verification.html), [Health Connect setup](https://developer.android.com/health-and-fitness/health-connect/get-started).

### 10.3 Screen understanding is not silent screen access

The current app has deliberate share/camera inputs. That is sufficient for the initial visual workflow.

If live screen sharing is later added, implement the normal MediaProjection consent/lifecycle flow. Android requires consent for each capture session for apps targeting Android 14+. Do not reuse a capture token to evade that boundary. [Android screen-capture behavior](https://developer.android.com/about/versions/14/behavior-changes-14).

Treat third-party accessibility automation as a separate engineering/product decision. The brochure assigns teachable third-party automation to Theme 3; implementing it now would consume time without automatically improving Theme 5 correctness.

### 10.4 Budget and latency discipline

Do not add another model just to rewrite every tool result. Deterministic arithmetic, filtering, differences and scheduling should be local. Reuse the existing Live connection and the existing asynchronous backend feedback pattern where supported.

For each cloud session, measure:

- Audio input/output duration or tokens according to the provider’s actual billing units.
- Text/context tokens and number of model calls.
- External lookup counts and duplicated/stale requests.
- Bytes sent for images and frequency of image updates.
- Cost of successful completion, not just cost of one response.

Estimate cost using the selected provider’s verified current rates and measured usage. The supplied brief gives no team budget, so this document does not invent one. Set an agreed daily cap and provider quota before sustained live testing. Keep development traces separate from billing estimates.

## 11. Implementation plan against this codebase

### 11.1 Preserve the current architecture

Keep the Kotlin app, Python controller, browser client, SQLite notebook and existing providers. No new foundation-model training, microservice fleet, vector store, generic workflow engine, or universal app-builder is necessary for the recommended prototype.

The useful conceptual flow is:

~~~text
Voice / text / deliberate image / selected card item
                         |
            speech activity + intent proposal
                         |
           validated patch to current task state
                         |
      affected reads/actions identified and reconciled
                         |
       structured results + evidence + actual outcomes
                         |
          stable cards + short grounded voice reply
~~~

The controller remains authoritative. The model proposes changes; the executor and returned evidence determine what happened.

### 11.2 Work in this order

**Step A: close correctness and submission gaps.**

Integrate the official stream contract when provided. Put time and sleep behind the smallest replaceable clock interface needed by that runner. Ensure fresh sessions cannot read prior notes/preferences. Isolate app-specific providers from evaluator-supplied manifests.

Before building more phone actions, test the delayed PhoneBridge outcome path under new provider messages. Keep reading provider events while independent action work is pending. Preserve one well-defined outcome per call ID and do not introduce concurrent writes merely to make the UI feel faster.

**Step B: add identity and local edits.**

Add stable task/card/item IDs and an explicit revision contract. A fetched result batch can still get its own ID, but it should update the correct logical card. Preserve progress and selection by item identity.

Support a small set of operations: set field, remove explicitly requested field, select item, update quantity, mark complete, and cancel/hold. Validate them with the same rigor as tool calls.

**Step C: add one linked plan.**

Start with a small structure for time, people, cost and checklist dependencies. Recompute affected local values. Mark source-dependent values stale and refresh only when their inputs change.

Do not build a generalized arbitrary dependency language. Three linked components can demonstrate the principle.

**Step D: add frame references and personal context.**

Attach selected region and frame ID to visual requests. Add explicit session preferences and a visible rationale. Keep them out of persistent storage unless the consumer mode intentionally supports it.

**Step E: finish eight native card families.**

Build the common behaviors once: loading/stale states, input chips, selection, short differences, source details and actions. Keep widgets simpler than the main app.

**Step F: benchmark and package.**

Run regression tests, a held-out team scenario set, human microphone trials, minified release checks, and an actual clean setup from the final package.

### 11.3 Concrete change map

| Existing location | Recommended change |
|---|---|
| Session controller | Task/card identity, scoped patch history, small plan dependencies, resumable side-question state and evaluation isolation. |
| Protocol schema | Explicit task/item/revision references and minimal new action schemas; adapt to the organizer’s actual contract. |
| Live relay | Non-blocking provider ingestion, current selected-card context, concise computed deltas, supported reconnection handling. |
| Capability executors | A few deterministic plan/split helpers and hourly weather fields. Keep source records attached. |
| Phone bridge / native actions | Clear pending/unknown outcomes; revision-aware material details; no blanket retries on uncertain writes. |
| Android state model | Merge revisions into stable cards; preserve checklist progress; avoid opening every small update as a new screen. |
| Android UI | Eight renderer families, input chips, a clarification view, change annotations and an evidence drawer. |
| Android widgets | Project approved card state into RemoteViews; preserve user interaction and stale-data indicators. |
| Browser renderer | Match the same payload/identity semantics while retaining its existing useful document views. |
| Test and verification scripts | Specific race/fault cases, official adapter checks, clear test-layer labeling and sanitized exportable evidence. |
| Build/release documents | Docker setup, Linux/headless runner, exact model/assets, lockfiles, disclosure and required tag. |

Make changes in existing modules first. Extract a helper only when a real repeated responsibility becomes difficult to maintain; do not pre-create twenty domain modules for the card catalog.

### 11.4 Invariants worth writing down

1. A card can show stale data but must not label it current.
2. A correction invalidates only work whose declared inputs changed.
3. A superseded read cannot become the current answer.
4. A new revision never erases the receipt of an already submitted action.
5. A voice correction cannot create a duplicate external write through reconnect/retry.
6. Acknowledgment, wording approval and action authorization remain distinct.
7. The user’s manually checked items survive unrelated model updates.
8. A visual reference identifies its frame, not just “the latest image.”
9. A change in response style does not change the task.
10. “Stop speaking,” “hold work,” “cancel task,” and “end session” remain separate operations.
11. Evaluation scenarios begin with clean state and do not read consumer persistence.
12. Unknown status is an honest state with a reconciliation path.

### 11.5 Source-to-speech consistency

The README already records a historical case where the screen’s correct conversion and the spoken unit disagreed. Rich cards are not enough if the voice contradicts them.

Use a compact authoritative speech summary from tool results: value, unit, applicable date/time, source and status. Validate numbers and units in the output transcript where available. For the showcase, inspect the actual recorded speech as well.

A correct controller does not prove the language model will always describe it correctly. Keep this as a measured quality target.

## 12. Four-person build plan

This is a suggested allocation for the confirmed four-person team, not an assumption about anyone’s specialties. The plan assumes work starts on 14 September and aims to freeze by 23 September, leaving a submission buffer. Recheck any changed organizer dates.

### 12.1 Four work lanes

| Lane | Ownership | Must deliver |
|---|---|---|
| Builder 1 · Core/evaluation | Controller, protocol, official adapter, task patches and state isolation. | Correct end states and cancellation/reconciliation evidence. |
| Builder 2 · Voice/device | Live relay, audio behavior, phone bridge and release-device testing. | Responsive interruption, honest action outcomes and reconnect behavior. |
| Builder 3 · Cards/interaction | Stable native card rendering, voice/touch references, progress preservation. | Eight coherent card families and usable visual corrections. |
| Builder 4 · Data/evidence/delivery | Chosen data extension, manual/visual sources, held-out checks, reproducibility and presentation. | Sourced hero inputs, benchmark records, clean package and short demo. |

Integration is everyone’s responsibility. Define the shared card/patch payload before parallel implementation. Pair on the changes that cross controller, voice and UI.

### 12.2 Calendar plan

| Date | Deliverable | Stop condition / decision |
|---|---|---|
| **14 Sep** | Confirm registration, choose hero journey, agree schemas and split work. | Freeze scope to the recommended core; keep catalog as backlog. |
| **15 Sep** | Stable task/card IDs, baseline latency trace, candidate release setup. | No new optional integrations until identity semantics work. |
| **16 Sep** | Registration deadline in supplied brochure; first complete text-driven hero flow. | Verify team registration externally; investigate official kit availability without assuming release. |
| **17 Sep** | Live correction and side-question flow; three connected native cards. | Demonstrate a changed field without resetting progress. |
| **18 Sep** | Frame-region correction and evidence; delayed-action interruption case. | Show a late obsolete result excluded and a truthful receipt. |
| **19 Sep** | Finish the eight card families and one useful data extension. | Do not start a second new provider if the first remains unreliable. |
| **20 Sep** | Four-person integration run, first held-out scenarios and release APK check. | Fix defects in hero behavior before adding polish. |
| **21 Sep** | Official adapter work as kit allows; unseen-manifest and isolation checks. | If external model/network rules remain unclear, preserve an explicit fallback/evaluation risk. |
| **22 Sep** | Human microphone/noise testing and source-to-speech review. | Choose the demonstrably reliable language/device conditions. |
| **23 Sep** | Feature freeze; reproducible setup, results table, first full video cut. | No new feature families. |
| **24 Sep** | Correct defects, finalize deck/disclosure, verify tagged package and links. | Rehearse a clean setup and inspect every claimed result. |
| **25 Sep** | Submit with a substantial buffer before the listed deadline. | Recheck form/time zone and keep proof of submission. |

This is a demanding eleven-day build window, not enough time to harden every consumer feature.

### 12.3 Minimum, strong, and stretch versions

| Version | What to ship |
|---|---|
| **Minimum credible** | Official adapter as available, correct interruption/reconciliation, stable cards, one text/voice scenario, one frame scenario, reproducible package. |
| **Strong recommended** | Minimum + Live Plan Repair, Side-question Return, Non-negotiables, Change Receipt, eight card families, real phone handoff, measured release behavior. |
| **Stretch** | One branch comparison, one in-session attention contract, or one user-described calculator. Choose only one after the strong version passes. |
| **After submission** | Consumer memory, durable monitors, account integrations, shared plans, health/home surfaces and broad card expansion. |

### 12.4 A practical feature-selection score

For choosing among optional features, assign team estimates from 1–5:

**Priority = (theme fit + user usefulness + demonstration clarity + reuse) ÷ (engineering effort + access risk).**

This is a decision aid, not a measured business or contest score. A feature with spectacular visuals but uncertain access should lose to a smaller feature that clearly demonstrates recovery.

Do not score every one of the 160 cards. Score the five optional features the team is actually considering.

## 13. The five-minute demonstration

### 13.1 Positioning

Use this idea for the pitch:

> “People change their minds while assistants are already working. THREAD keeps the useful context, changes the affected work, and shows what actually happened.”

Explain that Gemini supplies native speech and language understanding. THREAD supplies the state coordination, typed tools, interruption recovery, grounded workspace and device integration. Owning that distinction makes the technical contribution more credible.

### 13.2 Suggested video, with buffer

| Time | What the viewer sees | What it proves |
|---|---|---|
| **0:00–0:20** | A concrete everyday problem and a short promise. Show the actual phone. | Clear user need and real product surface. |
| **0:20–1:20** | Build a small personal plan. Interrupt: change people and time; retain budget. The same cards update. | Local corrections, dependency handling, visual continuity. |
| **1:20–1:50** | Ask a side calculation, correct it, then return to the plan. | Task continuity and correct reference handling. |
| **1:50–2:40** | Share a device image. Select one indicator, then correct the target while a manual lookup is pending. | Multimodal grounding and stale-result exclusion. |
| **2:40–3:35** | A clearly labeled sandbox action is interrupted at a consequential boundary. Show late-result/unknown-status handling. | No duplicate write, no fabricated cancellation. |
| **3:35–4:00** | One real supported phone handoff, such as an event draft, with its true status. | Actual native integration and outcome honesty. |
| **4:00–4:35** | Show concise evidence: trace, final slots, excluded result and measured performance with test conditions. | Technical depth and reproducibility. |
| **4:35–4:45** | One sentence about integration potential and current limits. | Mature scope and clear contribution. |
| **4:45–5:00** | Buffer for pacing, titles or necessary clarification. | Stay within the maximum. |

If three scenarios make the video rushed, shorten the personal plan and devote more time to one interruption chain. A coherent demonstration is more memorable than twenty unrelated commands.

### 13.3 Example adversarial dialogue

The exact values and options here are demo inputs, not actual availability:

1. “Plan an outing for two tomorrow. We need to be home by ten and stay under twelve hundred.”
2. During planning: “Actually four, but keep the budget.”
3. “What’s that per person?”
4. During the explanation: “Wait, one person is only joining for dinner.”
5. “Go back to the plan. Keep the café time.”
6. “Compare leaving half an hour later without changing this one.”
7. “Use the original. Show only what changed.”

Do not force the system to pretend it knows how to allocate a dinner-only participant’s share. That ambiguity is an excellent short clarification moment.

For the sandbox action, prepare independent branches:

- Stop before submission: show no write submitted.
- Stop after submission: show cancellation requested and then the provider’s actual response.
- Reply lost: show outcome unknown, reconcile by operation ID, and do not resubmit blindly.

### 13.4 Present the evidence well

Use a small “What changed” strip on the consumer screen. Put internal operation IDs and detailed traces in a separate evidence view. The user should see useful state; the judge should be able to inspect the machinery.

One strong evidence display:

~~~text
Your correction
  people: 2 → 4
  budget: ₹1,200 retained
  home-by: 22:00 retained

Affected work
  cost split: recalculated
  checklist quantities: revised
  weather for unchanged location/date: retained

Action status
  no reservation submitted
~~~

This is a proposed display of actual controller events, not a canned success panel.

### 13.5 Demonstration failure plan

- If the network fails, identify the failure and show local/retained capabilities. A recording can be shown explicitly as recorded evidence, never presented as a live run.
- If a public feed fails, use a disclosed sandbox scenario or a previously saved source labeled with its age.
- If an interpretation is wrong, use the correction as a real test. Do not cut the video to make a failed action appear successful.
- Keep device battery and thermal conditions reasonable, test the minified APK, and restore USB forwarding before rehearsal.
- Use stationary demonstrations. A driving example does not require a person driving during the demo.

## 14. Measurements that make the claims credible

### 14.1 Separate four kinds of evidence

| Evidence layer | What it establishes | What it does not establish |
|---|---|---|
| Deterministic unit/controller tests | Valid state transitions, schema handling, calculations and defined race cases. | General language understanding or real acoustics. |
| Live model scenarios | Whether particular natural-language requests produced the expected state/actions. | Universal intent accuracy or all accents/environments. |
| Device tests | Native behavior on the tested device/build, with the stated inputs. | Behavior on all Android devices or background conditions. |
| Human use | Whether real people can finish the task and understand the result. | A broad population claim from a few testers. |

Keep these labels in the deck and README. The existing 497-test result belongs to the first layer.

### 14.2 A small held-out evaluation the team can afford

Create **twenty-four team-authored scenarios**: eight task-repair cases, six action-boundary cases, four visual-reference cases, four speech/hesitation cases, and two reconnect/isolation cases.

Have someone other than the feature author write the final phrasing for at least half. Freeze those prompts before the validation run. Separate development failures from a final fresh evaluation.

Run deterministic cases at three interruption points and two fault conditions if useful: that can produce **144 executions of 24 scenarios**, not 144 independent scenarios. Record the case identity and variation.

These are the team’s tests. They are not Samsung’s nine public or approximately sixty hidden scenarios.

### 14.3 Suggested product targets

Targets are **proposed engineering goals**, not measurements already achieved and not invented organizer thresholds.

| Metric | Initial target / reporting rule |
|---|---|
| Physical interruption to audible playback stop | Aim for p95 below 200 ms on the S24 in stated quiet conditions; publish measured results and noise conditions. |
| Valid structured input to controller state/cancel event | Aim for p95 below 50 ms excluding model/network interpretation; official harness thresholds take precedence. |
| Spoken turn end to first substantive response | Aim for p95 below 1.5 seconds in the chosen warm-network demo configuration; report separately from filler. |
| Local card update after accepted patch | Aim for p95 below 150 ms for deterministic edits; external fetch latency is separate. |
| Retained-constraint correctness | Every applicable unchanged hard constraint retained in the frozen test set. |
| Stale-result leakage | Zero obsolete results promoted to current answers in tested fault cases. |
| Duplicate state-changing operations | Zero duplicate submissions in tested retry/reconnect/cancellation cases. |
| Grounded spoken values | No mismatched value, unit, date or action status in the reviewed demo set. |
| Manual progress preservation | No lost checked state or selected identity after unrelated edits/refreshes. |
| Session isolation | Zero previous-scenario personal state in new evaluation sessions. |
| Task completion | Report passed/attempted cases and failure categories; do not hide clarification or provider failures. |
| User usefulness | Record completion without coaching, number of corrections, and whether the user would reuse the result. |

The configured 96 ms speech gate is not a measured 96 ms physical stop time. Audio capture, inference, buffering, scheduling and hardware all contribute.

### 14.4 Measure the right clocks

Record these separately:

1. Acoustic speech onset, if captured in a consented test recording.
2. Local detector speech-start event.
3. Provider transcription/intent arrival.
4. Controller revision/cancellation event.
5. Tool request and returned outcome.
6. Audio generation/receipt.
7. Scheduled playback and, where measured, physical audible playback.
8. Card update/render completion.

Phone monotonic time and server wall time are not automatically interchangeable. Correlate timestamps deliberately or compute each interval on a single clock. Clearly state when a metric excludes physical sound.

For acoustic validation using the available phone and laptop, record a deliberate test with a reference microphone where possible, obtain consent from participants, and label the spoken interruption/last audible old response. Do not use private background speech as a test corpus.

### 14.5 Cases likely to expose real defects

| Case | Expected behavior |
|---|---|
| Name correction before a slow lookup returns | Old entity result never replaces the corrected one. |
| Two tasks of the same domain | Distinct task/card identity; no accidental overwrite. |
| Checklist revised after user ticks two items | Preserve the matching items’ manual state. |
| New frame while old visual lookup is pending | Old coordinates/evidence cannot attach to the new frame. |
| Phone result delayed thirty seconds | Provider ingestion and user interruption remain responsive. |
| Speech says “don’t remove the time limit” | Constraint remains. |
| User says “yes, that date is right” | No unintended booking or save. |
| Background noise without actual words | Recover only permitted unheard speech; no action execution from recovery. |
| Short acknowledgment during output | Handle according to the active conversational policy; never treat it as new write authority. |
| Two different units in card and voice | Mark failure even if the card’s number is correct. |
| Service commits but reply is lost | Outcome remains unknown until reconciled; no blind retry. |
| Connection resumes with prepared action | Hold action; do not treat greeting/resumption as authorization. |
| Evaluation starts after consumer note use | No notebook/history/preferences leak into the scenario. |
| Public provider returns partial/malformed data | Show precise incompleteness without filling values from model memory. |
| Source text includes an instruction to act | Treat it as untrusted content, not a user command. |
| User changes only explanation depth | Work and factual values remain unchanged. |

### 14.6 Evidence for the submission

Include a compact results table with:

- Build/commit identifier and exact tested model/configuration.
- Test layer, case count, inputs and test conditions.
- Latency definitions, sample counts, p50 and p95.
- Completion, stale-result, duplicate-write and protocol outcomes.
- Known failures and limitations.
- A few sanitized traces that reproduce the strongest claims.

The existing ignore rule for JSON reports means those files will not automatically enter a future Git commit. Intentionally include the selected sanitized evidence in the final tagged package. Exclude API keys, personal recordings and unrelated private content.

### 14.7 AI disclosure

The supplied disclosure form asks for feature origins and AI involvement. This feature strategy itself involved AI-assisted analysis and ideation. Preserve that fact; do not call all proposed features solely human-originated.

For implemented features, record which tools assisted ideation, code, design and testing; summarize outputs and the team’s modifications. Keep the underlying pretrained voice model distinct from the code the team builds.

## 15. What to postpone

### 15.1 Tempting features with poor submission return

| Temptation | Why postpone it | Better use of the time |
|---|---|---|
| Train a new voice foundation model | Large research/data/compute project, unrelated to the strongest existing contribution. | Prove the controller and interruption behavior. |
| Always-listening wake word | Outside Theme 5 scope; adds background/battery complexity. | Excellent tap-to-talk and active-session behavior. |
| Build every card before submission | Spreads testing and design effort across unrelated surfaces. | Eight families and three coherent hero workflows. |
| Arbitrary third-party app automation | New permissions, UI fragility and significant scope; overlaps Theme 3. | Real public intents plus schema-driven tools. |
| SmartThings-first demo | No team hardware; account/setup risk. | S24 camera, actions and interruption proof. |
| Full personal knowledge graph | Large privacy/data/modeling problem; evaluation disallows cross-session memory. | Explicit scoped preferences and a small notebook. |
| Automatic payments/bookings | Requires real integrations and consequential-action guarantees. | Disclosed sandbox writes plus accurate native handoffs. |
| Emotion detection from voice | Easy to overclaim and unnecessary for personal usefulness. | Let users choose patient/brief/quiet behavior explicitly. |
| Automatic emergency intervention | High reliability and deployment burden, poor fit for current prototype. | Bounded preparedness and ordinary assistance. |
| A complete smart-home/health platform | Access, device and approval dependencies. | Show how the verified controller could host these integrations later. |
| Another major aesthetic redesign | The project already has an approved coherent identity. | Spend design time on state, controls and error recovery. |
| A manufactured competitor failure montage | Weak evidence and avoidable credibility loss. | Publish THREAD’s measured behavior under clear test conditions. |

### 15.2 Delivery quality criteria

It should mean someone can change their mind, lose connectivity, ask a side question, correct an image target, or misunderstand a result—and still recover without starting over.

It should mean the next team member can run the project from a clean checkout, the app does what the demo says, and the evidence shows the limits.

It should mean the card helps someone complete a real task instead of merely looking expensive.

## 16. Decisions still open

### Confirmed

- Team size: **four total**, including Ansh.
- Available mobile hardware: **the connected Galaxy S24 only**.
- Desired cards: **rich, interactive and personal**, not a paid subscription.
- Supplied hackathon: **Samsung PRISM Generative AI Hackathon, Theme 05**.
- User request: broad ambitious product ideas, project analysis and this substantial feature document.

### Not yet confirmed

1. **Primary hero journey.** The working recommendation is an everyday outing/travel plan plus a device-support visual scenario. Dinner Rescue is a strong alternative if the team prefers it.
2. **Team specialties and available hours.** The four-lane allocation is provisional until the builders choose ownership.
3. **Registration and official kit status.** The folder establishes dates/rules, not whether this team is registered or has subsequently received the kit.
4. **Cloud/network/model rules for evaluation.** The supplied Theme 5 guide does not settle them.
5. **Spending cap.** No budget was supplied or assumed.
6. **Demonstration language.** Start with the languages the team can test with real speakers; Hindi/English mixing is a promising differentiator only if the behavior is measured.
7. **Production ambition after submission.** Saved preferences, account integrations and persistent monitoring need an explicit next-phase scope.

### The decision I recommend now

Commit the submission to **an evaluator-compatible interruptible agent with measured state correctness, cancellation/reconciliation, unfamiliar-tool handling and multimodal grounding**. Use the existing presentation to demonstrate those behaviors.

The broader product ideas stay available after the submission core passes. The immediate identity is **an agent whose work stays correct when the user interrupts or changes the goal**.
