# FDB-v3 migration — implementation and limits

## Current pipeline (27 September)

Recorded audio → LiveKit room (VAD) → faster-whisper base.en (CUDA; optional
input-only vocabulary prompt built from the public tool contract) → logical-turn
assembly (pauses and late decodes stay context of one turn) → LocalPlanner
(Qwen3.5-4B via llama.cpp, schema-constrained JSON, clause-cited writes) →
argument normalisation (heard identifier spelling, cut-short identifier
completion, unstated optional numbers dropped, `<noun>_type` values) →
ParticipantAgent write gate and value checks → upstream mock registry →
outcome ledger → bounded follow-up planning for remaining requested work →
spoken result (portable command TTS; espeak-ng on Linux, SAPI only as a Windows
development profile).

Controller rules that shape results:

* **Write gate with recorded reasons.** A write needs one current, affirmative
  command whose cited clauses survive negation, cancellation, retraction and
  condition checks; every refusal records why (`gate` in the clarification
  event). Conditions scope their own sentence; a pro-verb consequent
  ("if it's cheap, do it") or a condition in the command's sentence still
  refuses. Price conditions are verified against this request's own returned
  prices; subjective conditions ("if it looks good to me") refuse.
* **Dependencies wait instead of failing.** "Once you find something, book it"
  defers the write until the request's own lookup returns, and the follow-up
  round re-plans it; a pending price condition waits the same way.
* **Hold markers.** A turn ending on "wait", "hold on" or "let me think"
  starts planning after a bounded 2 s; new speech cancels it.
* **Per-scenario model cache.** Prompt-prefix reuse only within one scenario:
  every server slot is erased at each scenario boundary, uncached if the erase
  cannot be confirmed.
* **Planner memory is not authority.** A repeated key inside the planner's
  `slots` memory drops that memory; a repeated key anywhere that affects an
  action remains a protocol error.

