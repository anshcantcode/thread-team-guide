#!/usr/bin/env bash
# One-command FDB-v3 reproduction for a Linux + NVIDIA host (organizer rerun shape).
#
# Runs THREAD as a LiveKit agent against the pinned upstream released-data
# pipeline, then all three upstream evaluators, then fdb3_verify_released.py.
# Exit 2: incomplete inference/judging (every recording stays in the
# denominator); 1: complete but not 100/100; 0: all pass.
#
# --prepare-only provisions the agent and verifies assets, without starting any
# service, running GPU inference or installing the large NeMo evaluator stack.
# Its zero exit means PREPARED_ONLY, never a completed benchmark/reproduction.
#
# Required inputs (environment):
#   THREAD_FDB3_ARCHIVE   path to fdb_v3_data_released.zip (SHA-256 checked)
# Optional:
#   LIVEKIT_URL/LIVEKIT_API_KEY/LIVEKIT_API_SECRET  existing server; otherwise
#   LIVEKIT_SERVER        path to a livekit-server 1.13.x binary started in --dev mode
#   LLAMA_SERVER          path to a CUDA llama-server; otherwise built from the pinned commit
#   THREAD_FDB3_JUDGE_MODE local (default) or hosted. Local uses pinned Qwen,
#                         explicitly NOT Samsung's judge. Hosted additionally
#                         requires THREAD_FDB3_HOSTED_JUDGE_AUTHORIZED=1 and
#                         OPENAI_API_KEY; no cloud key is used implicitly.
#   THREAD_WORK           work directory (default: ./.repro-<timestamp>)
#   THREAD_FDB3_TTS_COMMAND  JSON argv for speech output (default: espeak-ng)
#   THREAD_FDB3_MODEL_FILE / THREAD_FDB3_WHISPER_DIR  optional pre-downloaded copies of the pinned
#                         planner GGUF and faster-whisper directory (still SHA-256 checked)
#   THREAD_FDB3_WHISPER_MODEL  base.en|small.en (default in config/fdb3-candidate.json)
#                         selects repo/revision/hashes, independently of CPU/CUDA device
#   THREAD_PYTHON         Python 3.11 executable (default: python3.11)
#   THREAD_BUILD_JOBS     build parallelism, 1 or 2 (default: 2)
#   THREAD_PLANNER_PORT / THREAD_LIVEKIT_PORT / THREAD_LIVEKIT_RTC_PORT
#                         owned local service ports (defaults: 8197/7980/7981)
set -Eeuo pipefail

PREPARE_ONLY=0
case "${1:-}" in
  --prepare-only) PREPARE_ONLY=1 ;;
  --help|-h) sed -n '2,/^set -/p' "$0" | sed '$d'; exit 0 ;;
  '') ;;
  *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
esac
[ "$#" -le 1 ] || { printf 'Expected at most one option\n' >&2; exit 2; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${THREAD_WORK:-$ROOT/.repro-$(date -u +%Y%m%dT%H%M%SZ)}"
PROVIDER="${THREAD_PROVIDER_LABEL:-thread}"
PYTHON="${THREAD_PYTHON:-python3.11}"
BUILD_JOBS="${THREAD_BUILD_JOBS:-2}"
PLANNER_PORT="${THREAD_PLANNER_PORT:-8197}"
LIVEKIT_PORT="${THREAD_LIVEKIT_PORT:-7980}"
LIVEKIT_RTC_PORT="${THREAD_LIVEKIT_RTC_PORT:-7981}"
export THREAD_AGENT_PORT="${THREAD_AGENT_PORT:-8181}"
JUDGE_MODE="${THREAD_FDB3_JUDGE_MODE:-local}"

log() { printf '[reproduce] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 2; }
check_sha() { [ "$(sha256sum "$1" | cut -c1-64)" = "$2" ] || die "SHA-256 mismatch for $1"; }
trap 'log "ERROR: prerequisite/runtime command failed at line $LINENO; evidence is incomplete"; exit 2' ERR

case "$BUILD_JOBS" in 1|2) ;; *) die "THREAD_BUILD_JOBS must be 1 or 2";; esac
[[ "$PROVIDER" =~ ^[a-zA-Z0-9_-]+$ ]] || die "invalid provider label"
case "$JUDGE_MODE" in local|hosted) ;; *) die "THREAD_FDB3_JUDGE_MODE must be local or hosted";; esac
if [ "$PREPARE_ONLY" -eq 0 ] && [ "$JUDGE_MODE" = hosted ]; then
  [ "${THREAD_FDB3_HOSTED_JUDGE_AUTHORIZED:-0}" = 1 ] || die "hosted judge requires explicit authorization and a caller-managed finite budget"
  [ -n "${OPENAI_API_KEY:-}" ] || die "hosted judge requires OPENAI_API_KEY"
