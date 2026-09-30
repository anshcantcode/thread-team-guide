# Release verification

The release checks exercise source, installation, clients and packaged assets separately. The downloadable `THREAD-1.0.0-evidence.zip` contains commands, logs, failed attempts, source hashes and receipts. `RELEASE-MANIFEST.json` binds the published assets to the tagged commit; `SHA256SUMS.txt` verifies their bytes.

## Executed checks

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

## Scope and resource boundaries

The new live checks used typed input, four local planner generations, 8,940 prompt tokens and 160 generated tokens. They performed two actual writes during a 249.609-second owned GPU window. Browser UI automation was unavailable: its live check used the actual client module with a disk storage adapter. Native playback used AudioTrack. Neither establishes physical microphone or acoustic behavior.

The evaluator installation consumed about 6.48 GiB of additional Linux filesystem space. Observed cumulative network receive traffic was at most 3.33 GiB, including earlier traffic in the measured environment. It completed within the declared 20-minute and 10-GiB limits. Offline checks loaded no ASR model and ran no recordings. Incremental billed usage was ₹0.

These checks do not establish a fresh final-source 100-recording score, three frozen 100/100 runs, a complete organizer-hardware GPU rerun or a signed human disclosure. Read [results](RESULTS.md) and [requirements](REQUIREMENTS.md) for those explicit boundaries.
