# Own-branch source audit — 25 September 2026

The fetched repository contains **113 refs, 102 unique commits and 90 distinct selected runtime/controller/test/build trees**. The earlier 68-group audit used a narrower directory selection. This audit found no evidence-backed reason to replace the migration base or automatically cherry-pick a historical branch tip.

Static selection and targeted source comparison are complete for the fetched relevant refs. All **113 refs / 90 selected tree groups** now have a targeted manual review or coverage through an exact inspected runtime identity. The review includes **64 historical patch commits**, plus final comparisons of the remaining **13 checkpoint/application trees / 26 refs**, which reduce to four exact Python runtime identities. Every distinct Python source blob under `participant/` and `thread_agent/` was also structurally read and AST-parsed without imports (120 blobs). **Zero fetched groups remain without targeted static review.**

This is not exhaustive behavioral qualification of every historical function, ancestor or ancillary file. The JSON records the exact files, comparisons and inheritance scope. Historical tests, builds, providers and device paths were not executed. The current FDB migration and its independent validation remain separate.

## Exact scope

| Coverage | Count / scope |
|---|---|
| Local heads | 102 |
| Remote-tracking refs | 11, including symbolic `origin/HEAD` |
| Actual named refs excluding symbolic alias | 112 |
| Unique commits | 102 |
| Exact selected-tree groups | 90 |
| Distinct runtime Python blobs structurally inspected | 120; no AST syntax errors |
| Targeted source patch commits | 64 |
| Selected groups reached by patch/lineage review | 90 / 90 |
| Final checkpoint/application groups / refs reviewed | 13 / 26 |
| Additional patches reviewed in this continuation | 48 |
| Exact participant/thread_agent Python tree identities | 64 |
| Groups lacking targeted static source review | 0, covering 0 refs |
| Fully behavior-qualified historical branch groups | 0 |
| Builds/tests/provider executions in this lane | 0 |

The selected tree includes `participant`, `thread_agent`, `android`, `web`, `tests`, `scripts`, `evaluation`, `theme5_kit`, `.github`, and root configuration/build/dependency files. Git object IDs preserve exact transitive tree identities; an additional SHA-256 fingerprint is computed from the sorted expanded path/mode/type/object list. Tests and build files can split otherwise identical runtimes, so 90 groups do not mean 90 materially different agents. `docs`, `reports`, `design`, `motion`, `proposals`, and root prose/media are excluded from this identity. Credential-like files were never opened.

The source base is `522f3f82ac7cec508eaa49297af638de6c674c63`. The current dirty FDB migration is recorded separately by selected working-file SHA-256 values; it must not be attributed to the committed historical base. The lane used fetched refs only and did not contact the remote, change a ref, create a checkout, or alter the original checkout. Remote freshness depends on the coordinator's previous fetch.

## Findings that affect the FDB path

1. **Late outcomes and duplicate notifications are already guarded.** `de48ae4d` prevents a late successful write from resuming a retired continuation; `c1599df5` prevents conflicting result notifications from repeating speech/effects; `18f18293` retains obsolete durable outcomes without stale responses; `f132eee1` retires expired continuations before result delivery. These protections are visible in the current `ParticipantAgent._result`, `_continue_result`, `_expire_writes` and existing controller tests. Different patch IDs do not prove missing functionality. Do not reapply whole tips.

2. **Do not restore the old cross-turn read cache.** `c8fb8283` added `_read_matches_current_slots` and completed-read reuse. `22787272` deliberately removed that reuse to require fresh reads across user turns. Equal tool arguments do not establish freshness of mutable service results. Preserve current freshness tests, and carry those requirements through the FDB bridge before treating reuse as a latency optimization.

