#!/usr/bin/env bash
# Called ONLY by invoke_fdb3_wsl_smoke.ps1 after the explicit phase-2 handover.
set -Eeuo pipefail
stage="${1:?prepare or run}"; task="${2:?new /opt/thread-task-b path}"
[[ "$task" == /opt/thread-task-b/* && "$task" != *..* ]] || { echo 'Invalid task root' >&2; exit 2; }
case "$stage" in prepare|run) ;; *) echo 'Unknown stage' >&2; exit 2;; esac
export PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
prepared=/opt/thread-sprint3/prepared-001
py="$prepared/venv-agent/bin/python"
disk_guard() {
  "$py" -c 'import shutil; assert shutil.disk_usage("/mnt/c").free >= 2 * 1024**3, "Less than 2 GiB host disk headroom; stop without deleting other work"'
}
if [ "$stage" = prepare ]; then
  archive="${3:?source tar}"; identity="${4:?source identity}"
  mkdir -p /opt/thread-task-b
  mkdir "$task"  # Fresh output only; no cleanup/reuse of failed preparations.
  mkdir "$task/source" "$task/logs" "$task/cuda-toolkit"
  cp "$identity" "$task/source-identity.json"
  "$py" - "$archive" "$identity" <<'PY'
import hashlib, json, sys
from pathlib import Path
with open(sys.argv[1], 'rb') as f:
    actual = hashlib.file_digest(f, 'sha256').hexdigest()
assert actual == json.loads(Path(sys.argv[2]).read_text())['source_archive_sha256'], 'Changed source archive'
PY
  tar -xf "$archive" -C "$task/source"
  cp "$identity" "$task/source/source-identity.json"
  # Choice/default/pins come from the exported source, never a model alias.
  # Keep the selected assets task-owned; do not replace the old prepared base model.
  "$py" "$task/source/scripts/setup_speech.py" --download-only \
    --model-dir "$task/models/whisper" >"$task/whisper-identity.json"
  # Install only build tools in this dedicated distro, never a GPU driver/full toolkit.
  apt-get update >"$task/logs/apt.log" 2>&1
  apt-get install -y --no-install-recommends cmake make g++-12 gcc-12 curl ca-certificates libcurl4-openssl-dev >>"$task/logs/apt.log" 2>&1
  "$py" -m pip install --no-cache-dir --no-deps --require-hashes --target "$task/cuda-python" \
    -r "$task/source/requirements-fdb3-cuda.txt" >"$task/logs/cuda-pip.log" 2>&1
  disk_guard
  # Three small, SHA-pinned compiler/header redistributions; cuBLAS comes from
  # the same runtime wheel used by Whisper. Avoid duplicating its large files.
  while read -r name version sha; do
    file="$task/$name.tar.xz"
    curl --fail --location --retry 2 --connect-timeout 20 --max-time 600 \
      "https://developer.download.nvidia.com/compute/cuda/redist/$name/linux-x86_64/$name-linux-x86_64-$version-archive.tar.xz" -o "$file"
    printf '%s  %s\n' "$sha" "$file" | sha256sum -c -
    tar -xJf "$file" --strip-components=1 -C "$task/cuda-toolkit"
  done <<'PINS'
cuda_nvcc 12.4.131 7ffba1ada0e4b8c17e451ac7a60d386aa2642ecd08d71202a0b100c98bd74681
cuda_cudart 12.4.127 0483bff9a36e7a44465db3cd42874f6f70f019297dcf803fbefcbf58d7448c8f
cuda_cccl 12.4.127 e1636f27a142d24e73dfd831c54bbf5575b498fd5900648d7372fae46f824fdf
PINS
  ln -s lib "$task/cuda-toolkit/lib64"
  for file in "$task/cuda-python/nvidia/cublas/include/"*; do ln -s "$file" "$task/cuda-toolkit/include/"; done
  for file in "$task/cuda-python/nvidia/cublas/lib/"*.so*; do ln -s "$file" "$task/cuda-toolkit/lib/"; done
  ln -s libcublas.so.12 "$task/cuda-toolkit/lib/libcublas.so"
  ln -s libcublasLt.so.12 "$task/cuda-toolkit/lib/libcublasLt.so"
  # WSL supplies the NVIDIA driver shim. Never install/replace the Windows driver.
  ln -s /usr/lib/wsl/lib/libcuda.so "$task/cuda-toolkit/lib/libcuda.so"
  export PATH="$task/cuda-toolkit/bin:$PATH"
  export LD_LIBRARY_PATH="$task/cuda-toolkit/lib:/usr/lib/wsl/lib:${LD_LIBRARY_PATH:-}"
  "$py" "$task/source/scripts/fdb3_download_llama_source.py" --output "$task/llama.tar.gz" --cached "${5:-/nonexistent-task-cache}"
  mkdir "$task/llama.cpp"
  tar -xzf "$task/llama.tar.gz" --strip-components=1 -C "$task/llama.cpp"
  disk_guard
  # RTX 4050 is SM89. One compiler job bounds RAM; no GPU inference here.
  # The commit-pinned archive has no .git: build version may truthfully say
  # "0 (unknown)". Source tar hash + binary hash, not fabricated version text,
  # bind this local build to b10930 in build-identity.json.
  timeout --signal=TERM --kill-after=30s 1800s cmake -S "$task/llama.cpp" -B "$task/llama-build" \
    -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_ARCHITECTURES=89 \
    -DCMAKE_C_COMPILER=gcc-12 -DCMAKE_CXX_COMPILER=g++-12 -DCMAKE_CUDA_HOST_COMPILER=g++-12 \
    -DCUDAToolkit_ROOT="$task/cuda-toolkit" -DLLAMA_CURL=ON \
    -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF >"$task/logs/cmake.log" 2>&1
  timeout --signal=TERM --kill-after=30s 3600s cmake --build "$task/llama-build" --target llama-server -j 1 >"$task/logs/build.log" 2>&1
  "$py" - "$task" <<'PY'
import hashlib, json, sys
from pathlib import Path
task = Path(sys.argv[1])
def sha(path):
    with path.open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()
config = json.loads((task/'source/config/fdb3-candidate.json').read_text())
(task/'build-identity.json').write_text(json.dumps({'llama_source_commit': config['llama']['commit'],
    'llama_source_tar_sha256': sha(task/'llama.tar.gz'),
    'llama_binary_sha256': sha(task/'llama-build/bin/llama-server'),
    'cuda_compiler': '12.4.131', 'cuda_architecture': '89', 'build_jobs': 1,
    'note': 'Local archive build, not an official prebuilt binary'}, indent=2))
PY
  printf 'PREPARED_NOT_RUN: %s\n' "$task"
  exit 0
fi

test -f "$task/build-identity.json"
# Recheck the selected pins before any GPU query, service or model startup.
"$py" "$task/source/scripts/setup_speech.py" --check-only --model-dir "$task/models/whisper" \
  >"$task/logs/whisper-verified.json"
export PYTHONPATH="$task/cuda-python:$task/source"
export LD_LIBRARY_PATH="$task/llama-build/bin:$task/cuda-toolkit/lib:$task/cuda-python/nvidia/cublas/lib:$task/cuda-python/nvidia/cudnn/lib:$task/cuda-python/nvidia/cuda_runtime/lib:/usr/lib/wsl/lib"
livekit="$(find /opt/thread-sprint3 -type f -name livekit-server -print -quit)"
test -n "$livekit" || { echo 'Preserved LiveKit binary missing' >&2; exit 2; }
printf '%s  %s\n' 7827d8be422458b7dd9fe6302764232deabab7c0193b60357bcb4649df2dadc5 "$livekit" | sha256sum -c -
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader >"$task/logs/gpu-before.txt"
gpu_free="$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -n 1)"
[ "$gpu_free" -ge 5000 ] || { echo 'Need at least 5000 MiB free VRAM; do not stop another owner automatically' >&2; exit 2; }
"$py" - "$task" <<'PY'
import hashlib, importlib.metadata, json, sys
from pathlib import Path
task = Path(sys.argv[1])
for line in (task/'source/requirements-fdb3.lock').read_text().splitlines():
    if '==' in line and not line.startswith('#'):
        name, version = line.split('==')
        assert importlib.metadata.version(name) == version, f'Prepared dependency drift: {name}'
with (task/'llama-build/bin/llama-server').open('rb') as f:
    assert hashlib.file_digest(f, 'sha256').hexdigest() == json.loads((task/'build-identity.json').read_text())['llama_binary_sha256']
PY
"$task/llama-build/bin/llama-server" --version >"$task/logs/llama-version.txt" 2>&1
"$py" -m pip freeze --all >"$task/logs/runtime-freeze.txt"
reference="${THREAD_WINDOWS_REFERENCE:?Supply the explicit historical Windows archive path for comparison}"
cd "$task/source"
exec timeout --signal=TERM --kill-after=90s 3600s "$py" scripts/fdb3_dispatch_smoke.py \
  --assets "$prepared/assets" --upstream "$prepared/upstream" --whisper "$task/models/whisper" \
  --model "$prepared/models/model.gguf" --llama-server "$task/llama-build/bin/llama-server" \
  --livekit-server "$livekit" --reference "$reference" --output "$task/smoke-five"
