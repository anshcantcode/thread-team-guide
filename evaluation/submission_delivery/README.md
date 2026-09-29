# Independent submission checks

This additive test surface exercises controller mistakes beyond the supplied kit.
It never enters the participant package. It does not modify runtime, the official
evaluator, or the older frozen challenge corpus and oracles. Dependencies are the
repository's existing Python environment; media preflight also uses installed
FFmpeg. No inference model is downloaded, and none of these commands calls a
provider.

Run from this checkout, using a new output path for every attempt:

```powershell
python -B -m evaluation.submission_delivery.run_controllers --candidate '<candidate-root>' --kit '<unchanged-kit-root>' --partition development --out '<new-development-evidence>'
python -B -m evaluation.submission_delivery.run_controllers --candidate '<candidate-root>' --kit '<unchanged-kit-root>' --partition holdout --out '<new-holdout-evidence>'
python -B -m evaluation.submission_delivery.run_races --candidate '<candidate-root>' --out '<new-race-evidence>'
python -B -m evaluation.submission_delivery.run_races --suite flight-chain --candidate '<candidate-root>' --out '<new-flight-command-evidence>'
python -B -m evaluation.submission_delivery.run_races --suite audio-agreement --candidate '<candidate-root>' --out '<new-audio-agreement-evidence>'
python -B -m evaluation.submission_delivery.holdouts --bundle '<private-bundle-root>' --freeze-sha256 '<independently-received-freeze-hash>' --out '<new-preflight.json>'
```

`run_controllers` delegates to the existing acceptance adapter. It selects only
the 2,880 injected-controller cases from the 3,136 authored catalogue, fixes
`--execution controller --clock auto --settle-turns 40`, and adds the existing
acceptance socket guard. Missing-result watchdog cases use the real clock;
other cases use the adapter's synthetic event schedule. These are controller
logic checks, not 2,880 model conversations or proof of real provider deadlines.
The original 80 text, 80 audio and 96 image cases remain distinct and are not
silently counted as run by this wrapper.

`run_races` runs 11 new test methods: nine controller checks and two mocked
planner/media checks. The invalid-media method has two explicitly labeled
subtests, which are not added to the method denominator. Queue helpers are
reused from the old tests; old test classes are not collected. The checks cover:

- Empty interruption with no replacement; cancellation and late-read suppression.
- An actual continuation-repair clarification while another read remains pending;
  a late sibling must neither finish that suspended request nor dispatch its write.
- Fresh authorization for an additional, identical effect after an earlier success.
- Selected actual result bindings, ambiguous rows and forged result identifiers.
- Confirmed late write success: durable outcome accounting without stale speech
  or continuation, preserving the current state and clarification.
- The exact write-watchdog boundary, canceled transport that returns late, and
  invalid audio/image inputs before any HTTP attempt.

Failures are ordinary failures, not `expectedFailure` or silently adjusted
assertions. `results.json` records source hashes, Python identity, individual
outcomes, subtest detail, blocked network attempts and before/after source
equality. `unittest.log` retains tracebacks. The current late-write check requires
silent durable accounting, matching the original kit's stale-result contract.
An earlier internal design required an unsolicited factual notice; that design
was corrected because the kit provides no exception for grounding later speech
in a stale result. Its historical failures remain retained, and the original
supplemental silence assertions were not changed.

`run_races --suite flight-chain` selects only nine independently authored test
methods in `test_flight_chain.py`. They exercise the real local Planner route and
controller, with the model-generation boundary mocked and HTTP rejected. Four
positive substitutions vary destination, passenger spelling, weekday and time;
bounded negatives check constraints, references, authority, fresh-turn provenance
and schema changes. Queue replays verify actual second-row binding,
missing/ambiguous/invalid identifiers, duplicate results, and a
correction queued with a late result. Labeled subtests are not additional methods
or model conversations. Fallback assertions preserve the entire original context;
they do not claim that the model would interpret it correctly.

The initial draft accepted arbitrary capitalized multiword passenger names. Its
retained independent failure absorbed `Nia Carrying Lithium Batteries` as a name.
The approved narrower contract accepts one unquoted Unicode name atom, including
internal ASCII hyphens/apostrophes. All names containing whitespace, including
legitimate full names, intentionally use the ordinary model route. The original
failed receipt and test source remain separate from checks of this revised scope.
A second retained draft accepted `myself` as a literal passenger name. One offline
replay confirmed that the ordinary controller dispatched that incorrect name with
an actual returned flight ID. The final independent run passes both retained
counterexamples by requiring the local route to defer their complete context.

