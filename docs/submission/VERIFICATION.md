# Release verification

**Historical 30 September package verification.** The counts, hashes and “current” client/media descriptions below refer to that package, not the changed 3 October candidate. Final-source results and checks are in [RESULTS.md](RESULTS.md). Earlier checks are retained, not reassigned to new code.

The release checks exercise source, installation, clients and packaged assets separately. The previously published `THREAD-1.0.0-evidence.zip` contains commands, logs, failed attempts, source hashes and receipts for that release. `RELEASE-MANIFEST.json` binds those published assets to the tagged commit; `SHA256SUMS.txt` verifies their bytes. **The S2 supplement below is local-only and is not claimed to be inside those unchanged published archives.**

## S2 Linux full-100 supplement — 3 October 2026

Measured source: **`8ef5b590a949586a4661df7e250bc7f62769acc4`**, derived from requested base `5191ea5` on an isolated branch. No newer moving-release changes were silently included. The final documentation/evidence commit changes no measured runtime files.

| Check | Actual outcome / source | Scope |
|---|---|---|
| Clean source archive | 903 members; no Git metadata, private state, credentials or generated caches; tar SHA recorded | Exported to the Linux filesystem before execution |
| Latest preparation | `prepare-006`, exit 0, `PREPARED_ONLY`, source `8ef5b59` | Separate new work directory; not counted as inference |
| Real one-command full run | `full-003`: 100 found, 100 completed, 100 evaluated; strict **61/100** | WSL Ubuntu 24.04, CPython 3.11.16, RTX 4050 6 GB; local Qwen judge |
| Script's own verifier | `complete=true`, `judge_verified=true`, `qualification_eligible=false`; exit **1** | Complete with strict non-passes; not official organizer qualification |
| Stage execution | Inference, tool evaluation, pass evaluation, latency: **all exit 0** | 100 closed sessions and zero recorded session errors |
| Checked judge evidence | 218 tool + 111 pass requests, all successful | Local endpoint only; no pending/error receipts |
| Additional latency judging | 95 logical calls; 100 analyzed, 0 skipped/failed | No checked-wrapper receipts; four negative local-judge completion estimates retained |
| Upstream integrity | Tracked files unchanged before/after; pinned `3e799c45a045256f47d5f1c9cda90157e2d2ec9e` | No grading/tool semantics changes; final source snapshot has zero hash mismatches |
| Requested Windows base suite | **1,891 passed**, 385.852 s, source `48fb504` | No failures/errors/skips; later runner changes are separately tested |
| Actual LiveKit SDK suite | **102 passed**, exit 0, 41.468 s, source `48fb504` | Dependency-complete Linux environment; earlier environment/fixture failures preserved |
| Final runner suite | **31 passed** on Windows/Git Bash (9.384 s) and native Ubuntu source export (6.541 s), source `8ef5b59` | General asset retry, identity, stdin and UTF-8 regressions plus existing guards |
| Resource cleanup | Owned GPU services exited; lock released 15:29:04 UTC | No Windows llama-server observed; no unrelated process killed |

Full-run wall time was **7,046 seconds**. Host-wide one-second GPU sampling observed **5,817 MiB used**, **104 MiB minimum free**, and **100% peak utilization**. Task-owned model/package caches and the permitted exact-hash prior llama build were explicitly reused; fresh environments, LiveKit download/verification and all 100 inference recordings ran in a new directory. This is not a newly built or completely cache-free organizer machine test.

The [S2 report](../fdb3/LINUX_QUALIFICATION_20261003.md) preserves all preparation/full-run attempts and explains the general repairs. The [curated aggregate/hash receipt](../fdb3/evidence/s2-linux-qualification-20261003.json) binds final outputs; originals remain under `/opt/thread-linux-qual-20261003/` and exact core copies in this worktree's private `.thread-run/evidence/S2-20261003-final`. Full attempts 001/002 were aborted and remain incomplete; no partial outputs contribute to full-003. AI assistance is disclosed in the report. No release assets, APKs, human forms or hosted services were published or changed by S2. **Spend: INR 0.**

## Historical release checks (before S2)

