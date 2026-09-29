# Author-created Samsung challenge laboratory

**3,136 unique cases are authored and frozen. These are not Samsung official tests, alleged secret tests, or 3,136 successful model conversations.** The frozen catalogue separates 36 controller templates from 16 semantic/media templates. Related controller and semantic families share some underlying risks; the template count is not a count of statistically independent failure mechanisms.

| Evidence class | Development | Holdout | Total | Execution needed |
|---|---:|---:|---:|---|
| Controller, explicitly injected planner | 2,160 | 720 | 2,880 | Participant plus acceptance adapter; offline, zero provider calls |
| Text semantics | 60 | 20 | 80 | Actual planner/model with scripted tools |
| Audio semantics / input handling | 60 | 20 | 80 | Actual model and required MP3 input or specified invalid-file fixture |
| Visual semantics / input handling | 72 | 24 | 96 | Actual model and required PNG input or specified invalid-file fixture |
| **Total authored** | **2,352** | **784** | **3,136** | Never combine authored, executed, blocked, and passed counts |

Of the 176 audio/visual cases, **140 require newly captured media**, **32 stage deliberately missing/corrupt files**, and **4 reuse the unmodified official public image solely for media-root/cwd regressions**. New-photo/new-recording recipes are specifications, not acquired assets. Their semantics have not been executed by this lane. Human capture and content review must happen before they can enter a real-model denominator; the eventual bytes need their own immutable provenance manifest. A generated picture or TTS clip must be labelled synthetic if substituted and evaluated as a separate variant.

**Semantic execution update:** pre-provider review proved two v1 semantic fixture assumptions invalid: forced obsolete calls and an arbitrary unrequested result-row ID. `SEMANTIC_V2.md` documents the separate frozen correction for the same 80 text cases, with identical user stimuli and zero new independent cases. Use `semantic-v2/` plus `semantic_oracle_v2.py` for actual-model text runs. Original v1 corpus, oracle and strict evidence remain unchanged.

## What was frozen

`frozen/development.jsonl` and `frozen/holdout.jsonl` are deterministic canonical JSONL. `frozen/FREEZE.json` records their hashes, authoring source hashes, the UTC freeze time, and the holdout strategy. `frozen/COVERAGE.json` lists every family, obligation, count, mode, partition and factor axis. The first freeze was **21 September 2026, 07:54:27 UTC**.

The scoped `.gitattributes` preserves LF bytes for the corpus and hashed authoring sources, including Windows checkouts. Copy frozen files as bytes; newline conversion invalidates their hashes.

Controller variants combine **five different tool/schema structures**, **four planner/result schedules**, and **four meaningful constraint, type, selection, or authority profiles**. The domains include public flight shapes and unfamiliar room, parcel, service and inventory schemas. Other families deliberately vary nesting depth, scalar/array/object errors, duplicate/error ordering, candidate cardinality, authority context and outcome certainty. Timings and values are variants, not new families. Runtime fingerprints exclude case ID, partition, description and oracle; all 3,136 stimuli remain distinct after those labels are removed.

Profile 3 is held out across every family. This reserves parameter/schema/condition compositions and new media requirements from the production owners before first evaluation. The author is independent of production implementation, but the holdout shares generator templates with development data; it is **not a statistically independent human conversation set**. Isolation is procedural on the shared filesystem. Production owners received family expectations and three development examples before freeze; no held-out answer rows were sent. Acceptance may inspect and execute the holdout only after recording a frozen candidate. Later use becomes regression evidence and must be labelled that way.

## Coverage and actual contracts

The official kit's raw dictionary events, action names, nested tool-result envelope, effect tags, five argument types and enum conventions are retained. `CONTRACT.md` specifies the external test adapter boundary. Cancellation surviving in-flight backends, duplicate/contradictory results, malformed events, missing kind tags and hostile planner outputs are explicitly **author-created robustness extensions**; they are not claims that the official public harness delivers those faults. Recursive schema validation is deliberately stronger than the official mock's shallow validator, and accepts declared optional empty strings, false, zero and empty arrays. Boolean values are not numbers; numerically equivalent integer/float enum values are accepted. Python-only boundary checks cover nonfinite values and very large integers without writing invalid JSON into the corpus.

