# Samsung participant package

This is the submission-specific entry path: `participant.agent:ParticipantAgent`.
The browser/Android product, its root `requirements.txt`, and its root `Dockerfile`
are separate. The official participant runs in the evaluator's Python process,
with queues; it does not start the app server or a JSON-over-stdio adapter.

`submission.yaml` intentionally identifies the team as
`LOCAL_DRAFT_TEAM_METADATA_REQUIRED`. The supplied validator accepts any nonempty
team string. Passing that check does not establish registration or final identity.
This local engineering package has not been pushed, tagged, published, or submitted.

This is the **candidate-009 post-run companion documentation** for the source
identified in [EVIDENCE.md](EVIDENCE.md): restored planner `59956ec7...`.
It retains candidate-008's original audio request/schema/guidance/merge and adds
the reviewed image normalization, capability catalogue, and five-second setup
ceiling. The owner records 49 passing methods, eight request-body equivalence
controls, and 21 restoration checks. The restored source's root regression passed
732 methods, and both peers completed their limited restoration reviews. Frozen
candidate-009's own verifier and all 105 focused methods passed on clean Python
3.10.20, 3.11.9, and 3.12.13: **315 new focused executions and three new packaged
verifier runs**, with prewarming disabled and zero external network attempts.
The completed public batch **failed acceptance**: **62.6 official weighted score,
6/27 mandatory passes, and 4/27 full passes**. The six mandatory passes came from
the two local routes; none of the 21 provider-dependent attempts completed its
task. The frozen directory and ZIP retain their original freeze-time
documentation; these updated companions are separate.
The withdrawn `0f937fce...` audio experiment, its 738-test result, and its failed
real-media screen remain historical.

## Runtime and installation

Use Python 3.10, 3.11, or 3.12. The manifest selects 3.11. Install the ten exact
pins in `requirements-submission.txt`; the same pins appear in `submission.yaml`.
HTTPX, python-dotenv, and Pillow are direct dependencies. The other pins are their
transitive requirements, including exceptiongroup for Python 3.10. It is installed
on all three versions so the kit's minimal YAML parser needs no version markers.
An initial Python 3.10 deadline-API failure was reproduced and corrected by the
model owner; the evidence distinguishes that failed snapshot from later checks.
All packages resolve from public PyPI. Pillow validates image files without
changing their contents. MP3 bytes go directly to the multimodal model. No local
checkpoint, GPU, audio decoder, app dependencies, or private package index is required.

From an integrated checkout on Windows PowerShell:

```powershell
py -3.11 -m venv .runtime/submission-venv
& .runtime/submission-venv/Scripts/python.exe -m pip --isolated install --index-url https://pypi.org/simple -r requirements-submission.txt
& .runtime/submission-venv/Scripts/python.exe -m pip check
$python = (Resolve-Path .runtime/submission-venv/Scripts/python.exe).Path
$kit = 'C:/absolute/path/to/unchanged/participant-kit'
& $python scripts/verify_samsung_submission.py --kit $kit --submission . --out .runtime/submission-offline.json
```

On Linux or macOS, create the environment with `python3.11 -m venv .runtime/submission-venv`
and use `.runtime/submission-venv/bin/python` for the equivalent commands.
The supplied `eval_submission.py` prints declared requirements but does **not**
install them or enforce the Python/env fields. A successful import in an existing
development environment is therefore weaker than the clean checks recorded in
[EVIDENCE.md](EVIDENCE.md).

## Credentials, model, and media paths

Register the **name** `SECRET_GEMINI_API_KEY` through the organizer's credential
mechanism for judged runs; keep its value out of source, archives, and reports.
The planner uses Google's hosted Gemini REST API directly, with the exact default
model `gemini-3.5-flash-lite`. It does not route decisions through a team server.
Outbound HTTPS to `generativelanguage.googleapis.com` and suitable provider quota
must be available in the judge environment; that organizer-side access is not
proved by a local successful run.

Optional local configuration:

