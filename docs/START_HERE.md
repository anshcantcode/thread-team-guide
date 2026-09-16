# Your first 15 minutes with THREAD

[Home](../README.md) · [What works](WHAT_WORKS.md) · [Setup](RUN.md) · [Code map](CODE_MAP.md) · [Team plan](TEAM_PLAN.md)

## First, understand the problem

A voice assistant can stop speaking while an obsolete search or action continues behind the scenes. THREAD treats an interruption as a possible change to the work itself.

We want a user to be able to say “actually Mumbai” without repeating the origin, date, and time. We also want a booking permission for one option to become unusable after that option changes. If an action has already been submitted, the assistant must account for its real outcome instead of pretending it disappeared.

The language model interprets the request. The task controller decides which state, result, and permission are still current.

## Minutes 0–5: explore the app

Use the installed Android app with its owner, or follow [Setup](RUN.md). A new phone needs its own configured Gemini key. Start with **Type instead** to learn the result screens, then use **Start talking** to explore interruption behavior.

These are exploration prompts, not a promise that every provider will be available at every moment:

| Try | Look for |
|---|---|
| “What is 17 times 19?” | A calculated result of **323**. |
| “Show the weather in Chennai.” | The named city, forecast, source, and dates. |
| “Show the time in Chennai and Tokyo.” | Two correctly labelled clocks. |
| “Find papers about speech interruption.” | Paper metadata and links; not a claim that full papers were read. |
| “Make a packing checklist for a two-day trip.” | A useful draft checklist that can be opened again from Library. |

On Android, new informational results can open their detail screen while the voice dock remains available. Use Back to return to the conversation, then **View result** to reopen the result. Explore the Home/Library and Widgets screens as well as the call screen.

## Minutes 5–10: try a correction

### Change a Google search tab

Start one conversation:

1. “Search Google for cat images.”
2. “Open videos instead.”

Look for the same search subject with the new tab. This is a handoff to Google, not a browser-control agent clicking arbitrary websites. A handoff receipt means Android accepted the destination; it does not prove that every page finished loading.

### Change a travel request

Use the explicitly labelled **demo flight** scenario:

1. Ask for flights from Chennai to Delhi, specifying a date and a time constraint.
2. Interrupt or correct it with “Actually Mumbai. Keep the date and time.”
3. Inspect the task details: destination changes; origin, date, and time remain.
4. Check that a late result from the earlier request cannot replace the corrected result.

Read-only exploration needs no booking. If testing a write, first confirm you are using the fictional service, select a current option, and explicitly request that action. “That looks good” is not the same as “Book the selected flight.”

### Try an interruption with your voice

Start a spoken answer, then speak a correction. Observe both the audio and the result state. A brief noise can pause output without becoming a new request; real words can replace the task. Record what actually happens rather than assuming the configured speech threshold equals measured acoustic latency.

## Minutes 10–15: make something personal

Try a world-clock or weather widget using the Widgets screen. Preview it and complete Samsung's **Add** confirmation only if you want it on the home screen. A preview alone does not pin the widget.

For notebook recall, preview a note, explicitly save it, and search for it later. THREAD's notebook contains what the user deliberately saved. It is separate from arbitrary phone files, messages, and other apps.

Finish by opening [Code map](CODE_MAP.md) and choosing one path:

- **Conversation and safety:** follow a correction through the controller.
- **Android and design:** follow a result from the model into a card or widget.
- **Tools and data:** follow a provider response into a sourced result.
- **Evidence and presentation:** follow one claim back to a specific report.

## Words we use

| Term | Meaning |
|---|---|
| Task | The current piece of work and its retained details. |
| Revision | A newer version of the task after relevant input changes. |
| Result/card | A structured answer with content, source information, and any supported actions. |
| Tool | A bounded operation such as weather lookup, calculation, or note saving. |
| Read | An operation that retrieves or computes information. |
| Effect/write | An operation that changes something, such as saving a note or creating a fictional reservation. |
| Authority | Permission for a specific current action, tied to the user's actual request. |
| Obsolete/stale result | An answer that belongs to an older request and must no longer drive the current task. |
| Unknown outcome | An action was submitted, but its final effect is not yet established. It must not be blindly repeated. |
| Fixture | Deliberately supplied sample data used for reproducible testing. |

## When something fails

Write down the exact words, whether input was typed or spoken, the visible result, and what you expected. Include app version and whether the network was available. A missing provider response, a wrong interpretation, a stale result, and a rendering problem are different bugs.

Do not share API keys or private notebook content in a bug report. The [team plan](TEAM_PLAN.md) has a short report template.
