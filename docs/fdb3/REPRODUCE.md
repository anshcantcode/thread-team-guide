# FDB-v3 reproduction

**4 October 2026:** the final-source run, its configuration and its results are in [submission results](../submission/RESULTS.md) and the [README results](../../README.md#results). The commands below are the unchanged interfaces. The local route remains INR 0.

The current model and runtime settings are centralized in [config/fdb3-candidate.json](../../config/fdb3-candidate.json). The default recognizer is **small.en**, pinned to Systran revision `d1d751a5f8271d482d14ca55d9e2deeebbae577f`. The release declares **seed 42**. Source identity comes from the actual checkout commit and file hashes. A source ZIP has no Git identity: its snapshot explicitly records null commit/dirty values and exact file hashes instead of borrowing a parent checkout's commit.

**3 October 2026 qualification:** the real command completed all **100/100** recordings from clean source export `8ef5b59` in WSL on a 6 GB RTX 4050. Strict tool pass **61/100**; all four stages exited 0; the script/verifier exited **1** (complete with non-passes). [Full evidence, repairs and limitations](LINUX_QUALIFICATION_20261003.md). This qualifies that local execution path, not the organizers' 48 GB hardware, a new CUDA build, or their official judge. The final attempt used explicitly declared task-owned download/package caches and the permitted exact-hash prior llama build.

## Full Linux entry point

Prerequisites: Linux x86_64 (glibc >= 2.28), Python 3.11 with venv/pip, Git, FFmpeg, espeak-ng, curl, tar, sha256sum, setsid, flock, a supported NVIDIA/CUDA environment and enough disk for two environments, models, recordings and output. The official environment describes a 48 GB NVIDIA GPU. The full evaluator installs NeMo; a CPU preparation alone does not validate that stage. A CUDA-capable **driver is not the CUDA compiler/toolkit**: building llama-server also requires CMake, a compatible C++ compiler and `nvcc` on PATH. Without those, supply a separately built server from the pinned commit using `LLAMA_SERVER`. The script checks this before installing the full stack and never installs or changes the host GPU driver.

Obtain the organizer's released archive. Do not substitute a differently hashed dataset. The script downloads LiveKit **1.13.7** for Linux x86_64 and checks both its archive and executable SHA-256 against `config/fdb3-linux-build.json`. No pre-existing LiveKit binary/cache is required. An explicitly supplied `LIVEKIT_SERVER` must match that executable hash; an explicitly configured existing server remains a separate option.

**Exact organizer command**, from the extracted source archive on the Linux filesystem, after the prerequisites below are installed. Replace the absolute input/interpreter/output paths with the actual target paths. Leave `LLAMA_SERVER` unset to build the pinned Git checkout for the target GPU; do not copy the local SM89 binary to a different architecture. No `.git` directory is needed in THREAD's source archive.

```bash
cd /absolute/path/extracted-thread-source
export THREAD_PYTHON=/absolute/path/python3.11
export THREAD_FDB3_ARCHIVE=/absolute/path/fdb_v3_data_released.zip
export THREAD_WORK=/absolute/path/new-full-run
export THREAD_FDB3_JUDGE_MODE=local
export THREAD_BUILD_JOBS=1
bash scripts/reproduce_fdb3_linux.sh
```

This is the one-command install/configure/evaluate entry point after external prerequisites are supplied. It creates a fresh work directory; verifies the archive, model and recognizer hashes; checks out upstream `3e799c45a045256f47d5f1c9cda90157e2d2ec9e`; prepares separate runtime/evaluator environments; starts owned local services; runs released-data inference; invokes tool, pass-rate and latency evaluators; then writes coverage and judge-request verification.

The entry point closes inherited stdin: it is a noninteractive batch command, and upstream FFmpeg must not read a terminal when launched by a background supervisor. For a caller-imposed time bound, use `timeout --foreground ...`; preserve the exit code and evidence if that bound interrupts the run.

It also sets `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8` for all Python children. Native ASR code can reset the process locale to `C`; Python UTF-8 mode prevents later upstream subprocess output from being decoded as ASCII. This does not alter upstream evaluation logic or suppress decoding errors.

GGUF and LiveKit downloads allow at most three transfers (30-minute bound each). Each failed transfer remains as an `.attempt-N` file with its curl failure in the log. Only a successful transfer with the pinned SHA-256 is moved into the final asset path. A hash mismatch fails immediately; existing files are never overwritten. These are asset-transfer retries, not inference retries or combined benchmark runs.

### Python provisioning when `python3.11` is not on PATH

Ubuntu 24.04 does not supply the required interpreter under that command by default. One explicit provisioning route (free downloads; no model/API calls) is:

```bash
sudo apt-get update
sudo apt-get install -y python3-venv git ffmpeg espeak-ng curl ca-certificates util-linux build-essential cmake
python3 -m venv "$HOME/.local/share/thread-bootstrap"
"$HOME/.local/share/thread-bootstrap/bin/pip" install 'uv==0.12.19'
"$HOME/.local/share/thread-bootstrap/bin/uv" python install 3.11.16
export THREAD_PYTHON="$("$HOME/.local/share/thread-bootstrap/bin/uv" python find --managed-python 3.11.16)"
"$THREAD_PYTHON" --version
```

`uv` obtains a managed CPython distribution; this is not a system Python replacement. See [uv's Python installation documentation](https://docs.astral.sh/uv/guides/install-python/). On the local qualification WSL distro, the existing interpreter resolves to `/root/.local/share/uv/python/cpython-3.11.16-linux-x86_64-gnu/bin/python3.11` (uv 0.12.19). That path is local evidence, not a portable organizer requirement. Set `THREAD_PYTHON` to the actual interpreter on the target machine. The script rejects other Python minor versions.

S2 found and reused that existing September interpreter; it did not claim to repeat a new system-Python installation. The commands above are the explicit provisioning route for a clean machine. Provisioning Python/toolkit/system packages is a prerequisite, not something the reproduction silently does with root privileges.

For the default **build-from-source** route, install a CUDA 12.x/13.x toolkit and its supported host compiler using [NVIDIA's Linux installation guide](https://docs.nvidia.com/cuda/cuda-installation-guide-linux/), and verify `nvcc --version`, `cmake --version`, and `c++ --version` before invoking the command. Build jobs are restricted to one or two. The build disables llama's prebuilt web UI so an unpinned latest UI bundle is not fetched. A reused September 28 SM89 binary is accepted only at its exact recorded SHA-256; it is not advertised as a portable binary for an arbitrary 48 GB GPU.

Exit 0 means every required check and strict case passed; 1 means a complete run with non-passes; 2 means incomplete infrastructure or evaluation. Read the generated reports as well as the exit code. Failures remain in the denominator. Never reuse an earlier output directory as fresh inference.

Local Qwen judging is the default and is **not** Samsung's organizer judge. Hosted judging requires explicit finite authorization and separate credentials; the current project spending authorization is zero. Never enable hosted mode merely to satisfy a command.

### Official-judge handoff (organizer-controlled)

The two labels below describe workflows, **not new CLI subcommands**. Do not run `--organizer-official` or assume that such a flag exists.

| Workflow | Settings | Interpretation |
|---|---|---|
| **local-diagnostic** | `THREAD_FDB3_JUDGE_MODE=local` (default) | Pinned local Qwen. No hosted keys or paid judge requests. Never an official score. |
| **organizer-official handoff** | `THREAD_FDB3_JUDGE_MODE=hosted`, authorization and key below | Uses the unmodified upstream judge client. Official only if the organizers confirm their pinned judge/configuration and execute/adjudicate the rerun. |

**For organizers, not authorization for the team to spend:** in a fresh shell, supply the archive and LiveKit paths above and an organizer-controlled finite judge budget. Configure the key privately (never in source, shell recordings or release assets). Then use the already-supported switches:

```bash
export THREAD_FDB3_JUDGE_MODE=hosted
export THREAD_FDB3_HOSTED_JUDGE_AUTHORIZED=1
# Set OPENAI_API_KEY privately using the organizer's secret mechanism.
: "${OPENAI_API_KEY:?Organizer must supply the authorized judge key}"
# If the pinned judge uses a gateway, set OPENAI_BASE_URL to that endpoint.
# Otherwise unset inherited OPENAI_BASE_URL so the upstream client uses its default.
bash scripts/reproduce_fdb3_linux.sh
```

The script refuses hosted mode without authorization or a nonempty key. It does **not** implement a monetary quota: the caller must enforce the finite budget externally. The unchanged upstream client requests `gpt-4o`; there is **no script option to pin a dated judge model**. An organizer-provided compatible gateway can map that request to the organizer's pinned snapshot, or the organizers must supply their official evaluator configuration. Do not change grading semantics, substitute a different model or assert an unverified alias is the pinned judge.

Before official execution, record the exact judge snapshot/endpoint policy (no secrets), upstream commit `3e799c45a045256f47d5f1c9cda90157e2d2ec9e`, source/config hashes, input/output ASR, TTS, seed and evaluator command. The supplied material does not establish the organizer's complete judge snapshot or final normalization formula. Until the organizers resolve that, hosted output correctly remains **`upstream gpt-4o hosted; organizer snapshot unverified`**, not a team-certified official result. Missing official configuration is an unresolved handoff, never a reason to silently fall back to local judging.

Review `execution.json`, `stage-exits.tsv`, `verification.json`, `eval-tools-receipts.json` and `eval-pass-receipts.json`. These retain actual stages, judge receipts and failures; do not hide an invalid judge response behind exact-match fallback. Agent inference remains local even when the organizer chooses a hosted evaluator.

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

Preparation and the full run each require a **different new `THREAD_WORK`**. The full command intentionally provisions its own environments; it does not append results to a prepared or failed directory. Local package/download caches may be reused but must be declared in the evidence. Never combine partial runs.

Fresh Linux preparation from a source export without `.git` has passed: dependency consistency, hash-checked models and 100 recordings, all 12 public tools, speech-backend validation and the LiveKit agent CLI. S2 then completed the **full Linux/NeMo/GPU 100-recording path** from source `8ef5b59`; see [results](../submission/RESULTS.md). That fresh Linux result is distinct from the historical Windows measurements. No supplied command is advertised as already verified on organizer hardware or every CUDA 12/13 toolkit combination.

For a preparation check followed by a full run, use different new directories:

```bash
THREAD_WORK=/absolute/path/new-prepare bash scripts/reproduce_fdb3_linux.sh --prepare-only
THREAD_WORK=/absolute/path/new-full bash scripts/reproduce_fdb3_linux.sh
```

Read `verification.json`, `execution.json`, `stage-exits.tsv`, `thread_evaluation_report.json`, `thread_pass_rate_report.json` and both `eval-*-receipts.json` under `THREAD_WORK`. The unchanged upstream latency report is at `THREAD_WORK/upstream/v3/thread_latency_report.json`; its log is `THREAD_WORK/logs/eval-latency.log`. The S2 local-judge latency report includes four negative task-completion estimates; preserve/report these rather than interpreting them as physical timings. Repeated runs must not reuse results or delete someone else's `/tmp/agent_tool_calls.log`; the runner protects that upstream global collector with `flock` and refuses an existing collector.

## Existing Windows diagnostic route

`scripts/fdb3_local_reproduce.py` accepts explicit paths to local llama-server, LiveKit server, Qwen weights, Whisper assets, pinned upstream and released archive, with `budget_inr: 0`. See its `--help` and validation errors. It provisions a dedicated environment and refuses occupied service ports. It never reads a private .env file.

Windows uses SAPI for local diagnostic speech. Linux requires a configured local synthesizer; the Linux runner defaults to espeak-ng. Different speech engines and transports are declared in run identities and are not silently treated as comparable latency measurements.

For the current browser/Android extension, use [Kitchen setup](../SETUP.md). Its WebSocket PCM transport is separate from benchmark WebRTC.

## Run logs and per-case failure dossiers

Keep the exact source identity, effective configuration, model/ASR hashes, seed (including an honestly unset seed), all 100 outcomes, infrastructure errors and failed attempts with each run. The Linux runner writes these under its fresh `THREAD_WORK` directory, including `source/source-identity.json`, `logs/`, `journals/`, evaluator reports and the receipts listed above. Check the runner's actual output locations, not a guessed run ID.

For a **finished Windows `scripts/fdb3_run.py` campaign**, the new offline analyzer consumes that campaign's `identity.json`, `report.json`, `dataset-manifest.json` and `case-NNN/` evidence:

```powershell
# Paths are supplied by the operator; use a NEW output outside .thread-run.
python scripts/fdb3_case_dossier.py C:\PATH_TO_FINISHED_RUN --assets C:\PATH_TO_PREPARED_ASSETS --out C:\PATH_TO_NEW_DOSSIER
# Optional same-format comparison: append --baseline C:\PATH_TO_EARLIER_RUN
```

Outputs are `SUMMARY.md`, `dossier.json` and `case-NNN.md` for each recorded case. Each case includes heard fragments, planner decisions, controller refusals/admissions, tool outcomes, speech and evaluation. Failure-layer labels are heuristic post-hoc diagnostics, not a revised grade. The analyzer reads reference metadata only on the evaluator side, never as runtime input. Preserve that separation and the original reports.

This tool does **not** accept the Linux upstream runner's different output layout, nor a lone `fdb3_audio_worker.py` demo directory. Publish Linux reports/receipts directly; do not fabricate a compatible campaign or imply dossier support for a layout it does not read. For the one-recording demonstration, [the runbook](../submission/DEMO_RUNBOOK.md) uses the worker's real journals and final result in a read-only viewer.