`run_races --suite audio-agreement` selects nine independent methods for the bounded
terminal flight-read audio comparison. Eight use mocked native responses through
the real Planner; one has small pure-helper boundary checks. The 23 labeled
subtests are not extra methods or conversations. Tiny public MP3 fixtures exercise
attachment and transport; they are not speech-understanding evidence. Tests retain
the wrong-native initial-clip veto, prior uncertainty, raw current transcripts and
cache text; check the precise formatting audit; and reject failed/uncertain current
perception, material words/numbers/interior punctuation, writes/dependent actions,
extra calls/arguments, mismatched effective entities, literal history, stale source
metadata and later-repair differences.

The approved read policy is a domain assumption, not proof of the goal hidden in
earlier uncertain audio or of arbitrary literal fidelity. A labeled baseline
control demonstrates that even exact agreement can allow an inappropriate injected
read after unrelated uncertain history. Another records existing slot synchronization:
the old `_decide` path makes duplicate state slots follow dispatch arguments before
the comparison. Raw provider slot fields are not claimed unchanged; effective args
and slots must match the parsed entity. The initial mistaken raw-slot pipeline
expectation remains in its failed receipt; corrected checks exercise a surviving
argument mismatch in the pipeline and a raw-slot mismatch directly at the helper.
These baseline controls are not newly introduced permissions or model-quality wins.

The private holdout has 18 independently authored stories: six text, six actual
decodable synthesized-speech MP3s and six original raster diagrams/documents.
These are synthetic media signal fixtures, not human recordings or photographs.
Voice/encoding provenance, source WAVs, image rendering source and local-use
licence limitations are retained with the exact asset bytes outside git. Version
2 adds explicit spelling to unfamiliar proper names in two speech scripts before
any model attempt. Version 1 remains immutable. They are the same 18 stories,
not 36 independent cases.

`inputs.jsonl` contains only manifests, scheduled input events and scripted tool
responses; `answers.private.jsonl` contains the expected checks and synthetic
witnesses. Speech transcripts and image descriptions are separate private
authoring files. Audio events contain only a media reference and turn marker;
image events contain only a media reference and frame identifier. The tool
driver exposes mock results only after a real participant call. Tool descriptions
contain schema hints, not expected result values. Filesystem isolation is
procedural on the shared host, not an access-control claim.

Acceptance owns the first real-model run after recording a frozen candidate and
receiving the provider slot. Reuse `evaluation.samsung_acceptance.adapter.Driver`
with `clock_mode="real", injected=False`; do not create a second executor:

```python
cases, private_answers, freeze = load_bundle(bundle, expected_freeze_sha256)
# For each case: set the candidate's media root to the bundle, observe actual
# media reads using the acceptance media_bindings observer, and run Driver(case).
# Do not attach the answer, witness, transcription or image description to Driver.
verdict = evaluate(case, private_answers[case["id"]], actual_trace)
```

The existing `observe_media_reads` takes a record with `assets` entries containing
`staged` (absolute asset path), `original_ref`, `sha256`, `bytes` and `mime_type`.
The bundle's `provenance.json` supplies the asset path/hash/length; speech uses
`audio/mpeg`, images use `image/png`. Media access obligations require this actual
loader-return telemetry; opening files during preflight does not satisfy a run.
Use the unchanged candidate's normal timing/configuration and retain every
failed, blocked or unrun attempt separately. Real provider execution is absent
from this module by design.

The independent adapter now has an opt-in `--bundle` route. Its worker reuses the
same `Driver`, `TransportObserver`, `QuotaObserver`, `DecisionObserver` and media
read callback; `run` has a closed `--worker adapter` choice. The default supervisor
worker and public recorder/audit remain unchanged. The legacy independent CLI
continues to require text-only real-provider mode; mixed media is admitted only
through the whole frozen-bundle route, without filters or input transformation.

Future supervised worker command (each placeholder must be fixed by a separately
reviewed allocation; this command is not a live authorization):

```text
python -B -m evaluation.samsung_acceptance.run --worker adapter --out <new-private-batch> --wall-seconds <approved-seconds> -- --candidate <frozen-package> --kit <frozen-package> --reference-kit <original-kit> --bundle <private-bundle> --freeze-sha256 <author-freeze-sha256> --archive-sha256 <approved-package-zip-sha256> --execution real-provider --clock real --provider-case-limit 18 --max-generation-requests <approved-generation-starts> --max-embedding-requests <approved-embedding-starts> --cap-generation-model <approved-exact-model>
```

