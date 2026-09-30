"""Prepare SHA-pinned English Whisper assets; optional warm-up is always CPU-only.

Select THREAD_FDB3_WHISPER_MODEL=base.en|small.en. The single default and both
pin sets live in config/fdb3-candidate.json. No microphone or benchmark is read.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.fdb3_config import load_config, verify_whisper


def prepare_model(directory=None, *, download_only=False, check_only=False):
    config = load_config()
    selected = config["whisper"]
    directory = Path(directory) if directory is not None else (
        ROOT / ".runtime" / ("whisper-" + selected["name"].replace(".", "-")))
    # Preserve existing assets: a populated wrong/partial directory is an error,
    # not permission to overwrite it or silently download a different model.
    if not check_only and (not directory.exists() or not any(directory.iterdir())):
        from huggingface_hub import snapshot_download
        snapshot_download(selected["repo"], revision=selected["revision"],
                          allow_patterns=list(selected["sha256"]),
                          local_dir=str(directory), token=False)
    identity = verify_whisper(directory, config=config)
    if not (download_only or check_only):
        from faster_whisper import WhisperModel
        WhisperModel(str(directory), device="cpu", compute_type="int8",
                     cpu_threads=2, num_workers=1, local_files_only=True)
    return {"directory": str(directory.resolve()), **identity,
            "status": "VERIFIED" if check_only else "ASSETS_READY" if download_only else "CPU_READY",
            "warmup_performed": not (download_only or check_only),
            "device": "cpu", "compute_type": "int8", "benchmark_recordings": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, help="Local model directory (must match selected pins)")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--download-only", action="store_true", help="Download/verify, without loading a model")
    modes.add_argument("--check-only", action="store_true", help="Offline hash check only; no download or model load")
    args = parser.parse_args()
    try:
        print(json.dumps(prepare_model(args.model_dir, download_only=args.download_only,
                                       check_only=args.check_only), indent=2))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
