"""Download pinned, hash-verified model assets and official llama.cpp binaries."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parent.parent / '.runtime'
REV='e87f176479d0855a907a41277aca2f8ee7a09523'
FILES=[
 ('models/Qwen3.5-4B-Q4_K_M.gguf',f'https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/{REV}/Qwen3.5-4B-Q4_K_M.gguf','00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4'),
 ('models/mmproj-F16.gguf',f'https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/{REV}/mmproj-F16.gguf','cd88edcf8d031894960bb0c9c5b9b7e1fea6ebee02b9f7ce925a00d12891f864'),
 ('downloads/llama.zip','https://github.com/ggml-org/llama.cpp/releases/download/b10930/llama-b10930-bin-win-cuda-12.4-x64.zip','7d07deb817f7f380d1da119c76967d7ead0a4dbb02456c0edfda82a99122fed6'),
 ('downloads/cudart.zip','https://github.com/ggml-org/llama.cpp/releases/download/b10930/cudart-llama-bin-win-cuda-12.4-x64.zip','8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6'),
]


def digest(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()


def download(entry):
    name,url,expected=entry
    path=ROOT/name; path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and digest(path)==expected:
        print(f'Verified existing {name}',flush=True); return path
    temporary=path.with_suffix(path.suffix+'.part')
    print(f'Downloading {name}',flush=True)
    with urllib.request.urlopen(url,timeout=120) as response,temporary.open('wb') as output:
        total=0; reported=0
        while chunk:=response.read(1024*1024):
            output.write(chunk); total+=len(chunk)
            if total-reported>=256*1024*1024:
                print(f'{name}: {total//(1024*1024)} MiB received',flush=True); reported=total
    if digest(temporary)!=expected: raise ValueError(f'SHA-256 mismatch for {name}; refusing to use it.')
    temporary.replace(path)
    print(f'Verified {name}',flush=True)
    return path


if __name__=='__main__':
    with ThreadPoolExecutor(max_workers=4) as pool: paths=list(pool.map(download,FILES))
    target=(ROOT/'llama').resolve(); target.mkdir(exist_ok=True)
    for path in paths:
        if path.suffix=='.zip':
            with zipfile.ZipFile(path) as archive:
                for entry in archive.infolist():
                    resolved=(target/entry.filename).resolve()
                    if not resolved.is_relative_to(target): raise ValueError('Archive member escapes runtime directory.')
                archive.extractall(target)
    print('Local model and CUDA runtime ready. No model training was performed.',flush=True)
    from setup_speech import model