The private review command imports no participant and loads no environment file:

```text
python -B -m evaluation.samsung_acceptance.adapter --candidate <same-frozen-package> --kit <same-frozen-package> --reference-kit <original-kit> --bundle <same-private-bundle> --freeze-sha256 <author-freeze-sha256> --archive-sha256 <approved-package-zip-sha256> --review-evidence <private-batch/run> --out <new-private-review.json>
```

Python 3.11 and HTTPX 0.28.1 are required for the observed coroutine/dispatch
boundaries. One counter spans the entire batch, including setup, warmup, acoustic,
planning, embedding, failed and cancelled request starts. The first captured 429
or exhausted/unsupported dispatch stops the batch. A decision, quota or media
observer capture failure also stops the current attempt and leaves later rows
unrun; partial evidence and observer errors remain in the receipt. Every case gets a persistent
unrun marker before execution and a started marker before setup; stopped/failed
attempts and the remaining unrun rows survive. Case timing is unchanged, with an
independent outer case bound of 305 seconds plus its authored event/tail duration.
The supervisor bounds and reaps the worker, then hashes its retained receipts.

Review checks the original bundle/order, package ZIP identity, source/tooling
hashes, imports, supervisor completion, global budget, native decision transport,
actual media evidence and any submitted vector against native embedding values.
Text can instead be labeled as a verified local outcome when the participant's
local-planning record matches the completed planner return and final applied
decision, and the unchanged trace oracle passes. The terminal planning record
must be local, and the last planner return must precede and match the final
apply. An earlier local marker cannot label a later native continuation local,
even when both retain the same revision or identical decision values. Later
unapplied returns are conservatively insufficient. Old canceled requests and setup
calls remain counted; zero transport is not required. A failure fallback or the
mere absence of native decisions is not proof of a local shortcut. Audio/image
cases still require native media proof. Local text is not native model-quality
evidence, and every case still needs the frozen-source and complete-accounting checks.
It reports oracle results separately. MockTransport cannot qualify as provider
evidence. Factual answer review remains required; the tool never declares semantic
qualification. Private traces/reviews can contain story details and stay in the
acceptance boundary; only aggregate counts should be sent to implementation.

The existing private secure launcher/freezer is still specific to public runs.
Acceptance must adapt and freeze its exact candidate, configuration, tooling,
bundle/answer/media identities, argv, caps and output; preserve root approval,
exclusive provider ownership and one-use STARTED enforcement before live use.
The worker itself does not supply that approval/ownership boundary. A new output
directory and final hashes preserve attempts but are not filesystem access control.
No blind request allocation exists and unused public allowance cannot transfer.
For root review only, a diagnostic ceiling proposal is 90 generation starts,
12 embedding starts and 1,800 outer wall seconds; these are ceilings, not a
prediction that all stories finish. Exhaustion preserves the partial result.

Provider-free structural verification uses temporary repeated generic records,
fake participants and MockTransport, never the actual private stories:

```text
python -B -m unittest -v evaluation.samsung_acceptance.test_blind
```

The narrow correction controls can be selected as
`evaluation.samsung_acceptance.test_blind.BlindCorrectionControls`; they use only
generic local-text, missing-native-media and observer-fault fixtures.

Preflight pins the externally recorded freeze hash, verifies every frozen byte
and the reused oracle source identity, rejects answer annotations in participant
payloads, exercises positive/negative synthetic trace controls, fully decodes
media, and checks the candidate media loader accepts identical bytes. Passing
preflight is not semantic accuracy. The reused trace oracle screens observable
calls, constraints, ordering and evidence; acceptance still needs factual review
of the actual answer, including unsupported extra claims and useful task completion.

At baseline `8abdf844cd5a72ab803fa1fd4d1bba506b3614e3`, the full frozen controller
run passed 2,880/2,880. The new 11-method suite passed seven and failed four
(two clarification races, fresh identical authorization, and the then-current
late-write notice expectation). This records the historical suite, before its
notice expectation was corrected to silent durable accounting.
Private holdout preflight passed, with zero participant/model holdout runs.
The owner report carries exact retained paths, hashes and command receipts.
