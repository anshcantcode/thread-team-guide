"""Render independently authored diagnostic fixtures to upstream-shaped inputs.

Development profile only: Windows SAPI synthetic speech, never human or
held-out audio. Output lands in an ignored local directory; the tracked spec
plus hashes in provenance.json reproduce it. expected_tool_calls is written
only to evaluator metadata, never to the transcript or audio.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from thread_agent.fdb3_evidence import file_hash

RATE = 24000
VOICE = "Microsoft David Desktop"  # Default; a spec may name another installed voice.
SCRIPT = '''param([string]$Root)
Add-Type -AssemblyName System.Speech
$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
  $voice.SelectVoice([IO.File]::ReadAllText((Join-Path $Root 'voice.txt')))
  $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(%d, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
  $voice.SetOutputToWaveFile((Join-Path $Root 'out.wav'), $format)
  $voice.Speak([IO.File]::ReadAllText((Join-Path $Root 'text.txt')))
} finally { $voice.Dispose() }
''' % RATE


def synthesize(text, voice=VOICE):
    with tempfile.TemporaryDirectory(prefix="thread-fixture-") as directory:
        root = Path(directory)
        (root / "text.txt").write_text(text, encoding="utf-8")
        (root / "voice.txt").write_text(voice, encoding="utf-8")
        (root / "speak.ps1").write_text(SCRIPT, encoding="utf-8")
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(root / "speak.ps1"), str(root)],
                       check=True, capture_output=True, timeout=60)
        with wave.open(str(root / "out.wav"), "rb") as audio:
            if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) != (RATE, 1, 2):
                raise ValueError("Unexpected SAPI output format")
            return audio.readframes(audio.getnframes())


def silence(ms):
    return b"\0\0" * (RATE * ms // 1000)


def metadata(spec):
    spoken = " ".join(segment["text"] for segment in spec["segments"])
    return {"id": spec["id"], "domain": spec["domain"], "title": spec["title"], "difficulty": spec["difficulty"],
            "dialogue": [{"user": spoken, "user_annotated": spoken, "ai": spec["ai"]}],
            "acting_notes": "Synthetic authored speech; pauses are inserted silence.",
            "disfluency_features": [], "expected_tool_calls": spec["expected_tool_calls"],
            "num_expected_calls": len(spec["expected_tool_calls"]),
            "state_rollback_test": spec["family"] in {"correction_after_pause", "retraction_safety"},
            "latency_profile": "normal", "authored_family": spec["family"]}


def render(spec_path, output, only=None):
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if spec.get("exposure") != "independently_authored":
        raise ValueError("Only independently authored fixture specs are rendered here")
    output.mkdir(parents=True, exist_ok=False)
    voice = spec.get("voice", VOICE)
    provenance = {"created_at": time.time(), "spec": str(spec_path.relative_to(ROOT)), "spec_sha256": file_hash(spec_path),
                  "source": spec["provenance"], "voice": voice + " (Windows SAPI development profile)",
                  "paid_requests": 0, "qualification": False, "files": {}}
    for fixture in spec["fixtures"]:
        if only and fixture["id"] not in only:
            continue
        pcm = [silence(1000)]
        for segment in fixture["segments"]:
            pcm.append(synthesize(segment["text"], voice))
            pcm.append(silence(segment.get("pause_after_ms", 0)))
        pcm.append(silence(2500))
        directory = output / fixture["id"]
        directory.mkdir()
        with wave.open(str(directory / "input.wav"), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(RATE)
            audio.writeframes(b"".join(pcm))
        # Faithful transcript of the spoken words, not an answer summary.
        (directory / "transcript.txt").write_text(" ".join(s["text"] for s in fixture["segments"]), encoding="utf-8")
        (directory / "metadata.json").write_text(json.dumps(metadata(fixture), indent=2), encoding="utf-8")
        for name in ("input.wav", "transcript.txt", "metadata.json"):
            provenance["files"][fixture["id"] + "/" + name] = file_hash(directory / name)
    (output / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    return provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=ROOT / "evaluation/fdb3_authored/fixtures.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()
    render(args.spec.resolve(), args.output.resolve(), set(args.only or ()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