fi
# Refuse existing directories atomically: old outputs and environments are not a
# fresh run. In particular, never truncate another campaign's evidence.
mkdir "$WORK" || die "THREAD_WORK must name a new directory with an existing parent"
WORK="$(cd "$WORK" && pwd)"
mkdir "$WORK/logs" "$WORK/slots"
PIDS=()
cleanup() {
  local pid
  for pid in "${PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill -- -"$pid" 2>/dev/null || kill "$pid" 2>/dev/null || :
    fi
  done
}
trap cleanup EXIT

# 1. Prerequisites (never installs system packages silently).
for tool in "$PYTHON" ffmpeg git sha256sum curl; do command -v "$tool" >/dev/null || die "missing $tool"; done
"$PYTHON" -c 'import sys; assert sys.version_info[:2] == (3, 11), "Pinned dependencies require Python 3.11"'
CONFIG_SHELL="$("$PYTHON" "$ROOT/scripts/fdb3_config.py" --shell)" || die "candidate configuration rejected"
eval "$CONFIG_SHELL"
"$PYTHON" "$ROOT/scripts/fdb3_config.py" >"$WORK/candidate.json"
if [ "$PREPARE_ONLY" -eq 0 ]; then
  command -v setsid >/dev/null || die "missing setsid"
  command -v nvidia-smi >/dev/null || die "full upstream pipeline requires NVIDIA CUDA (including NeMo output ASR)"
  nvidia-smi --query-gpu=name,memory.total --format=csv,noheader >"$WORK/logs/gpu.txt"
fi
[ -n "${THREAD_FDB3_ARCHIVE:-}" ] && [ -f "$THREAD_FDB3_ARCHIVE" ] || die "set THREAD_FDB3_ARCHIVE to the released data zip"
check_sha "$THREAD_FDB3_ARCHIVE" "$ARCHIVE_SHA256"
if [ -z "${THREAD_FDB3_TTS_COMMAND:-}" ]; then
  command -v espeak-ng >/dev/null || die "install espeak-ng or set THREAD_FDB3_TTS_COMMAND"
  export THREAD_FDB3_TTS_COMMAND='["espeak-ng","-w","{output}","-f","{text_file}"]'
  export THREAD_FDB3_TTS_PROFILE=espeak-ng
fi

# 2. Separate agent and benchmark environments (agent never sees gold metadata).
# Execute copied Python/configuration, not a checkout another agent may edit.
"$PYTHON" "$ROOT/scripts/fdb3_config.py" --snapshot "$WORK/source" >"$WORK/source-identity.json"
ROOT="$WORK/source"
"$PYTHON" -m venv "$WORK/venv-agent"
"$WORK/venv-agent/bin/pip" install -q -r "$ROOT/requirements-fdb3.lock"
if [ "$PREPARE_ONLY" -eq 0 ]; then
  "$WORK/venv-agent/bin/pip" install -q --no-cache-dir --require-hashes -r "$ROOT/requirements-fdb3-cuda.txt"
  CUDA_PYTHON_LIBS="$("$WORK/venv-agent/bin/python" -c 'import site; print(site.getsitepackages()[0])')/nvidia"
  export LD_LIBRARY_PATH="$CUDA_PYTHON_LIBS/cublas/lib:$CUDA_PYTHON_LIBS/cudnn/lib:$CUDA_PYTHON_LIBS/cuda_runtime/lib:${LD_LIBRARY_PATH:-}"
fi
"$WORK/venv-agent/bin/pip" check
"$WORK/venv-agent/bin/pip" freeze >"$WORK/logs/agent-freeze.txt"