| Variable | Purpose |
|---|---|
| `PARTICIPANT_MODEL` | Explicit model override; report any override with results |
| `PARTICIPANT_THINKING_LEVEL` | `minimal` by default; also accepts `low`, `medium`, or `high` |
| `PARTICIPANT_IMAGE_EMBEDDING` | `1` by default; `0` disables the optional current-image `gemini-embedding-2` request; eligibility is described below |
| `PARTICIPANT_PREWARM` | `1` by default; `0` disables the bounded read-only model metadata GET during setup |
| `PARTICIPANT_MEDIA_ROOT` | Absolute base directory containing referenced media |
| `PARTICIPANT_ENV_FILE` | Explicit local `.env` file; never copied into the package |
| `PARTICIPANT_TIMEOUT_SECONDS` | Planner deadline, default 4.5 seconds, allowed range greater than 0 and at most 5.5 |
| `THREAD_API_KEY`, `THREAD_MODEL` | Legacy local compatibility; avoid conflicting values |
| `THREAD_PROVIDER` | If set, must be `gemini`; no silent provider fallback |

Audio turns use a parallel acoustic check with a 3.5-second cap inside the total
planning budget (4.5 seconds by default).

Candidate-009 restores candidate-008's original audio behavior. Every current
clip's raw bytes still go to both main planning and the independent acoustic
request, and both responses require full transcripts. The original guidance
preserves ordered clips, hesitations, and self-corrections. The checked acoustic
transcript replaces the main transcript during the existing merge, with boolean
uncertainty combined conservatively. Acoustic failure or current uncertainty
still prevents an effectful plan. Uncached historical audio keeps its original
main-request transcript requirement. The schema, request construction, acoustic
path, merge, and prior-turn cache behavior match the candidate-008 baseline.

The proposed main-transcript omission and its separate current-audio guide were
withdrawn after an experimental two-input, four-call screen produced an acoustic
timeout and a confident Boston proposal unsupported by the acoustic transcript.
No effects were executed. That experiment is disclosed in `EVIDENCE.md` under
its own source identity; it is not part of this candidate. Restoring the earlier
audio path does not prove an ASR fix: both model phases still depend on
self-reported clarity. In candidate-009's public batch, no ambiguous-audio attempt
obtained a successful current-confirmation response, and all three two-clip
correction attempts reached the acoustic deadline. The returned responses and
remaining evidence limits are recorded separately in `EVIDENCE.md`.

The runtime retains the private, in-memory audio cache introduced in
candidate-008. After a completed plan, it may retain the checked transcript and
conservative uncertainty flag under the exact message index,
message revision, MIME type, and source SHA-256. Every referenced audio file still
passes through the normal media read, validation, and hash calculation before
reuse is considered. Only matching audio from before `current_turn_start` can be
replaced in a later provider request by that private cached observation. A
filename or a controller-supplied observation alone cannot establish a cache hit.
The trace records reused source identities in `reused_audio`.

All current-turn raw audio is retained, including multiple clips within the same
turn. Cache entries come only from a completed outer planning call; cancelled,
failed, or timed-out calls do not commit them. Reuse preserves uncertainty, and a
previously true uncertainty flag stays true for the same cache key. Closing the
planner clears the cache. This change introduces no dependency or configuration
flag. The historical candidate-008 public batch observed this reuse and actual
Boston results in all three ambiguous-audio attempts. Each second main request omitted
98,304 previously checked raw bytes while sending the current clip. Those runs
establish the changed input shape and task outcomes, without isolating a causal
latency improvement. Candidate-009 observed one verified prior-clip reuse in
public case 05; its current confirmation then failed the acoustic check, so that
attempt did not complete. The cache does not apply to public audio case 06, whose two
clips are both current-turn input. The 3.5-second acoustic and 4.5-second default
planning budgets remain unchanged. See [EVIDENCE.md](EVIDENCE.md) for the clean
offline checks, measured results, and remaining failures.

Candidate-008 also introduced a narrow local path for a completed literal
`flight_search` request. It requires exactly one fresh, finished text message,
empty intent/slots, and no prior actions, tool results, observations, planning
error, or image context. The command grammar accepts a simple find/search request
with a single destination token or a quoted multiword destination. Split speech,
history, recognized references, dates, extra constraints, and unsupported syntax
defer to the general planner. Its command vocabulary and reserved-word list are
finite; it performs no independent place validation and does not establish that
every accepted name denotes a real place.

