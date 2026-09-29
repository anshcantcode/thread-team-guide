"""Prepare a label-free runtime contract and complete evaluator-side audio inventory."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import wave
import zipfile


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=False)
    runtime = args.destination / "agent-contract"
    runtime.mkdir()
    for name in ("mock_apis.py", "latency_injector.py", "cascaded_agent.py"):
        shutil.copyfile(args.upstream / "v3" / name, runtime / name)
    data = args.destination / "evaluator-data"
    data.mkdir()
    with zipfile.ZipFile(args.archive) as archive:
        for info in archive.infolist():
            target = (data / info.filename).resolve()
            if not target.is_relative_to(data.resolve()):
                raise ValueError("Unsafe archive member")
        archive.extractall(data)
    rows = []
    for path in sorted(data.rglob("input.wav")):
        with wave.open(str(path), "rb") as audio:
            # Read every frame, not just a potentially misleading header.
            frames = audio.readframes(audio.getnframes())
            if len(frames) != audio.getnframes() * audio.getnchannels() * audio.getsampwidth():
                raise ValueError("Truncated audio")
            row = {"recording": path.parent.name, "relative_path": path.relative_to(data).as_posix(),
                   "sha256": digest(path), "frames": audio.getnframes(), "sample_rate": audio.getframerate(),
                   "channels": audio.getnchannels(), "duration_seconds": audio.getnframes() / audio.getframerate()}
        metadata = path.parent / "metadata.json"
        if not metadata.is_file():
            raise ValueError("Missing evaluator metadata")
        row["metadata_sha256"] = digest(metadata)
        rows.append(row)
    result = {"upstream_commit": subprocess.check_output(["git", "-C", str(args.upstream), "rev-parse", "HEAD"], text=True).strip(),
              "archive_sha256": digest(args.archive), "expected": 100, "observed": len(rows),
              "contract_hashes": {p.name: digest(p) for p in runtime.iterdir()}, "recordings": rows}
    (args.destination / "dataset-manifest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    if len(rows) != 100:
        raise ValueError(f"Expected 100 recordings, found {len(rows)}")
    print(json.dumps({"expected":100,"decoded":len(rows),"manifest_sha256":digest(args.destination / "dataset-manifest.json")}))


if __name__ == "__main__":
    main()