3. **Task-scoped invalidation deserves an independent bridge test.** Current `ParticipantAgent._invalidate` marks every pending operation cancelled when input changes. Existing `thread_agent/engine.py` contains `result_current`, `invalidate` and `ensure_lookup`, which retain reads whose argument/media/domain dependencies still match. That engine is still organized around one current domain and is not a ready-made multitask solution. Its source is already present in the chosen base. Use it as a design reference, not a branch transplant. Author two-task controls: correcting task A must not cancel unrelated task B; changing A's dependencies must suppress A's obsolete result and continuation.

4. **The rapid-correction tests already exist; exercise the transport boundary.** `538d9687` adds a cancellation-resistant planner receiving three corrections, and `841d1d1c` adds a queued correction racing a stale read result and continuation. Their tests are present in current `tests/test_participant_controller.py`. Fresh FDB bridge/audio evidence remains separate. Useful additional coverage is the same race through `ControllerBridge.speech_started`, backend admission and actual speech output, including late completion after a timeout and a deadline/result tie.

5. **Keep current parsing and field-level authorization.** The reviewed patches `e2420f90` / `af87f444` reject duplicate JSON keys and incomplete provider output. `c2be24ca`, `7dd0249d`, `0e080879` and base `522f3f82` protect numeric fields, decimal boundaries, array recipients and bound container leaves. Current source contains those protections. Historical whole-command number/boolean helpers and narrow flight-audio grammar are not general FDB improvements. New provider routes should retain strict parsing and independently test exact FDB argument schemas against current permission boundaries.

6. **Camera branch work is already integrated by patch identity.** `git cherry` identifies the camera branch sequence ending at `14f7ad92` as equivalent to changes in the committed base. Its whole tree is older and lacks later controller/tests changes. Device execution and the current tethered extension remain separate evidence tasks.

## Concrete integration work supported by this review

| Suggested work | Historical source / existing code | Required proof |
|---|---|---|
| Bridge timeout → late success must reconcile once without a continuation | `de48ae4d`, `c1599df5`; `participant/agent.py`, `thread_agent/fdb3.py` | Independently authored blocking backend with actual call ledger; no second write, no stale speech |
| Bridge expiry/result boundary must not revive an action chain | `f132eee1`; `tests/test_write_deadline_race.py` | Controlled deadline/result ordering at the bridge; durable result retained, continuation retired |
| Scope invalidation to operation/task dependencies where required | Base `thread_agent/engine.py` versus `ParticipantAgent._invalidate` | Two unrelated concurrent tasks plus a correction; demonstrate which work survives and which must be rejected |
| Preserve strict current-source authority through FDB argument adaptation | `522f3f82`, `0e080879`, `c2be24ca`, `7dd0249d` | Independent supplied-value, correction, recipient and result-binding controls under native tool schemas |

These are follow-up implementation/test tickets, not measured advantages or instructions to copy old code. Some bridge controls already exist; inspect them before adding cases and add only missing boundary coverage. No cherry-picks are recommended by this audit.

## Evidence and remaining review

`own-branch-review.json` records every ref/commit/group, exact selected Git tree identities, runtime blob SHA-256 values, definition-level AST hashes and line locations, each group's diff hash and patch-equivalence evidence, selected current working-file hashes, targeted findings, and the preserved prior 26-ref gap list and its completed lineage reviews.

The structural inventory and targeted branch-selection review are complete for fetched refs. Behavioral, execution, device and latency qualification remain separate; this lane does not claim those gates passed. Any selected implementation still needs current validation under the coordinator's existing campaign and budget controls.


## Additional targeted review

The continuation manually read 48 additional historical `participant/` and `thread_agent/` patches. A reviewed group means its recorded runtime patch was inspected; it does **not** mean every ancestor, test, Android file, web file or build configuration was behavior-reviewed. The JSON records each reviewed commit, exact paths, patch SHA-256, stable source patch ID, ancestry/base patch-equivalence evidence, and a concrete finding. No historical code was imported or executed. Current migration changes continue independently and are not frozen by this report.

