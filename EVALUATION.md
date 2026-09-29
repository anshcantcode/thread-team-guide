# Theme 5 evaluation contract and evidence

This is the **provisional thread.v1 adapter**. Samsung's actual kit has not been supplied. The implementation follows the provided Theme 5 guide's architecture, but its field names and transport are not represented as the official interface. Python **3.11** is the supported release runtime. The consumer UI, wake word and voice synthesis are outside the Theme 5 scored core.

## Run from a clean environment

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_theme5.py -q
.\.venv\Scripts\python.exe scripts/check_theme5.py --seeds 50
```

The deterministic replay requires no API key, account, microphone, persistent notebook or network after dependency installation. Six authored scenario families run over 50 timing seeds: **300 scenario/seed combinations, 600 paired executions plus 600 executions in two fresh Python processes with different hash seeds**. All three interpreters must produce identical logical traces and service effects. Scripted interpretations isolate controller correctness. They are not model accuracy scores and are not the nine Samsung scenarios.

```sh
docker build -t thread-theme5 .
docker run --rm --entrypoint python thread-theme5 scripts/check_theme5.py --seeds 50
docker run --rm -i -e THREAD_API_KEY -e THREAD_MODEL=gemini-3.5-flash-lite thread-theme5
```

The container recipe is supplied. This Windows host currently has no Docker CLI; execution of the container is a separate verification item. A fresh local virtual environment is exercised independently of the existing developer environment. The base image tag is not digest pinned; record the resolved image digest for the final submission build. No `.env`, user notebook, device credentials, or historical reports enter the image.

## Two asynchronous queues

```python
adapter = QueueAdapter(planner, clock=clock, manifests=scenario_manifests)
running = asyncio.create_task(adapter.run(wall_timeout=120))
await adapter.events.put(input_event_dict)
action = await adapter.actions.get()
# Continue producing input and consuming actions concurrently.
await adapter.events.put(None)  # EOF
```

`events` is a bounded input queue. `actions` is the output queue. Each adapter owns a fresh external-tools session. It loads only the supplied manifests, never consumer capabilities. Input `None` means EOF; output `None` means the controller has closed and released resources. JSONL stdio uses the same boundary, with a daemon stdin reader so an open peer cannot defeat the wall timeout. Stdout contains only JSON objects. Use `python -m thread_agent.stdio --sandbox` for the three explicitly fictional built-in tool environments; this mode still uses session-only storage.

The default clock is real monotonic time. `VirtualClock` is driven only by the replay harness; all controller prepare delays, speculation delays, acknowledgments and outcome deadlines use it. Seconds are the clock API unit; emitted `at_ms` is milliseconds since session start. `timestamp` is the corresponding timezone-aware timestamp. Incoming timestamps describe observations; receipt order determines precedence. The harness schedules observations against the clock rather than letting a payload move time backwards. Deterministic IDs are scoped to one replay; a real session uses unique random IDs.

The scenario wall cap is 120 seconds independently of virtual time. A timeout ends new work and emits a snapshot of unresolved submitted actions. The adapter never converts shutdown or missing confirmation into proof that an action failed. The 300-second organizer warm-up allowance is a maximum budget, not a required wait; installation and optional provider checks belong before scenario execution.

## Inputs and turn ownership

All inputs have a nonempty unique `id`, `type`, optional `text`, optional `timestamp`, and a `data` object. Duplicate IDs have no second effect.

| Input | Contract |
|---|---|
| `text` | One complete utterance, maximum 12,000 characters. |
| `transcript` | Append-only text chunk with `utterance_id` and **explicit** `end_of_turn: false/true`. Empty final chunks are permitted. Repeated delivery with the same event ID does not append twice. |
| `partial` | A complete provisional hypothesis replacing the prior hypothesis, not an append-only chunk. May start a schema-valid read; never supplies write authority. |
| `interrupt` | User owns the floor immediately. Pending interpretation is cancelled; prepared writes stay held. No inference that a noise or cough changed task slots. |
| `audio` | `data.mime` WAV and `data.base64`; 0.1–30 seconds PCM16 mono/stereo, maximum 6 MB. |
| `frame` | PNG/JPEG/WebP decoded and normalized to PNG, bounded size. Current-frame dependencies travel with lookups, including unfamiliar visual capabilities. |
| `manifest` | `data.manifest` is a new validated Manifest; an ID cannot replace an existing manifest in a live session. |
| `tool_result` | `data.call_id` and object `data.result`; optional notification ID. Unknown calls and malformed evidence are rejected before state mutation. |
| `control` | Explicit controls such as pause, cancel, resume, status, select, book and end. This is an authorized input channel, not an LLM-generated hidden bypass. |
| `speech_status` | Delivery feedback about an emitted message; does not grant tool authority. |

An interruption holds the floor until a complete utterance or explicit resume. New complete input preempts pending reasoning; clearly supplied earlier, unprocessed words/audio are carried into a fresh interpretation. Their old write requests do not authorize a new write. A cancelled provider call that returns late cannot apply its interpretation.

`stop_work` cancels ongoing reads and revokes prepared actions without requesting reversal of a submitted effect. The exact complete utterance “Cancel the search” uses this fast path. `cancel` means an explicit request to undo a submitted action. If more than one eligible action exists, the model must resolve an exact `action_id` or ask the user which one. The structured `control` channel is an explicit authorized UI/harness channel: `cancel` requests reversal; `stop_work` only stops work; `cancel_action` requires an exact `call_id`.

Model-proposed creates and cancellations also pass an independent bounded English command check. Supported examples include “Book the selected flight,” “Please save that exact note now,” and the unfamiliar-capability fallback “Submit the selected action.” Named nouns must belong to that capability's `authorization_objects`; a request to create a note cannot authorize a flight booking. Optional `authorization_verbs` must come from the supported imperative vocabulary in `authorization.py`; a manifest cannot make “yes” a write verb. Additional effects require explicit “another/additional/separate/one more” wording. Conditional, quoted, unrelated, acknowledgment-only or unsupported rich phrasing produces a clarification while retaining validated slot corrections and invalidating obsolete options. This bounded gate complements semantic parsing; it is not unrestricted English or multilingual understanding.

Native streaming captions are display/read evidence, never write authority. Google documents independently delivered input transcription without guaranteed ordering or a local speech-interval identifier. A receipt-time epoch cannot prove which speech produced a caption. The native relay therefore gives every local input a fresh token; state-changing calls must match it. Typed text is direct input evidence. Audio writes require a separate, history-free transcription of the locally captured 0.1–30 second PCM interval, with cancellation when another turn arrives. Silence, incomplete/overlong clips and unavailable verification hold the action. Only the current verified words reach the bounded command gate. This second model request adds measured latency and quota use; it is not claimed to be instantaneous. [Live API reference](https://ai.google.dev/api/live).

A new native speech turn retires any prepared but unsubmitted action before its words arrive. A fresh explicit command may authorize the current proposal again; lookup work continues and already submitted effects remain accounted for. This conservative native policy prevents a late caption, audio chunk or turn-completion packet from releasing earlier unsubmitted permission. It differs from the headless adapter's explicit EOT contract, whose prepared actions remain held until the current complete input is resolved. Android functions additionally require a current verified quote and a bounded action-specific command. This is not unrestricted phone-language understanding.

Native action permission is consumed once per input turn, including an additional action or cancellation. A different model call ID cannot reuse it. Task writes bind to the domain, slots, revision, result list, selection and image present when the request arrived; they cannot rewrite those details inside the action call. Provider withdrawal and connection closure are rechecked after audio verification, at preparation and at the phone send boundary. These limits deliberately require a fresh explicit request after a changed proposal and separate commands for multiple native actions.

The same lifecycle check also covers shared task pause/close while native verification or a phone send is pending. A monotonic interruption counter prevents pause followed by resume from restoring old permission. A selection generation prevents changing an option from A to B and back to A from reviving an old request. A fresh explicit command after an earlier clarification can authorize the current reviewed proposal. Incorrect result references remain rejected, but the function returns an explicit `state.results_id` and an argument-repair instruction: fixing the reference in the same unchanged turn does not require repeating an already clear command, and does not turn an acknowledgment into permission.

## Manifest and tool-result shape

Each manifest declares closed JSON object schemas for session slots and tool arguments, defaults, and one lookup plus optional create/status/cancel roles. Tool names are arbitrary; roles and effects are explicit. The current controller supports one tool per role. It is not a general arbitrary tool-DAG interpreter. Translate an organizer contract into these supported roles only when the official semantics are known; unsupported shapes must not be silently advertised as supported.

Schemas must be inline: `$ref`, `$dynamicRef` and `$recursiveRef` are explicitly rejected at registration, including local references. Expand references before supplying this provisional contract. The controller also reports a schema-resolution fault without killing the input worker. This restriction avoids accepting schemas whose detached slot fragments lose their reference scope. See the library's [validator and reference-context documentation](https://python-jsonschema.readthedocs.io/en/stable/validate/).

The headless model output schema preserves each declared slot's JSON type, including nested objects and arrays. `changes[].value` is a native JSON value validated against that slot; legacy encoded values remain accepted at the controller boundary. The native Live compatibility schema uses encoded values for this one generic function; dedicated read functions use native JSON. An `observe` interpretation may answer a current-image question directly without a manual lookup. Its final snapshot includes the image ID and observation. Questions about motion do not establish a reported symptom, and a label-only answer does not require an indicator selection.

Headless audio is first transcribed without conversation history, then the faithful transcript enters the same typed interpretation path as text. Both stages are preemptible. This separates acoustic recognition from slot reasoning and prevents the interpretation result from rewriting the recognized words used for authority. Earlier interrupted clips are transcribed as pending context; only the current input can authorize a new write. Audio timings include both model calls, except exact digital silence handled locally.

For a route already containing an origin and destination, a standalone city correction defaults to changing the destination; departure changes need an explicit origin/from/departure cue. This is a declared conversational convention, not a proof of all ambiguous utterances. Price comparisons use the lowest valid listed amounts from both current result collections in the same currency, retain both evidence references and report the difference. They do not convert currencies, infer absent prices or answer non-price comparisons with invented arithmetic.

Action parameters normally come from current slots. A legacy `option_id` is bound to the selected result ID. Explicit `bindings` allow unfamiliar argument names: `{"slot_code":"option_id"}`, `{"allocation_ref":"reference"}`, or `{"request_id":"call_id"}`. The values come from controller state or service evidence, never guessed identifiers. Legacy `operation_id` binds to the original call ID. Every reconciliation call validates against its declared schema before emission; missing evidence produces a clarification instead of an invalid call. Optional `result_schema` validates service output.

Successful lookups return `{"status":"completed","source":"...","items":[{"id":"...","title":"..."}],"summary":"..."}` with optional evidence locators. Item IDs must be unique. Write completion requires `status: completed` and a nonempty `reference`. `unknown`/timeouts preserve uncertainty and block ordinary replacement. A negative status response cannot erase an already confirmed effect. Cancellation is a request until the service confirms it. The external service must enforce idempotency on `call_id`; the mock ledger tests this independently.

## Output and timing interpretation

`tool_call` has explicit `call_id`, `tool`, `effect` and validated `arguments`. `cancel` identifies the superseded read or action being reconciled. `speak`, `clarify` and `final` are textual speech actions; `speak` indicates whether audio delivery is allowed. `final.state_snapshot` includes the current goal, slots, selected option, source evidence, action outcomes and unresolved call IDs. `snapshot` provides fuller diagnostic state. No UI panel is required to access the final evidence.

One delayed progress action may describe an actual coordination decision: holding a named prepared action or retaining current task details while withholding arriving results. This is distinguishable from generic receipt acknowledgment and from semantic understanding of the new correction. Reports must show **all three** separately. The model's input-to-corrected-slots delay is never replaced by the shorter acknowledgment measurement. Local/server measurements are not physical speaker onset or acoustic interruption latency.

## Actual model acceptance

`evaluation/corpus.json` freezes 30 authored cases: 15 text, 9 audio, 6 visual. Expectations are not in model context. Audio is Windows synthetic English speech; one case is silence. The six visual requests use the existing fictional router fixture. Explicit initial states let the tests probe correction, reference and action behavior; they do not count those setup states as earlier model successes.

```powershell
powershell -NoProfile -File scripts/make_acceptance_audio.ps1
.\.venv\Scripts\python.exe scripts/check_acceptance.py
```

This calls the configured Gemini/local **headless** model and consumes its normal quota. It is separate from the phone's Gemini Live model. Reports preserve input fixtures, interpretations, answers, evidence, effects, source/corpus hashes and timing for critical review. Report failures as failures; use `--ids` only for diagnosis and rerun the full frozen corpus on the final candidate. Neither passing this corpus nor an internal reviewer score proves Samsung hidden-test performance or predicts a win.

The original 2.5 Flash run encountered a daily free-tier quota and did not verify its remaining media cases. The user authorized another supported model. The first 3.5 Flash Lite full run passed 29/30 checks but created one unauthorized mock booking from an acknowledgment; it is preserved as failed historical evidence. Subsequent runs must validate the independent authority gate against the same corpus and new independent cases. Passing familiar cases after repairs is regression evidence, not an untouched held-out score.

For a separately frozen corpus use `--corpus PATH --output NEW_REPORT_PATH`. Optional corpus `manifest_files` loads unfamiliar manifests; each case can supply explicit `initial_state`, a mock `lookup_result`, `audio` and `image` paths. Those fixtures and expected answers are authored by the evaluator; only ordinary inputs, declared manifests and service results reach the model. Preserve the first attempt rather than replacing it after fixes.

`evaluation/corpus-v2.json` preserves the original 30 inputs and records its predecessor hash. Its stronger assertions reject unwanted speech muting, require a real separate comparison lookup, and reject inventing a blinking symptom from a question. It permits the newly introduced observation answer for that visual request. The original corpus and its reports remain unchanged. The independent ten-case first attempt remains 8/10 strict automated, 9/10 after an explicitly recorded place-spelling adjudication, and 7/10 under the reviewer’s complete authored criteria. Subsequent runs of those now-known cases are development regressions, not new held-out evidence.

```powershell
$env:THREAD_MODEL = 'gemini-3.5-flash-lite'
.\.venv\Scripts\python.exe scripts/check_acceptance.py --corpus evaluation/corpus-v2.json --output reports/theme5-acceptance-gemini-3.5-flash-lite-v2-full.json
.\.venv\Scripts\python.exe scripts/check_native_authority.py
```

The second command tests six owned-PCM authority cases with the actual transcription model and deliberately delayed streaming captions. It includes a legitimate booking command, acknowledgments, negation, correction, a wrong action object and silence. The provider function calls and packet ordering are controlled test inputs; this is not a measurement of Gemini Live's autonomous tool selection. Audio fixtures are synthetic English and the service effects are fictional.

## Responsiveness and process lifecycle

`python scripts/check_responsiveness.py` runs 25 fresh sessions with a stated 400 ms scripted interpretation delay. It measures real event-loop coordination, correction-to-cancellation after interpretation, exact-stop cancellation and retained slots. `--actual-model --repetitions 20` runs the same interruption checks with the configured provider and consumes quota. The latter tests repeated timing for one authored correction phrase, not language diversity. Both keep semantic delay separate from the faster coordination signal and report p50, p95 and maxima.

Gemini pure generation has at most three attempts under a shared 45-second wall budget per generation, including backoff. Each attempt has a 20-second response timeout and a five-second connect timeout, further restricted by remaining budget. Only transient transport errors and HTTP 500/502/503/504 are retried; quota, authorization and request-format refusals are not. The complete request body is retained across retries. Interruption cancels requests and backoff, and a dependency that swallows cancellation cannot make a late answer authoritative. Other HTTP failures are sanitized and contained so a subsequent input can still be processed. Tool execution is outside this retry loop.

Each `provider_attempt` records its model request ID, owning input ID or native epoch, attempt number, safe outcome class/status, duration, total elapsed time and whether a retry was planned. It contains no request body, key, URL, headers or raw provider exception text. Context-local observers keep concurrent sessions separate. Native speech verification and headless WAV transcription use the same bounded transport. A WAV may need two generations and therefore approach 90 seconds before other work; the adapter's independent 120-second wall cap still applies. Full receipt-to-interpretation timing includes attempts and backoff and must never be replaced by only the final successful request duration. Historical failed batches stay preserved.

`python -m thread_agent.warmup` checks the supported runtime/import path without a provider request. `--check-provider` performs a real provider check, bounded by the 300-second allowance. Every evaluation adapter has a separate 120-second wall cap. Stdio uses a daemon reader so an open input pipe cannot hold process shutdown hostage. Optional local Whisper runs in an owned subprocess that is killed and reaped on cancellation; it does not leave blocking executor transcription threads alive. Local model weights are an optional setup dependency, never downloaded implicitly during a scenario.

On 14 September, a fresh Python 3.11 virtual environment installed `requirements.lock` and ran the full 528-test Python suite. The working environment also passed the three JavaScript suites. Two installed S24 release-app microphone lifecycle cycles passed against the restarted server. These statements describe those recorded runs; source hashes in the reports determine whether they still match a later edit.

## Research used

The supplied Theme 5 guide controls scope and scoring. [Sierra's interaction metrics](https://github.com/sierra-research/tau2-bench/blob/main/docs/interaction-metrics.md) support separating responsiveness, yielding and interruption selectivity. [Pipecat's lifecycle documentation](https://github.com/pipecat-ai/pipecat/blob/main/COMMUNITY_INTEGRATIONS.md) reinforces prompt interruption handling and guaranteed resource cleanup; no Pipecat framework code was imported. [ElevenLabs' winners announcement](https://elevenlabs.io/blog/announcing-the-winners-of-the-elevenlabs-worldwide-hackathon) illustrates the presentation value of a clear, observable technical behavior. [Reddit accounts](https://www.reddit.com/r/hackathon/comments/1s2di3z/whats_the_smartest_hackathon_strategy_youve_seen/) are anecdotal, not Samsung judging evidence. Targeted X searches yielded no usable authoritative Theme 5 guidance; no conclusions are attributed to inaccessible posts.