Evidence and limits: `docs/fdb3/SPRINT2.md` and `.thread-run/experiments.jsonl`
(local Qwen judge, not the organizer's judge). The historical notes below
describe how each safeguard was introduced; where they conflict with this
section, this section is current.

`scripts/fdb3_agent.py` provides a LiveKit AgentServer room entrypoint.
`scripts/fdb3_audio_worker.py` uses the same AgentSession with file audio I/O
or two actual WebRTC participants on a loopback LiveKit server.

Audio → LiveKit VAD/STT adapter → local Whisper → ControllerLLM →
LocalPlanner → existing `participant.agent.ParticipantAgent` →
exact upstream mock registry → controller outcome reconciliation →
LiveKit TTS adapter → command TTS (Windows SAPI in development, espeak-ng on
Linux) → captured PCM.

The migrated path reuses the generic participant controller, its state revisions,
authorization, dependent-result bindings, duplicate suppression and operation ledger.
It does not claim to reuse the application's separate domain-specific Engine.
The debug Android extension uses this same controller via the desktop bridge,
explicit emulator serial, and native receipt protocol. The standalone Android
speech path still uses the legacy application runtime; it has not been migrated.

The local model renders the unchanged controller proposal prompt with llama.cpp's
native template endpoint and generates schema-constrained JSON through its native
completion endpoint. This avoids an observed chat-endpoint JSON-format failure.
The controller validates schema/authority before emitting
a dispatch. The bridge checks freshness again at the execution boundary. Speech
arrival synchronously marks earlier revisions ineligible, before queued controller
events are processed. Blocking mock registry work runs in a thread. A submitted
effect is not assumed cancelled when audio or planning is interrupted; its actual
result still reconciles in the controller ledger. Every invocation enters the trace
before execution, including failed/unknown outcomes. Admission is rechecked inside
the executor thread: waiting for a free thread does not reserve permission.
Queued operations rejected at that boundary are explicitly `not_submitted`.
Read results cannot authorize
invented write identifiers. Read-only spelled identifiers receive a bounded lexical
normalization; write grants are never rewritten by this rule.

Each worker owns one new controller/registry/recognizer/session. Prompt-prefix
reuse is scoped to one scenario (every server slot is erased at the scenario
boundary) and observed usage, including cached tokens, is saved per request. The agent
receives an opaque audio path plus a contract directory containing only three
public upstream files. Metadata is read by the evaluator after worker exit.
This is process/input separation, not an OS-enforced filesystem sandbox: the
same-user process could access other local paths if malicious. That stronger
isolation gate is not passed.

Real loopback WebRTC transport has run using LiveKit 1.13.7's development server
and public development key, with incoming recordings, actual registry calls and
received synthesized audio. The first room slice's raw strict boolean was true,
but malformed judge responses made that evaluation invalid. Its artifacts remain.
Complete 100-recording local diagnostics are recorded in `docs/fdb3/SPRINT2.md`. There is no cloud transport,
hosted dispatch or physical microphone claim. Received RTP includes silence;
first-frame timing is not meaningful-speech latency or an official latency score.
Future workers separately record received signal above a declared -40 dBFS
threshold and LiveKit state transitions. This is diagnostic instrumentation, not
semantic speech detection or the organizer's latency normalization. Output
transcription uses silence filtering after an independent synthetic control
reproduced Whisper inventing "You" during 35 seconds of silence. Original received
WAV files remain intact; reference text is never supplied to recognition.

Multiple controller result messages are combined for the active voice turn.
Shutdown waits for recognition, current planning and execution to settle, rather
than treating an earlier speech-completion event as proof the final correction
was processed. These fixes have independent tests; the running frozen baseline
predates them and must not be presented as their live validation.

`--manual` and `--unpaced` are explicit diagnostics and are never qualification.
Automatic VAD is the default. Backchannels, partial transcript replacement,
fully independent cancellation of concurrent tasks, bounded long-session
history and audio reconnect races still need further integration work. In particular,
the controller retires old continuations, while an explicit fresh proposal may
retain an admitted older-revision read whose full arguments and dependencies are
unchanged. Retention creates a separate consumer; it neither re-executes the
backend nor rewrites the original outcome. A dependency change before or after
the result invalidates that consumer, including its use in later write bindings.
Queued reads require a trusted non-submission receipt before fresh dispatch.
Writes and completed-result caches cannot be retained. These controls do not
establish fully independent simultaneous task cancellation or live validation.
The model-input view now keeps the complete current utterance, structured active
constraints and full outcome ledger while retaining only four prior transcript
messages. Original message indices remain stable. This bounds obsolete transcript
in the prompt; it does not bound the durable ledger or prove long-audio behavior.

The exact upstream strict and quality evaluators run after inference. Their
prompts and scoring are unchanged. A declared local Qwen judge uses one native
schema-constrained generation per judge request; every attempt is retained.
The compatibility alias `gpt-4o` in the upstream client is not the actual model.
Any failed/malformed judge request invalidates the case, including when upstream
silently returns its exact-match fallback. All local reports are diagnostic and
ineligible for the three-run qualification gate.

New workers journal tool dispatch intent before backend I/O, with a second
freshness check after the disk flush. Disk writes occur outside the admission
lock. A killed worker leaves a possible invocation with unknown outcome; it
cannot be counted as definitely unsubmitted. Completed receipts reconcile even
if their journal write fails, but such a run is rejected as experiment evidence.
The runner compares final actual calls with the durable tool trace before
evaluation. It runs both agent and evaluator from the frozen source snapshot.

Model, recognition and judge attempts now have durable pending/final checkpoints.
Pending request counts describe submission intent, not proof of server admission
or known tokens. Accounting folds journal snapshots by request identity and
recovers valid journals beside missing or malformed final reports. Earlier runs
predate these controls; their missing usage remains unknown.

Assistant playback context uses LiveKit committed conversation items and message
IDs. The pinned SDK can commit full generated text after an interruption when it
has no synchronized transcript. Therefore interrupted text is omitted from model
context and explicitly marked delivered_text_unknown; the raw SDK text remains
in voice evidence. A longer stale chat snapshot cannot restore it. Uninterrupted
text remains an SDK estimate, not measured human hearing. Exact interrupted
prefix synchronization is still unimplemented. Assistant text cannot authorize
a write or establish an effect outcome. Receiver task failures now propagate
through room cleanup and invalidate a partial audio capture.

The new separate latency diagnostic invokes untouched upstream latency logic
with captured input/output clock origins and evaluator-side input ASR. Timing
alignment uses frame-arrival clocks and includes RTC jitter. Local ASR and local
judge identities remain explicit. Missing clocks or incomplete judgments cannot
be converted into complete latency evidence for older runs.

The local route is a Windows development implementation: SAPI is not portable to
the organizer Linux host. A portable authorized speech/provider route is a remaining
reproduction requirement, not hidden behind a successful local import.

The current adapter shares one SDK VAD stream and stamps each segment with its
identity and input epoch at onset, before queued recognition begins. Successful
empty recognition retires that segment's waiter and gives a fixed clarification;
it cannot restore old permission or retry an effect. Nonempty final transcripts
carry single-use provenance through the SDK conversation message ID into atomic
controller admission. Delayed old recognition, reused IDs, changed text and
mixed-epoch coalesced fragments cannot gain fresh authority. Raw recognition and
rejected delivery remain evidence. Rejecting mixed fragments can lose useful
context; safe historical context recovery remains incomplete.

Independent review caught stale nonempty recognition gaining current authority
in the first shared-VAD implementation. The repair has actual SDK queue/admission
race tests and identical-text/different-message tests. These tests establish the
tested boundaries, not complete live correction performance.