The 90 broader selected trees reduce to **64 exact Python runtime trees** when the selection is limited to `participant/` and `thread_agent/` `.py` entries. This is byte/object identity for that scope, not semantic equivalence or whole-application equivalence. Among the 48 additional patches, three duplicate source-patch pairs were found: `ca036f2a` / `197b6714` (missing-frame references), `aee8473d` / `a2d07f0f` (fresh-turn audio formatting), and `9562e1a6` / `b41aec65` (booking correction event boundaries). Different parent trees and ancillary files remain separately inventoried.

| Reviewed behavior | Concrete source evidence | Implication for FDB integration |
|---|---|---|
| Unknown/pending retry and expiry retirement | `f75b285a`, `c3eba579`, `ad1eccb7`, `0e170170`; `participant/agent.py` | Preserve later base guards across input encodings and retired continuations; earlier narrower variants add no demonstrated advantage. |
| Exact field authority | `8b60c6a5`, `4b192fc7`, `fc4c1362`, `7a1beaed`, `668fa9e0`; `participant/agent.py` | Enum validity, whole-command numbers, and tool-returned fields cannot replace source-bound authority. Keep later container safeguards. |
| Missing or replaced visual evidence | `09253c7f`, `0f78c732`, `a94a20ee`, `90f792ce`, `34f5616f`, `9b1593ea`, `26fb022c`, `eb569b0b`, `f3c211c9`; planner/media | Preserve unrelated text handling while blocking arguments and direct visual answers derived from an unavailable frame. Narrow natural-date conversion is distinct from inferring a missing target. |
| Audio corrections and source continuity | `df7bb84b`, `7069718b`, `6230310f`, `f8fe8099`, `203027f9`, `d1ed2578`; planner/controller | Bind retained observations to exact bytes, reject stale plans and stale epochs, and let either perception veto uncertainty. Historical flight grammar is not generic FDB permission logic. |
| Literal discovery and result provenance | `476caf04`, `d4e81178`, `084644c2`, `194a16fe`, `640e8660`, `fd24924f`; planner/controller/schema | Existing bounded discovery avoids a model roundtrip under exact contracts; it never grants the later write. Preserve source wrapper facts and distinguish printed-label recognition from user referent certainty. |
| Optional offline ASR lifetime | `3829985b`, `f4e9725b`, `29931c66`; `participant/local_asr.py`, planner | Hash-bound snapshots and offline pinned loading are useful existing patterns. Cancelling a future cannot stop an already-running inference thread; releasing the planner's model reference is not proof that resource work stopped. No ASR installation or execution was performed. |
| Camera send ownership | `56af274b`; `thread_agent/live.py` | Rechecking stream/token/input ownership under the same send lock is a useful existing admission pattern. Backend age/sequence/size checks and acknowledgements do not qualify the unreviewed Android path. |
| Clock and configuration limits | `7fe0f46d`, `cc7c9af6`, `88618d09`, `ebe6ddd8`; planner/controller/app backend | Do not restore a fixed 10 ms acknowledgement sleep as a substitute for shared clock epochs. Historical local-only configuration validation and temperature choices are source facts, not present provider-access or performance proof. |

The fixed 10 ms fence is absent from committed base and the inspected current `ParticipantAgent`. It was explicitly a small clock-skew workaround in the historical patch. The optional ASR adapter's single-worker busy guard is logical isolation within one process, not an operating-system sandbox. These limitations are relevant to cancellation/latency claims; they do not justify changing the frozen benchmark or enabling historical execution.

## Final checkpoint and application review

The final 13 selected trees covered five commit lineages but only four exact Python runtime identities. `e617a343` and `8abdf844` have identical runtime/app source; separate documentation and evaluation artifacts had inflated the apparent implementation count. Exact identity—not branch age or title—was used to share that review. The previous 26-ref gap list is preserved in JSON under `prior_remaining_review_snapshot`, and every affected group now points to the final lineage review.

