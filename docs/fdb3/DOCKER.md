# FDB-v3 agent container

`Dockerfile.fdb3` packages the LiveKit agent with pinned dependencies and
espeak-ng output. Its **default `cuda` target** uses the shared candidate
profile in `config/fdb3-candidate.json`; `--target cpu` is an explicit
`cpu-component` diagnostic, not the measured candidate. Both run as UID 10001.
The planner and LiveKit server are separate services. The full CUDA container benchmark has not been qualified. See [reproduction](REPRODUCE.md) for defaults, server flags, model hashes and the executed preparation scope.

The root `Dockerfile` and `Dockerfile.submission` belong to the historical queue
participant/validator. Neither is the FDB-v3 agent. Select this file explicitly:

```bash
docker build -f Dockerfile.fdb3 --target cpu -t thread-fdb3:cpu .
docker run --rm --network none thread-fdb3:cpu --help
# Candidate CUDA agent (NVIDIA container support required; not executed here):
docker build -f Dockerfile.fdb3 --target cuda -t thread-fdb3:cuda .
```

The base is Python 3.11.16 on Debian Bookworm, pinned by image digest. All 95
base Python dependencies are pinned in `requirements-fdb3.lock`. CUDA adds the
three SHA-pinned libraries in `requirements-fdb3-cuda.txt`. Debian packages
come from the base image's apt repositories at build time; the executed build's
package inventory is retained, but this is not a bit-for-bit rebuild guarantee.
The Docker-specific ignore file excludes private environment files, models,
recordings, evaluation labels, build output and raw evidence from the context.

## Inputs and execution

Prepare two host directories: one containing only the pinned public contract's
`cascaded_agent.py`, `mock_apis.py` and `latency_injector.py`, and one containing
the selected pinned faster-whisper model files. Set
`THREAD_FDB3_WHISPER_MODEL=base.en|small.en` consistently for host preparation
and the container; unset means the central default, currently **`small.en`**.
Both repositories, full revisions and four SHA-256 values are declared in
[`config/fdb3-candidate.json`](../../config/fdb3-candidate.json) and tabulated in
[the reproduction guide](REPRODUCE.md).
No model is downloaded at container startup: the agent checks all four mounted
files against the selected pins before loading them. A mismatched/missing model
fails instead of falling back. The preparation command in
[the Linux reproduction procedure](REPRODUCE.md) verifies and creates
these directories. Keep the
contract separate from the upstream evaluator's dataset and metadata.

For a Linux host with its own running planner and LiveKit server, the agent can
be started with the following template. Replace the absolute paths and supply a
private environment file containing `LIVEKIT_URL`, `LIVEKIT_API_KEY`,
`LIVEKIT_API_SECRET`, `THREAD_FDB3_ENDPOINT` and `THREAD_FDB3_MODEL`. The planner
endpoint ends in `/v1`; it must refer to the planner, not the judge. Do not add
that environment file to Git or the image.

```bash
mkdir -p /absolute/path/thread-evidence
sudo chown 10001:10001 /absolute/path/thread-evidence
docker run --rm --name thread-fdb3-agent --network host \
  --gpus all --cpus 4 --memory 4g --pids-limit 128 \
  --env-file /absolute/private/path/thread-livekit.env \
  --env THREAD_FDB3_WHISPER_MODEL \
  --mount type=bind,source=/absolute/path/agent-contract,target=/assets/contract,readonly \
  --mount type=bind,source=/absolute/path/selected-whisper,target=/assets/whisper,readonly \
  --mount type=bind,source=/absolute/path/thread-evidence,target=/evidence \
  thread-fdb3:cuda start
```

`--env THREAD_FDB3_WHISPER_MODEL` forwards the optional host selection; for
example, export `THREAD_FDB3_WHISPER_MODEL=small.en` before preparing that model
and running this template. The model choice does not change the target/device.
An offline CPU-only mounted-asset check, without starting a LiveKit agent, is:

```bash
docker run --rm --network none --entrypoint python \
  --env THREAD_FDB3_WHISPER_MODEL \
  --mount type=bind,source=/absolute/path/selected-whisper,target=/assets/whisper,readonly \
  thread-fdb3:cpu scripts/fdb3_config.py --verify-whisper /assets/whisper
```

Only `whisper.default_model` in the shared JSON would change to adopt a new
default; neither Dockerfile contains a second default. `Dockerfile.submission`
remains a legacy validator and does not load Whisper. Task M prepared/tested
the selection and hash logic on CPU; it did not build or run either image.

Host networking here is a Linux configuration. `LocalPlanner` requires a
loopback endpoint, so use `http://127.0.0.1:<planner-port>/v1` with the planner
in the same network namespace. A normal bridge-mode `host.docker.internal`
planner address is rejected. Docker Desktop networking has not been validated.
For CPU-only diagnostics, use the `cpu` target and omit `--gpus all`; do not
label that configuration as CUDA candidate evidence. The mounted
evidence directory receives `agent_tool_calls.log` and per-session journals.
The upstream benchmark expects a host telemetry pathname; a complete benchmark
launcher must connect that pathname to this output without overwriting another
run. Once the launcher owns its fresh `/tmp/agent_tool_calls.log` under the
existing run lock and grants UID 10001 write access, the exact additional agent
bind is `--mount type=bind,source=/tmp/agent_tool_calls.log,target=/evidence/agent_tool_calls.log`.
This makes the upstream collector and agent use the same file throughout the
run. Do not copy logs between scenarios or replace an existing run's path. The
current reproduction script starts a native agent; substituting this container
in that orchestration has not been tested.
The container example has not been exercised through AgentServer dispatch
or the upstream benchmark. Use `scripts/reproduce_fdb3_linux.sh` for the existing
full-run orchestration and checked judge receipts; do not treat this agent-only
command as the complete evaluator pipeline.

## Historical CPU evidence — not a test of the updated targets

Inside the task's isolated Ubuntu 24.04 WSL distribution, the image built and
`pip check` passed. Its exact local identity is
`sha256:e6457d692f8d3193821d91d5c8bfec2fa0dbce153df24fc495860b4680319d0e`.
The preserved build context contains 43 files, with individual hashes in
[container-context-20260928.json](evidence/container-context-20260928.json).

Containers with networking disabled successfully exercised the CLI entrypoint,
loaded all 12 public tools and the registry, initialized Silero VAD and the real
espeak-ng backend, and ran a CPU speech round trip through THREAD's `CommandTTS`
and local Whisper. Authored input and recognition were both **“The blue cup is
on the table.”** The WAV was 1.69554 seconds; the complete component smoke took
1.10746 seconds with two CPU threads. This is synthetic component evidence,
with zero benchmark recordings or model/judge requests. It is not agent latency
or a new benchmark score.

[container-summary-20260928.json](evidence/container-summary-20260928.json)
records the image, context, lock, log and speech hashes. Full logs, installed
package inventories and the WAV remain in `.thread-run/raw/container-evidence001`.
The image is local to the preserved task distribution; it has not been pushed
to a registry. The updated targets require a new build. CUDA recognition,
NeMo, GPU planner startup and the full Linux
100-recording inference/judging remain unverified.

After the checks, all temporary containers had exited. The task distribution's
new Docker/socket/containerd services were stopped and disabled, and only
`THREAD-Submission-Sprint3` was terminated to release memory. Its image and
evidence remain on disk. To use that preserved image again, start the distro
and explicitly run `sudo systemctl start docker`; Docker is not auto-started.