# 3. Pinned upstream, released data, model and recognizer assets.
git clone -q https://github.com/DanielLin94144/Full-Duplex-Bench "$WORK/upstream"
git -C "$WORK/upstream" checkout -q "$UPSTREAM_COMMIT"
V3="$WORK/upstream/v3"
"$PYTHON" "$ROOT/scripts/fdb3_prepare.py" --archive "$THREAD_FDB3_ARCHIVE" --upstream "$WORK/upstream" --destination "$WORK/assets" >"$WORK/logs/assets.json"
DATA="$(find "$WORK/assets/evaluator-data" -maxdepth 2 -type d -name fdb_v3_data_released -print -quit)"
[ -n "$DATA" ] || die "archive has no fdb_v3_data_released directory"
ln -sfn "$DATA" "$V3/fdb_v3_data_released"
[ "$(find "$DATA" -name input.wav | wc -l)" -eq 100 ] || die "expected 100 recordings"
mkdir -p "$WORK/models"
# Optional pre-downloaded copies (same SHA-256 checks): THREAD_FDB3_MODEL_FILE and THREAD_FDB3_WHISPER_DIR.
if [ -n "${THREAD_FDB3_MODEL_FILE:-}" ]; then
  ln -sfn "$(readlink -f "$THREAD_FDB3_MODEL_FILE")" "$WORK/models/model.gguf"
else
  curl -fsSL -o "$WORK/models/model.gguf" "$MODEL_URL"
fi
check_sha "$WORK/models/model.gguf" "$MODEL_SHA256"
if [ -n "${THREAD_FDB3_WHISPER_DIR:-}" ]; then
  mkdir -p "$WORK/models/whisper" && cp -rL "$THREAD_FDB3_WHISPER_DIR"/. "$WORK/models/whisper"/
else
  "$WORK/venv-agent/bin/python" "$ROOT/scripts/setup_speech.py" \
    --model-dir "$WORK/models/whisper" --download-only >"$WORK/logs/whisper-download.json"
fi
for file in "${!WHISPER_SHA256[@]}"; do check_sha "$WORK/models/whisper/$file" "${WHISPER_SHA256[$file]}"; done
"$WORK/venv-agent/bin/python" "$ROOT/scripts/setup_speech.py" \
  --model-dir "$WORK/models/whisper" --check-only >"$WORK/whisper-identity.json"

