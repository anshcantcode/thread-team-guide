# FDB-v3 reproduction

The current model and runtime settings are centralized in [config/fdb3-candidate.json](../../config/fdb3-candidate.json). The default recognizer is **small.en**, pinned to Systran revision `d1d751a5f8271d482d14ca55d9e2deeebbae577f`. The release declares **seed 42**. Source identity comes from the actual checkout commit and file hashes. A source ZIP has no Git identity: its snapshot explicitly records null commit/dirty values and exact file hashes instead of borrowing a parent checkout's commit.

## Full Linux entry point

Prerequisites: Linux, Python 3.11, Git, FFmpeg, espeak-ng, curl, sha256sum, setsid, flock, a supported NVIDIA/CUDA environment and enough disk for two environments, models, recordings and output. The official environment describes a 48 GB NVIDIA GPU. The full evaluator installs NeMo; a CPU preparation alone does not validate that stage.

Obtain the organizer's released archive and a local LiveKit server binary. Do not substitute a differently hashed dataset.

```bash
export THREAD_FDB3_ARCHIVE=/absolute/path/fdb_v3_data_released.zip
export LIVEKIT_SERVER=/absolute/path/livekit-server
bash scripts/reproduce_fdb3_linux.sh
```

This is the one-command install/configure/evaluate entry point after external prerequisites are supplied. It creates a fresh work directory; verifies the archive, model and recognizer hashes; checks out upstream `3e799c45a045256f47d5f1c9cda90157e2d2ec9e`; prepares separate runtime/evaluator environments; starts owned local services; runs released-data inference; invokes tool, pass-rate and latency evaluators; then writes coverage and judge-request verification.

Exit 0 means every required check and strict case passed; 1 means a complete run with non-passes; 2 means incomplete infrastructure or evaluation. Read the generated reports as well as the exit code. Failures remain in the denominator. Never reuse an earlier output directory as fresh inference.

Local Qwen judging is the default and is **not** Samsung's organizer judge. Hosted judging requires explicit finite authorization and separate credentials; the current project spending authorization is zero. Never enable hosted mode merely to satisfy a command.

Optional supplied assets:
```bash
export THREAD_FDB3_MODEL_FILE=/absolute/path/Qwen3.5-4B-Q4_K_M.gguf
export THREAD_FDB3_WHISPER_DIR=/absolute/path/whisper-small-en
export LLAMA_SERVER=/absolute/path/pinned-llama-server
export THREAD_WORK=/absolute/path/new-run-directory
```

The runner checks pinned identities and rejects conflicting inherited feature flags. It snapshots the exact runtime source. Default llama settings include context 8192, one slot, reasoning off, temperature 0 in planner requests, explicit server seed 42, and scenario-scoped cache ownership. Historical Windows runs did not set an explicit sampling seed; their manifests retain that fact. Their scores are not new results for this changed configuration.

The evaluator uses `requirements-fdb3-bench.lock` with `--require-hashes`: 225 resolved packages for Linux x86_64, glibc 2.28 or later, Python 3.11. Direct versions and official package metadata are recorded in `requirements-fdb3-bench.txt`. A fresh Linux installation and dependency-consistency check passed, followed by NeMo ASR import and four unmodified upstream CLI checks with networking disabled. The runtime and evaluator use separate environments. These checks loaded no model and are not proof of a successful full GPU benchmark.

## Preparation and containers

`bash scripts/reproduce_fdb3_linux.sh --prepare-only` verifies CPU preparation only. Its success is **PREPARED_ONLY**, not a benchmark score. `Dockerfile.fdb3` has an explicit CPU component target and a CUDA candidate target. The earlier `Dockerfile.submission` and root `submission.yaml` describe the old queue-kit participant, not the current FDB entry point.

Fresh Linux preparation from a source export without `.git` has passed: dependency consistency, hash-checked models and 100 recordings, all 12 public tools, speech-backend validation and the LiveKit agent CLI. The full Linux/NeMo/GPU benchmark remains unqualified. [Results](../submission/RESULTS.md) distinguishes preparation/component checks from complete historical Windows WebRTC runs. No supplied command is advertised as already verified on organizer hardware.

## Existing Windows diagnostic route

`scripts/fdb3_local_reproduce.py` accepts explicit paths to local llama-server, LiveKit server, Qwen weights, Whisper assets, pinned upstream and released archive, with `budget_inr: 0`. See its `--help` and validation errors. It provisions a dedicated environment and refuses occupied service ports. It never reads a private .env file.

Windows uses SAPI for local diagnostic speech. Linux requires a configured local synthesizer; the Linux runner defaults to espeak-ng. Different speech engines and transports are declared in run identities and are not silently treated as comparable latency measurements.

For the current browser/Android extension, use [Kitchen setup](../SETUP.md). Its WebSocket PCM transport is separate from benchmark WebRTC.
