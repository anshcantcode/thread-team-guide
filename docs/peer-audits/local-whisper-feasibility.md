# Local Whisper feasibility: four public audio clips

Branch `codex/local-whisper-feasibility`, based on `origin/codex/provider-route-benchmark` at `09f91640dd833cab7efaa387cd52847260802c35`.

## Setup and command

Used the isolated DUET venv and its cached pinned Hugging Face snapshot: `dropbox-dash/faster-whisper-large-v3-turbo` at `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`. Only `faster_whisper` was imported; inference was direct, offline, with no DUET runtime imports and no provider keys. The checkpoint and audio are under `C:\Users\ANSH\.codex\worktrees\provider-benchmark\samsung voice interupt model\.runtime\competitor-research\duet-git`.

Device capture commands:

```powershell
$Py = 'C:\Users\ANSH\.codex\worktrees\provider-benchmark\samsung voice interupt model\.runtime\competitor-research\duet-git\.venv-duet\Scripts\python.exe'
& $Py --version
& $Py -c "import faster_whisper, torch, ctranslate2, sys; print('python',sys.executable); print('faster_whisper',faster_whisper.__version__); print('ctranslate2',ctranslate2.__version__); print('torch',torch.__version__); print('cuda_available',torch.cuda.is_available()); print('torch_cuda_version',torch.version.cuda); print('device',torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
nvidia-smi --query-gpu=index,name,driver_version,memory.total --format=csv
```

From that directory, this PowerShell command ran one unmeasured warm-up decode, then one timed decode per clip. The transcription settings match the pinned DUET ASR settings (`en`, beam 5, temperature 0, word timestamps, no previous-text conditioning); no DUET code was imported.

```powershell
$V = 'C:\Users\ANSH\.codex\worktrees\provider-benchmark\samsung voice interupt model\.runtime\competitor-research\duet-git\.venv-duet'
$env:PATH = "$V\Lib\site-packages\torch\lib;$env:PATH"
$env:HF_HUB_OFFLINE = '1'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
$Py = "$V\Scripts\python.exe"
@"
import json, re, time
from faster_whisper import WhisperModel

repo = "dropbox-dash/faster-whisper-large-v3-turbo"
revision = "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf"
clips = [
    ("pub05 turn1", "audio/pub_05_turn1.mp3", ["Boston", "Austin"]),
    ("pub05 turn2", "audio/pub_05_turn2.mp3", ["Boston"]),
    ("pub06 part1", "audio/pub_06_turn1_part1.mp3", ["Boston"]),
    ("pub06 part2", "audio/pub_06_turn1_part2.mp3", ["New York"]),
]
load_started = time.perf_counter()
model = WhisperModel(repo, device="cuda", compute_type="float16", revision=revision)
load_seconds = time.perf_counter() - load_started

def infer(path):
    started = time.perf_counter()
    segments, info = model.transcribe(
        path, language="en", beam_size=5, temperature=0.0,
        word_timestamps=True, condition_on_previous_text=False,
    )
    segments = list(segments)
    elapsed = time.perf_counter() - started
    words = [(w.word.strip(), float(w.probability)) for s in segments for w in (s.words or [])]
    text = " ".join(s.text.strip() for s in segments)
    return elapsed, text, words

warm = infer(clips[0][1])
print(json.dumps({"model": repo, "revision": revision, "device": "cuda", "compute_type": "float16", "load_seconds": round(load_seconds, 3), "warmup_clip": clips[0][0], "warmup_inference_seconds": round(warm[0], 3)}))
for name, path, destinations in clips:
    elapsed, transcript, words = infer(path)
    norm = [(re.sub(r"^[^a-z0-9']+|[^a-z0-9']+$", "", token.lower()), probability) for token, probability in words]
    confidence = {}
    for value in destinations:
        target_words = re.findall(r"[a-z0-9']+", value.lower())
        found = [max((p for token, p in norm if token == word), default=None) for word in target_words]
        confidence[value] = {"word_probabilities": found, "mean_detected": (sum(p for p in found if p is not None) / sum(p is not None for p in found)) if any(p is not None for p in found) else None}
    print(json.dumps({"clip": name, "path": path, "warm_inference_seconds": round(elapsed, 3), "transcript": transcript, "destination_confidence": confidence, "words": [{"token": token, "probability": round(p, 4)} for token, p in words]}, ensure_ascii=False))
"@ | & $Py -
```

The first attempt failed because `cublas64_12.dll` was not on the process DLL path. It was already present, along with cuDNN 9, in the venv's `torch\lib`; prepending that existing directory fixed CUDA loading without installing anything.

## Result

Runtime: Python 3.11.9, faster-whisper 1.2.1, CTranslate2 4.8.2, PyTorch 2.10.0+cu128; CUDA available (12.8). GPU: NVIDIA GeForce RTX 4050 Laptop GPU, driver 592.82, 6141 MiB reported memory.

Model load from cache took **6.529 s**. The first pub05 turn1 decode was the unmeasured warm-up (**2.179 s**). Timed calls below were after that warm-up; time covers `transcribe()` through consuming all returned segments, excluding model load.

| Clip | Transcript | Destination word probability | Warm inference |
| --- | --- | --- | ---: |
| pub05 turn1 | “I broke off my head to Austin.” | Boston: not emitted; Austin: **0.4751** | **0.456 s** |
| pub05 turn2 | “I said Boston.” | Boston: **0.9771** | **0.402 s** |
| pub06 part1 | “Book a flight to Boston.” | Boston: **0.9844** | **0.443 s** |
| pub06 part2 | “Actually make that New York” | New: **0.6992**; York: **0.9912**; mean: **0.8452** | **0.427 s** |

## Limits

One timed warm pass per clip on this RTX 4050 is a feasibility datapoint, not a stable benchmark. Word probabilities are model scores, not calibrated probabilities. This measures ASR only; it does not evaluate streaming aggregation, clarification behavior, or end-to-end response latency.
