"""Offline integrity and oracle checks for a separately held, immutable private bundle.

Acceptance uses load_bundle(), gives ONLY the input case to its existing Driver,
then calls evaluate() after collecting the trace. This module never calls a model.
"""
import argparse
from array import array
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

from PIL import Image

from evaluation.samsung_challenge.semantic_oracle_v2 import evaluate_case


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def relative_file(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Bundle reference escapes its root")
    return path


def load_bundle(root, expected_freeze_sha256=None):
    root = Path(root).resolve()
    if expected_freeze_sha256 is not None and sha(root / "FREEZE.json") != expected_freeze_sha256:
        raise ValueError("Bundle freeze does not match the independently recorded identity")
    freeze = json.loads((root / "FREEZE.json").read_text(encoding="utf-8"))
    if not {"inputs.jsonl", "answers.private.jsonl", "provenance.json"}.issubset(freeze["files"]):
        raise ValueError("Freeze omits a required bundle file")
    for name, info in freeze["files"].items():
        path = relative_file(root, name)
        if sha(path) != info["sha256"] or path.stat().st_size != info["bytes"]:
            raise ValueError("Frozen bundle changed: " + name)
    repo = Path(__file__).resolve().parents[2]
    for name, digest in freeze["oracle_sources"].items():
        if sha(relative_file(repo, name)) != digest:
            raise ValueError("Frozen oracle source changed: " + name)
    cases = read_rows(root / "inputs.jsonl")
    answers = read_rows(root / "answers.private.jsonl")
    if len({row["id"] for row in cases}) != len(cases) or len({row["id"] for row in answers}) != len(answers):
        raise ValueError("Duplicate case or answer identifier")
    answers = {row["id"]: row for row in answers}
    if set(answers) != {case["id"] for case in cases}:
        raise ValueError("Inputs and private answer identities differ")
    if Counter(case["mode"] for case in cases) != {"e2e_text": 6, "e2e_audio": 6, "e2e_visual": 6}:
        raise ValueError("Expected exactly six independent cases in each modality")
    allowed = {"user_speech_chunk": {"text", "end_of_turn"}, "user_audio_chunk": {"audio_ref", "end_of_turn"},
               "video_frame": {"image_ref", "frame_id"}, "interruption": {"text"}, "scenario_end": set()}
    for case in cases:
        if case.get("injected_plans") or case.get("requirements") or any(key in case for key in ("oracle", "expected", "answer")):
            raise ValueError("Semantic inputs contain an answer or unmet prerequisite")
        for step in case["steps"]:
            event = step["event"]
            if set(event["payload"]) - allowed[event["event_type"]]:
                raise ValueError("Unexpected participant payload field (possible annotation leakage)")
            for key in ("audio_ref", "image_ref"):
                if key in event["payload"]:
                    name = event["payload"][key]
                    if name not in freeze["files"] or not relative_file(root, name).is_file():
                        raise ValueError("Media reference is not frozen")
    return cases, answers, freeze


def evaluate(case, answer, trace):
    """Expected values attach after execution; the Driver never needs this copy."""
    if case["id"] != answer["id"]:
        raise ValueError("Answer belongs to another case")
    return evaluate_case({**case, "oracle": answer["oracle"]}, trace)


def check_oracles(cases, answers):
    counts = Counter()
    for case in cases:
        answer = answers[case["id"]]
        witness = answer["witness"]
        for positive in [witness, *answer.get("alternate_witnesses", [])]:
            result = evaluate(case, answer, positive)
            if not result["passed"]:
                raise AssertionError({"case": case["id"], "synthetic_witness_failures": result["failures"]})
            counts["synthetic_positive_traces"] += 1
        negatives = {"silent": []}
        negatives["unrequested_tool"] = witness + [{"kind": "action", "action": "tool_call", "t_ms": 1500,
                                                     "api_name": "never_declared", "call_id": "rogue", "args": {}}]
        if any(rule["op"] in {"grounded", "binding"} for rule in answer["oracle"]):
            negatives["no_actual_results"] = [row for row in witness if row.get("kind") != "tool_completed"]
            bad = deepcopy(witness)
            for row in bad:
                if row.get("action") == "final_response":
                    row["payload"]["text"] = "Unobserved fabricated answer."
            negatives["fabricated_answer"] = bad
        if case["mode"] != "e2e_text":
            negatives["no_media_read"] = [row for row in witness if row.get("kind") != "media_access"]
        for label, trace in negatives.items():
            if evaluate(case, answer, trace)["passed"]:
                raise AssertionError({"case": case["id"], "escaped_negative": label})
            counts[label] += 1
    return dict(counts)


def preflight(root, ffmpeg="ffmpeg", expected_freeze_sha256=None):
    from participant.media import MediaLoader

    root = Path(root).resolve()
    cases, answers, freeze = load_bundle(root, expected_freeze_sha256)
    loader = MediaLoader(root)
    media = []
    provenance = json.loads((root / "provenance.json").read_text(encoding="utf-8"))
    for source in provenance["assets"]:
        path = relative_file(root, source["path"])
        record = {key: source[key] for key in ("path", "origin", "licence", "synthetic", "sha256", "bytes")}
        raw, mime = loader._read(source["path"], "audio" if source["kind"] == "speech" else "image")
        if hashlib.sha256(raw).hexdigest() != source["sha256"] or len(raw) != source["bytes"]:
            raise ValueError("Actual candidate media loader returned different bytes")
        record.update(candidate_loader_validated=True, mime_type=mime)
        if source["kind"] == "speech":
            decoded = subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", "16000", "pipe:1"],
                                     check=True, capture_output=True, timeout=30)
            samples = array("h", decoded.stdout)
            if not samples or not max(abs(value) for value in samples):
                raise ValueError("Decoded audio is empty or silent")
            record.update(decoded=True, pcm_samples=len(samples), duration_seconds=round(len(samples)/16000, 3),
                          peak=max(abs(value) for value in samples),
                          rms=round((sum(value*value for value in samples)/len(samples))**0.5, 2),
                          human_recording=False, human_listening_review=False)
        else:
            with Image.open(path) as image:
                image.load()
                record.update(decoded=True, format=image.format, width=image.width, height=image.height)
        media.append(record)
    if Counter(source["kind"] for source in provenance["assets"]) != {"speech": 6, "image": 6}:
        raise ValueError("Expected six acquired speech clips and six acquired images")
    return {"authored_cases": len(cases), "authored_modes": dict(Counter(case["mode"] for case in cases)),
            "participant_runs": 0, "semantic_passes": 0, "provider_calls": 0,
            "freeze_sha256": sha(root / "FREEZE.json"), "preflight_source_sha256": sha(__file__),
            "candidate_media_source_sha256": sha(Path(__import__("participant.media", fromlist=["__file__"]).__file__)),
            "oracle_controls": check_oracles(cases, answers), "media": media,
            "limits": "Synthetic witness checks and media decoding are not participant/model understanding. No human speech/accent or photographic robustness claim."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--freeze-sha256", required=True, help="Freeze hash received separately from the private author")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Output exists; preserve every attempt")
    result = preflight(args.bundle, args.ffmpeg, args.freeze_sha256)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in ("authored_cases", "participant_runs", "semantic_passes", "provider_calls", "freeze_sha256", "oracle_controls")}))


if __name__ == "__main__":
    main()
