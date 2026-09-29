# THREAD: demonstration storyboard, 23 September 2026

**Draft for a 4 minute 40 second film. Current-build results and recordings are pending.** This document specifies the story and the evidence to capture; it does not report a successful demonstration. Finalize the spoken wording only from the completed [evidence checklist](DEMO_EVIDENCE_CHECKLIST.md).

The story is simple: a person changes a request while work is running; THREAD must use the new request, look up a real result and carry out only the authorized action. The viewer should be able to follow that chain without reading code.

| Time | Picture and action | Narration to use only when the displayed evidence supports it |
|---|---|---|
| **0:00-0:15** | Title: “THREAD — keep the task consistent when the request changes.” Show the exact demonstrated build and whether this is a live capture or recorded replay. Label the tool environment. | “A changed request can leave old work in flight. Here is the request, the lookup result and the action that actually followed.” |
| **0:15-1:40** | One continuous correction → lookup → authorized-action sequence. Show the user input, pending lookup, corrected field, replacement result, action request and returned confirmation. Keep the original timestamps visible. | “The destination changed; the date stayed the same. This is the result returned for the corrected request. The user then authorized this option. The action's returned confirmation is what supports the final answer.” |
| **1:40-2:30** | Two clearly separated audio excerpts: an ambiguous recording requiring clarification, then a recording with a self-correction. Play the actual input sound and show the corresponding accepted input identifier and events. | “This input is an audio recording. In the first example, the agent asks for clarification before searching. In the second, the speaker corrects themselves; the lookup uses the final intended value.” |
| **2:30-3:05** | Show the actual submitted image, the observation, the relevant manual lookup, the returned passage/page and the final answer. Keep image evidence and manual evidence visually distinct. | “This is the image the agent received. The manual search returns this passage. The answer keeps the supported details and names the source.” |
| **3:05-3:35** | Briefly show a tool manifest supplied at run time and its valid call/result. Show a separate read-failure/retry excerpt only if both fit clearly. Label distinct runs. | “This tool's name and arguments come from the supplied schema. Here is its returned result.” If the separate retry is shown: “This read failed, then a bounded retry returned the evidence used in the answer.” |
| **3:35-4:00** | Show the final quickstart and an actual clean setup record: environment, dependencies, secret variable name with no value, configuration check and participant entry point. Show the tested operating systems and recorded duration. | “The documented setup creates the environment, installs the pinned dependencies and selects the configuration. This is the package and the setup record used for these results.” |
| **4:00-4:40** | Hold a readable results card: exact package identity, public attempts, mandatory/full outcomes, safety and factual-review findings, independent media checks, operating systems and known limits. Close on reproducibility and attribution references. | Use the evidence statement below with recorded values. End with the specific remaining limitations, if any. |

**Proposed main dialogue.** These lines describe an additional demonstration, not one official public scenario. Use only values supported by the actual demo manifest, with an unambiguous date. The example names below do not become expected runtime answers.

1. User: “Find flights to Kochi on 10 October 2026.” Let the first lookup visibly start.
2. User, while it is pending: “Actually, Pune. Keep the same date.” Show the corrected state and what happens to the old lookup.
3. Show the actual replacement result. Select a unique option from that result; display its returned identifier and supported fields without inventing price units or availability.
4. User: “Book that option for Maya Rao.” If “that option” is not uniquely bound by the visible exchange, use the exact displayed option or ask a real clarification. The booking remains in the explicitly labelled test tool environment.
5. Show the single intended action, its response and the final confirmation. The action's identifier must come from the returned evidence. Do not script an assistant success response in advance.

This composed sequence needs its own recorded run from the frozen package. Separate official correction and booking runs can support the same explanation, but they must be shown as two examples. Do not edit separate runs into a fabricated continuous session. “Real lookup” here means an actual call and response in the stated tool environment; Samsung's mock booking tools do not purchase a commercial ticket.

If an old read returns after the correction, show why it does not replace the current answer. If a write has already succeeded, cancellation does not undo it: show the observed outcome. Include that harder race only when a retained trace demonstrates it; do not imply the main correction clip proves every late-write case.

**Recording rules.** Preserve the waits in any segment used to discuss timing. A replay should carry “Recorded replay” throughout; a deterministic or mock tool environment should be named. If a segment is accelerated or shortened, label it and do not use its screen duration as a latency result. Show separate times for acknowledgment and completed answer when those measurements are available. A fast filler is not proof that the agent understood the correction or finished the task.

Use a legible transcript and a small event view with the current request, active lookup/action, result and outcome. Existing logs are enough; a new interface is not required. Raw protocol fields can remain in a readable evidence inset while the main view uses “request,” “lookup,” “result” and “confirmation.” Do not display secret values, local usernames or private coordination material.

The 4:40 schedule leaves 20 seconds below five minutes. Measure the finished export, including title and end cards. If honest waits make the film too long, remove the optional retry excerpt or reduce narration; do not conceal waits to manufacture speed. Keep the uncut source recordings as evidence.

**Qualification-dependent edits.** If the final run fails, show the failure as a limitation and remove the unsupported success sentence. If a required audio/image recording is still missing, mark it “not demonstrated”; a waveform, typed transcript, filename, stock image or generated animation cannot substitute for actual perception. If only a manual title is returned, say which source was found and that no supporting passage was available. Do not present a title as proof of a technical specification. Claim the image-embedding checkpoint only with the actual image hash, embedding response and accepted tool call retained.

Keep the final model name identical to the demonstrated configuration. Product inference attribution belongs in the results card; complete the required assistance disclosures and third-party credits truthfully. Do not invent team members, college details, signatures, repository tags or public video links. This storyboard does not require a release or an upload to prepare the local film.

**Results-card wording, pending evidence:**

“Package [SHA-256], source [commit], using [provider/model and configuration], was evaluated on [OS/Python] with the unchanged supplied kit [identity] at normal timing. Mandatory outcomes: [x/27]; full checkpoints: [x/27]; safety/protocol violations: [count]; weighted automated score: [value]. Factual review: [scope and findings]. Independent inputs: [run/pass/failed/blocked/unrun counts by modality]. Clean setup: [systems and results]. Demonstration excerpts: [run references]. Remaining limits: [specific items].”

Keep every bracketed field pending until its evidence exists. One complete passing 27-attempt public batch supports public-kit qualification of that artifact. A second identical-artifact batch, independent inputs and clean Windows/Linux setup support stronger confidence. None establishes hidden-test success or a chance of winning. Historical candidate 009 and 010 results must not fill this card.