| Lineage / representative | Files and behavior inspected | Base-selection conclusion |
|---|---|---|
| Archive `e617a343` / engineering `8abdf844` | Controller/planner/schema differences through `f45f0b17`; state visibility during correction, clarification suspension, cancellation-resistant planner deadlines, operation identity, audio authority, discovery and citation rendering. Packaging/configuration source changes were also read. | Earlier source lacks concrete protections retained by the base. Identical runtime code across archive/engineering refs supplies no competing implementation to adopt. |
| Submission checkpoint `f45f0b17` and audit descendants | Controller, authorization, media and planner differences to base: field-bound values, container/recipient authority, unsettled retries, expiry/continuation retirement, strict JSON completion, source hashes and missing-frame checks. | Replacing the base with this checkpoint would remove these inspected protections. No reusable missing runtime fix was found. |
| Published `main` (`62781833`, backend anchor `c284a3aa`) | Core app source identity; server protocol labels, browser setup guidance, absent top-level participant/submission files, and shared pre-camera Android delta. | Core app engine is shared. This branch omits the participant implementation; it is not an alternate FDB controller. |
| Embedded `master` (`13fa71ff`, backend anchor `b59cf79f`) | Comparison to main: a blank line in media code, Gradle wrapper checksum/URL validation removal, and older ignore/line-ending configuration. | No behavioral improvement. Do not restore the weaker wrapper verification or source configuration. |
| Shared camera additions in base | `CameraFrameGate.kt`, `LiveCamera.kt`, MainActivity/ThreadModel/ThreadUi changes, manifest/UI-probe changes, and gate/rotation unit-test source; Python send-lock ownership was reviewed earlier. | Existing base provides one-frame backpressure, source ownership, post-correction capture selection, permission/lifecycle checks and rotation handling. This static finding is not device-execution evidence. |

Branch-specific scripts and tests were inspected separately from shared runtime identity:

- `be7212c9` adds an uncertain independent-audio veto plus a positive clear-audio write control. `2035392c` tests renamed tools with selected-result bindings; `8323f254` tests nested returned identifiers and rejects guesses. **All three tests are already in the committed base and current test suite.** There is no missing-test transplant to recommend.
- `f06ac718:scripts/provider_route_probe.py` is an experimental transport adapter. Adapted audio becomes an ASR transcript supplied to planning; it also changes request formats and disables image embedding for adapted routes. Its call caps, partial-run flag and weights do not establish a native-model comparison or an FDB result. It was read, never invoked.
- `4d8fddcc:scripts/replay_public_trace.py` records three public-kit traces with source hashes and scores. It is a historical evidence helper, not an FDB runtime improvement, and was not run.
- `82a51b9c:scripts/render_participant_demo.py` verifies source/media hashes and renders explicitly edited mock-tool trace cards with original input audio. It labels film time separately from response time and records that it is not an app capture. It cannot substitute for a current live demonstration.
- Older packaging used recursive directory collection and a hidden prewarm override. The later checkpoint/base use an explicit file allowlist, reject symlinked parents/collisions, and verify the selected setup profile with synthetic mocked credentials. This audit only read that code; it did not open credentials or run package tooling.

`completion_lineage_reviews` contains **18 explicit comparison/file records**, with full commit IDs, selected paths, source or diff hashes, findings and `executed: false`. Ancillary changes unique to each of the 13 groups are recorded with that group. The report retains the previous 77-group checkpoint, so the final coverage does not erase how earlier limits were resolved.

**Confidence:** high for exact source identities, inspected differences and the conclusion that these lineages offer no demonstrated reason to replace the selected base. No claim is made that historical implementations passed tests or that every evaluation artifact, test, build script or device path was exhaustively audited. All 90 groups still lack fresh historical behavioral qualification in this lane. No historical code was executed, no provider was called, no ref or checkout was changed, and no cherry-pick is recommended.