# Validate the actual Linux imports and public contract, not only pip metadata.
(cd "$ROOT" && "$WORK/venv-agent/bin/python" - "$WORK" <<'PY'
import hashlib, json, platform, subprocess, sys
from pathlib import Path
import av, ctranslate2, faster_whisper, onnxruntime
from livekit import agents, rtc
from thread_agent.fdb3 import load_contract, load_registry
from thread_agent.fdb3_voice import speech_backend
work = Path(sys.argv[1])
contract = work / 'assets/agent-contract'
tools = load_contract(contract)
load_registry(contract)
speech_backend()
report = {
    'status': 'PREPARED_ONLY', 'full_reproduction': False, 'inference_recordings': 0,
    'python': platform.python_version(), 'platform': platform.platform(),
    'public_tools': len(tools), 'contract_files': sorted(p.name for p in contract.iterdir() if p.is_file()),
    'source_identity': json.loads((work/'source-identity.json').read_text()),
    'whisper': json.loads((work/'whisper-identity.json').read_text()),
    'script_sha256': hashlib.sha256(Path('scripts/reproduce_fdb3_linux.sh').read_bytes()).hexdigest(),
    'agent_lock_sha256': hashlib.sha256(Path('requirements-fdb3.lock').read_bytes()).hexdigest(),
    'upstream_commit': subprocess.check_output(['git', '-C', str(work/'upstream'), 'rev-parse', 'HEAD'], text=True).strip(),
    'paid_requests': 0,
}
(work/'preparation.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report))
PY
) >"$WORK/logs/imports.json"
if [ "$PREPARE_ONLY" -eq 1 ]; then
  log "PREPARED_ONLY: verified assets and agent imports in $WORK; no inference or judge run"
  exit 0
fi

"$PYTHON" -m venv "$WORK/venv-bench"
"$WORK/venv-bench/bin/pip" install -q --require-hashes -r "$ROOT/requirements-fdb3-bench.lock"
"$WORK/venv-bench/bin/pip" check
"$WORK/venv-bench/bin/pip" freeze >"$WORK/logs/benchmark-freeze.txt"

# Fail before starting anything if any requested port belongs to another task.
"$PYTHON" - "$PLANNER_PORT" "$LIVEKIT_PORT" "$LIVEKIT_RTC_PORT" "$THREAD_AGENT_PORT" <<'PY'
import socket, sys
ports = [int(p) for p in sys.argv[1:]]
if len(set(ports)) != len(ports):
    raise SystemExit('Owned service ports must be distinct')
for port in ports:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', port))
PY

# 4. Planner server on the GPU, pinned llama.cpp.
if [ -z "${LLAMA_SERVER:-}" ]; then
  command -v cmake >/dev/null || die "install cmake + CUDA toolkit, or set LLAMA_SERVER"
  git clone -q https://github.com/ggml-org/llama.cpp "$WORK/llama.cpp"
  git -C "$WORK/llama.cpp" checkout -q "$LLAMA_COMMIT"
  cmake -S "$WORK/llama.cpp" -B "$WORK/llama.cpp/build" -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release >"$WORK/logs/llama-build.log"
  cmake --build "$WORK/llama.cpp/build" --target llama-server -j "$BUILD_JOBS" >>"$WORK/logs/llama-build.log"
  LLAMA_SERVER="$WORK/llama.cpp/build/bin/llama-server"
fi
"$LLAMA_SERVER" --version >"$WORK/logs/llama-version.txt" 2>&1
grep -q "${LLAMA_COMMIT:0:9}" "$WORK/logs/llama-version.txt" || die "LLAMA_SERVER must match pinned $LLAMA_VERSION ($LLAMA_COMMIT)"
sha256sum "$LLAMA_SERVER" >"$WORK/logs/llama-binary.sha256"
setsid "$LLAMA_SERVER" -m "$WORK/models/model.gguf" --host 127.0.0.1 --port "$PLANNER_PORT" \
  "${LLAMA_ARGS[@]}" --slot-save-path "$WORK/slots" >"$WORK/logs/model.log" 2>&1 &
PIDS+=($!)
for _ in $(seq 1 120); do
  kill -0 "${PIDS[0]}" 2>/dev/null || die "owned planner exited; see logs/model.log"
  if curl --max-time 2 -fs "http://127.0.0.1:$PLANNER_PORT/health" >/dev/null; then break; fi
  sleep 2
done
curl --max-time 2 -fs "http://127.0.0.1:$PLANNER_PORT/health" >/dev/null || die "planner server not ready"

# 5. LiveKit: organizer-provided server, or a local dev server.
if [ -z "${LIVEKIT_URL:-}" ]; then
  [ -n "${LIVEKIT_SERVER:-}" ] || die "set LIVEKIT_URL/KEY/SECRET or LIVEKIT_SERVER"
  setsid "$LIVEKIT_SERVER" --dev --bind 127.0.0.1 --node-ip 127.0.0.1 --port "$LIVEKIT_PORT" --rtc.tcp_port "$LIVEKIT_RTC_PORT" >"$WORK/logs/livekit.log" 2>&1 &
  PIDS+=($!)
  export LIVEKIT_URL="ws://127.0.0.1:$LIVEKIT_PORT" LIVEKIT_API_KEY=devkey LIVEKIT_API_SECRET=secret
  sleep 3
fi

# 6. THREAD agent worker (public tool contract only; fresh state per room).
# Upstream hardcodes this collector pathname. An exclusive campaign lock avoids
# wiping a concurrent owner's telemetry; remove neither existing logs nor locks.
command -v flock >/dev/null || die "install util-linux (flock)"
exec 9>/tmp/thread-fdb3-upstream.lock
flock -n 9 || die "another upstream reproduction owns the global telemetry collector"
[ ! -e /tmp/agent_tool_calls.log ] || die "existing /tmp/agent_tool_calls.log; preserve it and use a clean environment"
(set -o noclobber; : > /tmp/agent_tool_calls.log) || die "telemetry collector already exists"
export THREAD_FDB3_CONTRACT="$WORK/assets/agent-contract" THREAD_FDB3_ENDPOINT="http://127.0.0.1:$PLANNER_PORT/v1" THREAD_FDB3_MODEL=local-qwen \
       THREAD_FDB3_WHISPER="$WORK/models/whisper" THREAD_FDB3_CACHE_OWNER_FILE="$WORK/cache-owner" \
       THREAD_FDB3_TELEMETRY=/tmp/agent_tool_calls.log THREAD_FDB3_JOURNAL_DIR="$WORK/journals"
setsid "$WORK/venv-agent/bin/python" "$ROOT/scripts/fdb3_agent.py" start >"$WORK/logs/agent.log" 2>&1 &
PIDS+=($!)
sleep 10

# 7. Upstream released-data inference, then all three evaluators.
# Upstream asks for gpt-4o by name. Local mode directs those requests to pinned
# Qwen; hosted mode uses the explicitly authorized endpoint and credentials.
if [ "$JUDGE_MODE" = local ]; then
  export OPENAI_BASE_URL="http://127.0.0.1:$PLANNER_PORT/v1" OPENAI_API_KEY=local-no-billing
  log "Judge: local Qwen3.5-4B (not Samsung's official judge); no paid API requests"
else
  log "Judge: upstream gpt-4o via explicitly authorized hosted endpoint; caller manages budget"
fi
stage_failures=0
run_stage() {
  local name="$1" code=0; shift
  "$@" >"$WORK/logs/$name.log" 2>&1 || code=$?
  printf '%s\t%s\n' "$name" "$code" >>"$WORK/stage-exits.tsv"
  if [ "$code" -ne 0 ]; then stage_failures=$((stage_failures + 1)); log "$name failed (exit $code); retaining evidence"; fi
}
cd "$V3"
run_stage inference "$WORK/venv-bench/bin/python" run_tool_benchmark_all_released.py --provider "$PROVIDER" --root_dir fdb_v3_data_released
CHECKED_JUDGE=("$WORK/venv-agent/bin/python" "$ROOT/scripts/fdb3_checked_upstream.py" --upstream "$V3" --judge-mode "$JUDGE_MODE")
if [ "$JUDGE_MODE" = local ]; then
  CHECKED_JUDGE+=(--judge-endpoint "http://127.0.0.1:$PLANNER_PORT/v1" --judge-identity Qwen3.5-4B-Q4_K_M.gguf)
else
  CHECKED_JUDGE+=(--judge-identity 'upstream gpt-4o hosted; organizer snapshot unverified')
fi
run_stage eval-tools "${CHECKED_JUDGE[@]}" --script evaluate_tool_calls --evidence "$WORK/eval-tools-receipts.json" -- --benchmark benchmark_data_v2.json --results-dir fdb_v3_data_released \
   --provider "$PROVIDER" --output "$WORK/${PROVIDER}_evaluation_report.json" --use-llm
run_stage eval-pass "${CHECKED_JUDGE[@]}" --script evaluate_pass_rate --evidence "$WORK/eval-pass-receipts.json" -- --benchmark benchmark_data_v2.json --results-dir fdb_v3_data_released \
   --provider "$PROVIDER" --output "$WORK/${PROVIDER}_pass_rate_report.json" --use-llm
run_stage eval-latency "$WORK/venv-bench/bin/python" analyze_tool_latency.py --results-dir fdb_v3_data_released --provider "$PROVIDER"

# 8. Truthful accounting: every recording, nonzero on anything incomplete.
code=0
"$WORK/venv-agent/bin/python" "$ROOT/scripts/fdb3_verify_released.py" --results-dir "$DATA" --provider "$PROVIDER" \
  --pass-report "$WORK/${PROVIDER}_pass_rate_report.json" --output "$WORK/verification.json" \
  --judge-receipts "$WORK/eval-tools-receipts.json" "$WORK/eval-pass-receipts.json" || code=$?
[ "$stage_failures" -eq 0 ] || code=2
"$PYTHON" - "$WORK" "$code" "$JUDGE_MODE" <<'PY'
import json, sys
from pathlib import Path
work = Path(sys.argv[1])
report = {'exit_code': int(sys.argv[2]), 'judge_mode': sys.argv[3],
          'judge_identity': 'Qwen3.5-4B-Q4_K_M (local diagnostic)' if sys.argv[3] == 'local' else 'upstream gpt-4o (hosted; organizer snapshot unverified)',
          'stage_exits': dict(line.split('\t') for line in (work/'stage-exits.tsv').read_text().splitlines())}
(work/'execution.json').write_text(json.dumps(report, indent=2))
PY
log "evidence: $WORK (exit $code)"
exit $code