The catalogue covers correction chains and retained constraints, planner cancellation resistance, stale result exclusion, repeated responsiveness, lifecycle and six-second tail, arbitrary nested schemas, missing required values, quoted/negated/hypothetical and revoked authority, single-utterance chains, one grant versus two distinct effects, forged result bindings, bounded read retry, unknown write outcomes, duplicate IDs/results/writes, grounded finals, real-media provenance, image replacement and citations, tool/image prompt injection, and media-root/cwd behavior.

The injected planner supplies complete snapshots, decisions and optional continuation steps through the exact agreed `setup/plan/close` interface. This tests whether the controller enforces and executes those proposals. It does **not** prove that the real planner can infer those snapshots, recognize corrections, transcribe audio, or ground vision. Semantic cases contain no injected plans and runtime audio/frame events contain no transcript, caption, annotations, reference answers or fake embeddings.

## Reproduce the author's checks

From a checkout containing this directory, Python 3.11's standard library is enough:

```powershell
python -m unittest tests.test_samsung_challenge_corpus -q
python -m evaluation.samsung_challenge.generate
python -m evaluation.samsung_challenge.selfcheck --out evaluation/samsung_challenge/evidence/new-selfcheck
```

Generation verifies existing frozen bytes and refuses to overwrite a changed freeze. `selfcheck` likewise requires a new output directory. The 12 unittest methods include subtests for every case and every eligible negative control; report the explicit case/mutation denominators, not 12 model tests or thousands of independent unit-test methods.

The original self-check output is retained in the local archive. The command above creates a fresh record of every synthetic positive witness and negative-control outcome plus source/corpus hashes. A witness is a hand-assembled trace derived from the authored story, not a participant run. Negative controls remove cancellation, delay cancellation, omit snapshots, reuse IDs, corrupt arguments, duplicate writes, invent evidence, act on forbidden requests, emit after the tail, or pretend to read media. Silent agents must fail every case; always-clarify and expected-text-only agents must fail every case that actually requires a tool. Always clarifying is correctly allowed on cases whose stated task really requires clarification.

## Execute the participant separately

The acceptance lane owns `evaluation/samsung_acceptance/adapter.py`. Run it after integrating that file; the challenge author does not maintain a second participant executor. This command records all selected rows, blocks non-injected rows explicitly, verifies the sibling freeze hash, verifies imports point to the requested candidate, records before/after source hashes and preserves every trace:

```powershell
python -m evaluation.samsung_acceptance.adapter --candidate '<candidate-root>' --kit '<unchanged-kit-root>' --cases evaluation/samsung_challenge/frozen/development.jsonl --oracle evaluation/samsung_challenge/oracle.py --partition development --out '<new-evidence-directory>'
```

The adapter's clock is a **synthetic discrete-event schedule** with production clocks unmodified. It exercises queue ordering, cancellation and result handling, but cannot establish real 800 ms responsiveness, wall-clock provider timeout behavior, six-second compute feasibility or audio/vision accuracy. Its `--settle-turns 20`, `40` and `80` settings can check scheduler sensitivity; changing this setting must be recorded. The unchanged official harness at time scale one remains the timing/real-model acceptance path. Do not run a 3,136-request cloud sweep.

The freeze includes `scenario_end_tail` cases where replies arrive 5.3–5.8 seconds after the call. `tail_ms=6000` is a fixture parameter, and `scenario_end` is an explicit scheduled event. Missing lifecycle/media telemetry fails its obligation instead of inventing a successful observation. Acquisition requirements that cannot be met are blocked, not false or true semantic results.

## Interpretation limits

The trace oracle checks observable effects, schema validity, ordering, snapshots, IDs, selected evidence and specified response content. Text checks intentionally allow several safe uncertainty phrases and validate evidence before the response, but they are not a complete natural-language truth or quality judge. The image cases require real asset access and actual returned document/page evidence; access alone is not visual understanding. No nonempty vector earns a claim of genuine embedding quality, and this corpus does not claim that optional bonus.

False positives must be adjudicated in a new evidence record with the original strict result retained. Do not alter a frozen oracle after seeing an agent fail. A test-design defect merits a new version and an explanation, not a silent improvement of reported performance. `SOURCE_LOCK.json` records the supplied kit/audit files used to author these obligations; no scenario or annotation is read by production.
