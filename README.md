<p align="center"><img src="web/images/thread-sphere.png" width="132" alt="THREAD voice sphere"></p>
<h1 align="center">THREAD</h1>
<p align="center"><strong>Go on.</strong><br>A voice assistant you can interrupt and correct without losing the task.</p>

<p align="center"><a href="docs/checkpoint/TOUR.md">Take the tour</a> · <a href="docs/checkpoint/SETUP.md">Run it</a> · <a href="docs/checkpoint/ARCHITECTURE.md">How it works</a> · <a href="docs/checkpoint/VERIFICATION.md">Evidence</a> · <a href="docs/checkpoint/SAMSUNG.md">Submission checklist</a></p>

## September 29 engineering checkpoint

This is a development checkpoint for Samsung PRISM Theme 05, not a final submission or an official benchmark score. It brings the current FDB-v3 controller to an explicit **Kitchen** mode in the browser and Android app. Kitchen can add, check, and read a real checklist stored on the client. It uses the same revision, authorization, cancellation, and outcome-accounting logic as the benchmark adapter.

[Download the checkpoint](https://github.com/anshcantcode/thread-team-guide/releases/tag/v0.7.0-checkpoint.20260929): Android APK, browser bundle, complete source, portable evidence and SHA-256 checksums. Start with the matching source and [setup guide](docs/checkpoint/SETUP.md); the clients require the local host. This private repository must be shared with reviewers before its links work for them.

| Entry point | What it runs | Start here |
|---|---|---|
| Browser Kitchen | Local speech/model host, current controller, persistent browser checklist | [Setup](docs/checkpoint/SETUP.md#browser-kitchen) |
| Android Kitchen, 0.7.0-checkpoint | Same host/controller, native device storage and receipts | [APK and connection](docs/checkpoint/SETUP.md#android-kitchen) |
| FDB-v3 benchmark | LiveKit WebRTC agent, 12 official mock tools, released recordings and evaluators | [Reproduction](docs/fdb3/REPRODUCE.md) |
| Earlier Gemini app | Existing product mode with its own backend | [Legacy setup](docs/GEMINI_SETUP.md) |

Kitchen uses **WebSocket PCM through a LiveKit AgentSession**. Benchmark measurements use the separate **LiveKit WebRTC** runner. Kitchen does not make real purchases, book flights, or embed the host model in the phone. Earlier Gemini mode is retained and is not represented as having migrated to this controller.

## What changes when you change your mind

1. Speech onset immediately blocks submission from the superseded revision.
2. The controller merges the new words into the request and checks proposed arguments against their source clauses.
3. An unsubmitted obsolete action can be retired. An already-submitted action keeps its identity until its actual outcome is known.
4. A device receipt records what happened. A spoken sentence alone never proves an action succeeded.

Every Kitchen tool request carries a session identity, fresh input token, and idempotency key. The client checks them before changing its checklist. A delayed success can settle an earlier unknown outcome without replaying the action or restarting its old continuation.

## Evidence, with its limits

Two complete historical local runs each recorded **61/100 strict tool passes**, with all 100 recordings evaluated and zero recorded infrastructure errors. Run 7 measured `1fcba977`; run 8 measured `4f95fdcb`. Both used a local Qwen judge. Their archives were checked again for coverage, file identities, evaluator receipts, and agreement between actual calls and the execution journal.

They measured different revisions and do not establish repeated qualification of one frozen configuration. Later identifier and required-argument repairs, plus this checkpoint's client integration, are **not covered by the 61/100 result**. The organizer's rerun is the official score. No proxy re-judge is presented as that score.

See [verification](docs/checkpoint/VERIFICATION.md) for fresh regression/build/client checks and evidence files. The internal goal of three fresh 100/100 runs remains unmet. No competitor ranking is claimed without comparable execution.

## Repository map

| Path | Responsibility |
|---|---|
| `participant/` | Task state, authorization, correction, cancellation and outcome accounting |
| `thread_agent/fdb3*.py` | Benchmark contract, planner bridge, LiveKit speech and client adapters |
| `web/fdb3.*` | Browser Kitchen and client-owned tool boundary |
| `android/` | Android app, native checklist storage and instrumentation tests |
| `scripts/` | Setup, reproduction, evidence verification and local host |
| `config/`, `requirements-*.lock` | Model identities, feature settings and dependency pins |
| `tests/`, `tests_fdb3/`, `tests_linux/` | Controller, real-SDK and reproduction regressions |
| `evaluation/` | Evaluator-only authored fixtures; never a production input source |
| `docs/checkpoint/` | Current tour, commands, architecture, evidence and requirements |

## Reproduce the benchmark

On a suitably provisioned Linux/NVIDIA host, this entry point installs isolated environments, verifies pinned assets, launches owned services, runs the released dataset and invokes the evaluators:

```bash
bash scripts/reproduce_fdb3_linux.sh
```

Read the [requirements and verification limits](docs/fdb3/REPRODUCE.md) first. The full fresh-machine Linux pipeline still requires qualification; preparation or unit tests are not a substitute for a completed benchmark. Local judging is the default. Hosted calls require separately authorized resources.

The [Samsung checklist](docs/checkpoint/SAMSUNG.md) distinguishes implemented work from human fields, disclosure/signature, final media, judge access, and organizer rerun. Required AI assistance disclosure and third-party notices remain truthful. Credentials, personal configuration, runtime caches, and private work notes are excluded from release packages.