The offered tool must be the documented read-only `flight_search`, with a
compatible live argument schema: required string destination, at most an optional
string date, compatible metadata, and a destination enum that accepts the value
when supplied. Supplied result-shape metadata must also be compatible. A local
match proposes the normal read-only call; the controller still performs its
usual validation, dispatch, cancellation, bounded retry, and result handling.
Flight identifiers, departures, and prices in the final response come from the
actual delivered result. Other tool names and unmatched requests use the general
planner.

The local path records `phase=local_planning` and
`rule=documented_flight_search` without a generation request for that decision.
The configured-key and setup contract remains: default `PARTICIPANT_PREWARM=1`
can still make the separate metadata GET described below. No generation for a
local decision is not a claim of zero provider requests. In candidate-008's three
historical public read-retry attempts, this rule produced the initial read, one
retry after the actual error, and a final grounded in the returned Seattle option. Those
attempts had no generation/acoustic records; their successful setup metadata GETs
remain provider activity. This establishes the recognized subset with those mock
tool delays, without establishing general text understanding or a universal
latency improvement. Candidate-009 again completed all three read-retry tasks
through this local route: 3/3 mandatory and 2/3 full passes. One otherwise complete
attempt failed the unchanged nominal-event timing check.

Candidate-009's integrated additional local rule answers a finite set of exact,
fresh tool-list or general-capability questions, such as "What tools are
available?" or "What can you do?" It requires the same fresh finished-text and
empty-context boundary as the literal flight-search rule. Extra task meaning,
history, media, or unmatched wording defers to the provider planner.

Tool-list answers use the actual runtime tool names, kinds, and required/optional
argument names. Broader capability answers additionally require a nonempty,
displayable supplied description for every offered tool, which is quoted as
supplied metadata. Its trimmed length must be at most 160 characters, and control
characters and the specified markup delimiters are rejected. Missing or
unsupported metadata falls back to provider planning. Broad capability questions
also defer when the tool manifest is empty. An explicit tool-catalogue request
with an empty manifest reports that no tools are available. The route limits the
catalogue to 32 tools, each with at most 32
arguments, and the complete response to 4000 characters; identifiers and
descriptions must pass its display checks. The existing completion-claim guard
still applies. This
route returns no tool calls, invented results, or completion claims. Its trace is
`phase=local_planning`, `rule=runtime_capabilities`; the configured-key/setup
contract and separate metadata GET remain. Candidate-009's public capability case
returned all five actual runtime tools with their descriptions in all three
attempts: 3/3 mandatory and 2/3 full passes. One immediate answer preceded the
nominal event timestamp and failed the unchanged timing check. This verifies the
recognized question with the supplied manifest; it does not establish general
no-tool understanding. Owner and peer mock evidence retain their separate source
identities and counts.

Candidate-009's integrated image-text normalization still requires `visible_text`
to be a list containing only strings. Within a valid list, it removes entries
with no Unicode alphanumeric character, such as blank strings or symbol-only
noise. Retained strings keep their original text, spacing, and case; a readable
label is not rewritten into another connector name. A printed-text citation must
still match a retained label and the actual named result record. This checks
internal consistency of provider-reported observations, without independently
proving that an image was read correctly. Candidate-008's rejected raw image
observation was not retained, so this change has no demonstrated causal link to
that failure. All three candidate-009 public visual main requests timed out before
returning an interpretation, lookup, or final answer, so live validation of this
normalization was not meaningfully reached. Their three embedding records stayed
`pending`; completion, attachment, and bonus eligibility were not established.
The peer checks also retain two existing limits: `explicit_target` and
`non_visual` can accept a normalized empty list because those declared bases are
not independently verified. Discarded text cannot supply a printed-text target
or a write grant.