| Scope | Result | What it establishes |
|---|---|---|
| Complete provider-free Python suite | 1,891 passed; no failures, errors or skips | Controller, host, protocol, cancellation, authorization and regression behavior |
| Real LiveKit SDK suite | 102 passed; no failures, errors or skips | Adapter behavior against the installed SDK |
| Reproduction guards | 22 passed on Windows/Git Bash and 22 on native Ubuntu | Configuration, explicit seed, shell failure paths and source-archive identity |
| Windows launcher, readiness and recognizer controls | 24 passed | Local launch arguments and pinned asset checks |
| Legacy YAML/package and Gemini configuration | 25 passed | The preserved queue-kit manifest, participant entry point and packaging controls |
| Clean Linux source-export preparation | Passed in a new Python 3.11 environment | Dependency consistency, pinned model assets, all 100 input hashes, 12 public tools, speech backend and agent CLI |
| Clean Linux evaluator installation | 225 hash-locked packages installed; dependency consistency passed | The actual evaluator dependency set installs, rather than only resolving |
| Offline evaluator runtime checks | NeMo ASR import and four upstream CLI checks passed | Installed runtime imports with networking disabled; no model or GPU inference claimed |
| Android | 11 JVM tests, 10 device tests and minified-release navigation smoke passed | History recreation, checklist behavior and application entry points on the emulator |
| Browser | 21 store assertions, 12 transport assertions, 72 workspace checks; audio suites passed | Client persistence and lifecycle behavior, including the closed-socket admission regression |
| Current local extension | One native turn and one browser-module turn passed | Two actual checklist writes, durable receipts and returned speech PCM |

The full Python/SDK suite was followed by the documented seed, dependency-lock and source-export repairs. Targeted reproduction tests cover those later changes. The evidence retains the exact source identity for each invocation; it does not silently assign earlier tests to a later tree.

The clean Linux clone's seven audited upstream files match commit `3e799c45a045256f47d5f1c9cda90157e2d2ec9e` byte for byte. An older Windows checkout has CRLF-only differences, recorded separately. No grading-code modification is hidden by normalizing that comparison.

The first hosted Windows CI run exposed a fixture-path mismatch: its temporary directory used a DOS short name while the launcher returned the equivalent canonical long path. Both fixtures now use the same canonical root invariant as production. Exact location checks, outside-root rejection, existing-file rejection and marker preservation remain asserted. This changes no production behavior or grading expectation. The original CI failure is retained in the release evidence.

## Package and media identity

The APK contains a per-file manifest for all 30 embedded Python source files. The release build was installed and pulled back from the emulator with an identical checksum. Its existing development certificate verifies; this is not production Play signing or a physical-device test.

The browser archive includes all 27 web assets, selected documentation, notices and tests. Its manifest records file hashes and the deliberate conversion of links to documents outside the bundle into links to the same Git tag. ZIP integrity and local documentation links were checked.

The presentation contains eight slides. Export and re-import validation passed, and every final slide was visually inspected. The original shared team presentation is preserved. The three-minute v3 launch film is unchanged and decodes completely. The separate 3:10 recorded demo retains original evidence audio, with its source revisions and edits disclosed in [media provenance](media/README.md).

## Historical release scope and resource boundaries

The new live checks used typed input, four local planner generations, 8,940 prompt tokens and 160 generated tokens. They performed two actual writes during a 249.609-second owned GPU window. Browser UI automation was unavailable: its live check used the actual client module with a disk storage adapter. Native playback used AudioTrack. Neither establishes physical microphone or acoustic behavior.

The evaluator installation consumed about 6.48 GiB of additional Linux filesystem space. Observed cumulative network receive traffic was at most 3.33 GiB, including earlier traffic in the measured environment. It completed within the declared 20-minute and 10-GiB limits. Offline checks loaded no ASR model and ran no recordings. Incremental billed usage was ₹0.

These historical release checks did not establish a fresh final-source 100-recording score. The separate S2 supplement above now establishes one complete local Linux measurement at `8ef5b59`; neither establishes three frozen 100/100 runs, a complete organizer-hardware GPU rerun or a signed human disclosure. Read [results](RESULTS.md) and [requirements](REQUIREMENTS.md) for those explicit boundaries.
