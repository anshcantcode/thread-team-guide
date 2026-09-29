"""Run the local THREAD Kitchen host for the browser and Android clients."""
from pathlib import Path
import argparse
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--whisper', type=Path, required=True, help='Existing SHA-256 pinned small.en directory')
    p.add_argument('--endpoint', default='http://127.0.0.1:8098/v1', help='Existing local llama-server endpoint')
    p.add_argument('--model', default='Qwen3.5-4B')
    p.add_argument('--port', type=int, default=8768)
    p.add_argument('--cuda-bin', type=Path, default=ROOT / '.runtime/llama',
                   help='Windows CUDA DLL directory installed by setup_local.py; process-local only')
    a = p.parse_args()
    if not 1024 <= a.port <= 65535:
        p.error('Port must be between 1024 and 65535')
    # CTranslate2 loads CUDA on the first transcription, after model loading.
    # Use the same pinned CUDA package as the local planner, without changing
    # the user's system PATH or silently falling back to another ASR profile.
    dll_scope = None
    if os.name == 'nt' and os.environ.get('THREAD_FDB3_PROFILE') != 'cpu-component':
        cuda_bin = a.cuda_bin.resolve()
        required = ('cublas64_12.dll', 'cublasLt64_12.dll', 'cudart64_12.dll')
        if any(not (cuda_bin / name).is_file() for name in required):
            p.error('Windows GPU speech requires the pinned CUDA DLLs. Run scripts/setup_local.py or supply --cuda-bin DIRECTORY.')
        os.environ['PATH'] = str(cuda_bin) + os.pathsep + os.environ.get('PATH', '')
        dll_scope = os.add_dll_directory(str(cuda_bin))
    from thread_agent.fdb3_client import create_app
    import uvicorn
    uvicorn.run(create_app(whisper_path=a.whisper, endpoint=a.endpoint, model=a.model),
                host='127.0.0.1', port=a.port, ws_max_size=65536)
    if dll_scope is not None:
        dll_scope.close()

if __name__ == '__main__':
    main()