Optional image embedding uses the same
HTTP client and secret and adds no package dependency. When enabled, it starts a
separate API request only if a validated current image is available and at least
one offered tool explicitly declares `image_embedding` as an array of numbers.
Planning attaches a vector only when it is already ready, its input SHA-256
matches that image, and the selected tool declares that argument. Trace evidence
records the tool names in `attached_to`. Planning does not wait for the optional
vector; an unfinished embedding request is cancelled.

Without an explicit media root, setup captures the current working directory.
Run the evaluator **from the package/kit root**, where `audio/` and `frames/` live.
The official runner forwards relative references unchanged and does not change
cwd when importing an external submission. For a different cwd or separately
mounted kit, set `PARTICIPANT_MEDIA_ROOT` to the actual media root. Do not infer it
from a scenario filename or inspect scenario annotations.

Construction must work outside an active event loop and makes no network request.
With a configured key and the default `PARTICIPANT_PREWARM=1`, async `setup()` makes
one read-only `models.get` metadata GET for the configured model, using the same
HTTP client as later planning. Candidate-009's integrated outer warm-up ceiling is
5 seconds, increased from candidate-008's 2 seconds. The HTTP client's timeouts
remain tied to `PARTICIPANT_TIMEOUT_SECONDS`: connect is the smaller of 2 seconds
and that setting; read/write/pool use that setting (4.5 seconds by default).
The outer ceiling does not override an earlier HTTP timeout. HTTP errors and
timeouts are best effort; there is no generation, retry, or fallback request.
Setup cancellation still propagates. The trace counts this separately with
`phase=warmup` and `method=GET`; it is not a generation request, and no latency
improvement is guaranteed. In candidate-009's public batch, all 27 attempt warm-ups
returned HTTP 200 in 234–1219 ms (median 297 ms), below the old two-second ceiling.
The extra allowance was never used beyond that old cap, so this batch shows no
benefit from increasing it. Setup ran before the scenario clock. Set
`PARTICIPANT_PREWARM=0` to disable it.

The kit allows 300 seconds for setup and 120 seconds for the scenario wall cap,
but only a 6-second tail after
the final user event. `scenario_end` closes user input while tool results can still
arrive. The runtime must remain alive until harness cancellation.

## Build a candidate without modifying the external kit

```powershell
& $python scripts/package_samsung_submission.py --kit $kit --source . --output .runtime/candidate-001
& $python scripts/verify_samsung_submission.py --kit $kit --submission .runtime/candidate-001 --out .runtime/candidate-001-offline.json
```

The output directory and sibling ZIP must not already exist. The ZIP is a kit root
when extracted, with `submission.yaml` at its root. ZIP entry ordering, timestamps,
and permissions are fixed; identical source/kit bytes and Git revision produce an
identical archive in the same Python/zlib environment. The builder immediately
checks ZIP CRCs, byte round-trips, and unchanged upstream file hashes.

The allowlist includes all Python modules under `participant/`, the submission
manifests, the two packaging scripts, and `docs/submission/*.md`. It preserves the
kit's README, walkthrough, harness/scorer, reference agent, scenarios, docs, and
MP3/PNG assets byte-for-byte. Only the kit's example `submission.yaml` is replaced.
`PACKAGE_MANIFEST.json` records each member's SHA-256, all retained upstream hashes,
the original example manifest hash, and the source Git revision. Actual file
hashes identify uncommitted changes; a Git revision alone does not.

Official scenarios necessarily contain evaluator annotations. They remain
evaluation inputs outside `participant/`; the participant runtime must never read
them. Authored challenge cases, holdouts, app files, local `.env` files, caches,
credentials, and historical reports are not packaged. The builder rejects
symlinks and obvious private-key/Gemini-key bytes, but that limited scan is not a
substitute for reviewing what is released.

## Official evaluation

Acceptance owns the final cloud runs and their complete traces. After loading the
authorized credentials into the environment, from the generated candidate root:

```powershell
& $python eval_submission.py . --reps 3 --time-scale 1 --out ../candidate-001-official.json
```

The official command imports `participant.agent:ParticipantAgent` using the
manifest and applies its unchanged scorer. Preserve every attempt. Inspect task
completion, cancellation, tool arguments, grounded finals, and state snapshots;
an aggregate score alone cannot establish that all intended tasks worked. The
offline verifier uses an injected controller test planner, then executes the real
`Planner.plan()` and PNG ingestion with an in-memory HTTP transport and a synthetic
provider response. It also checks rejection of synthetic late replies after
cancellation or deadline expiry, making no cloud calls. The verifier explicitly
sets `PARTICIPANT_PREWARM=0` and records that override in its JSON report while
blocking external sockets and DNS. Its admission and planner checks therefore
exclude production metadata prewarming; dedicated model-owner tests cover that
path through a mock transport. This establishes packaging/lifecycle behavior,
not model accuracy, latency, official
public-case success, or hidden-test performance.

Candidate-009's completed acceptance batch on 21 September 2026 ran all nine
unchanged public cases three times at time scale 1, using clean Python 3.11.9,
`gemini-3.5-flash-lite`, minimal thinking, prewarming enabled, and image embedding
enabled. It recorded **62.6 official weighted score**, **62.2 plain average of
case medians**, and **6/27 mandatory and 4/27 full passes**. The individual-attempt
mean was 59.726. **The acceptance gate failed.** The local capability and read-retry
routes each completed 3/3 tasks; each lost one full pass to the unchanged nominal
timing rule. All 21 provider-dependent attempts failed task completion. Some
provider responses did return, so that failure is not a claim of zero HTTP 200s
or zero usage. All attempts and their original scores remain in the denominator.
The authoritative results, media limits, provider accounting, and hashes are in
[EVIDENCE.md](EVIDENCE.md).

Two later isolated latency diagnostics returned HTTP 200, and a separate four-arm
transport comparison was mixed (cold 2/2 successes, warm 1/2). Both diagnostics ran
in the development environment. They neither reran public acceptance nor establish
recovery, a cause of the public failure, or a warm-up fix.

The historical candidate-008 acceptance batch on 21 September 2026 ran all nine
unchanged public cases three times at time scale 1. It recorded **94.0 official
weighted score**, **95.2 plain average of case medians**, and **22/27 mandatory
and 22/27 full passes**. The individual-attempt mean was 91.281. The full
acceptance gate failed: one booking had no receipt, one no-tool request
timed out, two audio-correction attempts did not complete, and one image response
failed validation. The authoritative evidence paths and qualifications are in
[EVIDENCE.md](EVIDENCE.md).
Frozen candidate-008 and its ZIP remain unchanged, including their original
freeze-time documentation. Candidate-009's new clean focused execution and own
packaged-verifier checks passed on all three supported Windows interpreters;
those offline results are separate from its failed public gate. The sequential
candidate-008/009 results do not isolate a cause for the decline.

## Optional container path

The image contains only the participant runtime and offline verifier. Supply the
unchanged kit as a read-only bind mount. These commands describe the intended path;
see the evidence file for whether this host actually ran it.

```sh
docker build -f Dockerfile.submission --build-arg PYTHON_VERSION=3.11 -t samsung-participant:local .
docker run --rm --network none --mount type=bind,src=/absolute/kit,dst=/kit,readonly samsung-participant:local
```

For a real cloud run, enable network and inject `SECRET_GEMINI_API_KEY` from the
host's already-set environment; do not put the value in a command, image, or file:

```sh
docker run --rm -e SECRET_GEMINI_API_KEY -e PARTICIPANT_MEDIA_ROOT=/kit --mount type=bind,src=/absolute/kit,dst=/kit,readonly -w /kit samsung-participant:local python /kit/eval_submission.py /opt/submission --reps 3 --time-scale 1
```

## Remaining external prerequisites

The current phase intentionally leaves registered team/institution metadata as a
draft. Before a separately authorized final release, reconcile the registered
identity, Theme 05 selection, final-form access, hosted-model/network/secret route,
and the organizer's media-root guarantee. The supplied Theme 5 guide remains
DRM-wrapped in the received archive; request a readable copy or clarification.
The general deliverables also require the final deck/demo/disclosure and matching
source/evidence references. This package does not fulfill those by implication.
