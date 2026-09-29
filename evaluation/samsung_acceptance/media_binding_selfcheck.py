"""Offline binding boundary checks; no participant/provider execution."""
import argparse
import asyncio
from copy import deepcopy
import json
import io
import os
from pathlib import Path
import tempfile
import sys
import struct
import threading
import wave
import zlib

from .media_bindings import assets_unchanged, invalid_media_attempts, media_evidence, observe_media_reads, runtime_environment, sha, stage_case


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    checks = {}
    with tempfile.TemporaryDirectory(prefix="acceptance-binding-") as directory:
        root = Path(directory)
        source, staging = root / "source", root / "staging"
        source.mkdir()
        raw = (args.kit / "frames/pub_07_f017.png").read_bytes()
        (source / "asset.png").write_bytes(raw)
        case = {"id": "binding-control", "partition": "development", "steps": [{"event": {
            "event_type": "video_frame", "payload": {"image_ref": "frame.png"}}}],
            "requirements": [{"kind": "media_asset", "media_ref": "frame.png",
                              "status": "available_from_kit", "source_kit_ref": "frames/pub_07_f017.png"}]}
        binding = {"case_id": case["id"], "partition": case["partition"], "original_line_sha256": "known-line",
                   "variant": "exact_original", "assets": [{"original_ref": "frame.png", "bound_ref": "asset.png",
                   "state": "materialized", "sha256": sha(raw), "bytes": len(raw), "mime_type": "image/png",
                   "provenance": {"human_checked_content": False}}]}
        count = 0
        def stage(c=case, b=binding, variant="original"):
            nonlocal count
            count += 1
            return stage_case(c, "known-line", b, source, staging / str(count), args.kit.resolve(), variant)
        staged, record = stage()
        checks["exact_official_bytes_ready"] = record["status"] == "ready" and staged == case and assets_unchanged(record)
        previous = (Path.cwd(), os.environ.get("PARTICIPANT_MEDIA_ROOT"))
        with runtime_environment(record):
            checks["separate_empty_cwd_and_explicit_media_root"] = (Path.cwd() != Path(record["media_root"])
                and not list(Path.cwd().iterdir()) and os.environ["PARTICIPANT_MEDIA_ROOT"] == record["media_root"])
        checks["environment_restored"] = previous == (Path.cwd(), os.environ.get("PARTICIPANT_MEDIA_ROOT"))
        for name, change in (
            ("wrong_line_rejected", lambda b: b.update(original_line_sha256="other-line")),
            ("wrong_hash_rejected", lambda b: b["assets"][0].update(sha256="0" * 64)),
            ("escape_rejected", lambda b: b["assets"][0].update(bound_ref="../asset.png")),
            ("variant_not_original", lambda b: b.update(variant="synthetic-v1")),
        ):
            bad = deepcopy(binding)
            change(bad)
            checks[name] = stage(b=bad)[1]["status"] == "blocked"
        human = deepcopy(case)
        human["requirements"][0] = {"kind": "media_asset", "media_ref": "frame.png", "status": "requires_acquisition"}
        checks["human_claim_not_inferred"] = stage(c=human)[1]["status"] == "blocked"
        reviewed_synthetic = deepcopy(binding)
        reviewed_synthetic["assets"][0]["provenance"] = {"human_checked_content": True,
            "kind": "synthetic_tts_transform", "creator_or_source": "generator", "capture_conditions": "synthetic"}
        checks["human_review_does_not_turn_synthetic_into_capture"] = stage(c=human, b=reviewed_synthetic)[1]["status"] == "blocked"
        checks["source_hash_without_success_not_consumption"] = not media_evidence(case, record, [
            {"status": "timeout", "input_media": [{"sha256": sha(raw), "bytes": len(raw)}]}])["passed"]
        checks["successful_current_bytes_required"] = media_evidence(case, record, [
            {"status": 200, "input_media": [{"sha256": sha(raw), "bytes": len(raw)}]}])["passed"]
        checks["wrong_bytes_not_consumption"] = not media_evidence(case, record, [
            {"status": 200, "input_media": [{"sha256": "unrelated", "bytes": len(raw)}]}])["passed"]
        invalid_records = []
        for kind, contents in (("ensure_absent", None), ("write_bytes", b"broken")):
            invalid = deepcopy(case)
            invalid["requirements"][0] = {"kind": "media_asset", "media_ref": "frame.png", "status": "stage_locally",
                "stage": {"operation": kind, **({"hex": contents.hex()} if contents is not None else {})}}
            bound = deepcopy(binding)
            bound["assets"][0].update(bound_ref="absent.png" if contents is None else "corrupt.png",
                state="expected_absent" if contents is None else "staged_corrupt", bytes=0 if contents is None else len(contents),
                sha256=None if contents is None else sha(contents))
            if contents is not None:
                (source / "corrupt.png").write_bytes(contents)
            invalid_case, invalid_record = stage(c=invalid, b=bound)
            invalid_records.append((kind, invalid_case, invalid_record))
            checks[kind + "_is_explicit_original_fixture"] = invalid_record["status"] == "ready" and media_evidence(invalid, invalid_record, [])["passed"]
        Path(record["assets"][0]["staged"]).write_bytes(b"changed")
        checks["mutation_detected"] = not assets_unchanged(record)
        clip = io.BytesIO()
        with wave.open(clip, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(8000)
            wav.writeframes(b"\x00\x00" * 80)
        (source / "speech.wav").write_bytes(clip.getvalue())
        audio = {"id": "audio-variant", "partition": "development", "steps": [{"event": {
            "event_type": "user_audio_chunk", "payload": {"audio_ref": "clip.mp3", "duration_ms": 999}}}],
            "requirements": [{"kind": "media_asset", "media_ref": "clip.mp3", "status": "requires_acquisition"}]}
        audio_binding = {"case_id": "audio-variant", "partition": "development", "original_line_sha256": "known-line",
            "variant": "synthetic-v1", "variant_id": "audio-variant.synthetic-v1", "assets": [{"original_ref": "clip.mp3",
            "bound_ref": "speech.wav", "state": "materialized", "sha256": sha(clip.getvalue()), "bytes": len(clip.getvalue()),
            "mime_type": "audio/wav", "duration_ms": 10, "provenance": {"human_checked_content": False}}]}
        audio_case, audio_record = stage(c=audio, b=audio_binding, variant="synthetic-v1")
        checks["wav_variant_gets_wav_reference_and_actual_hint"] = audio_record["status"] == "ready" and audio_case["steps"][0]["event"]["payload"] == {"audio_ref": "clip.wav", "duration_ms": 10}
        checks["variant_not_human_original"] = audio_record["original_recipe"] is False and audio_record["variant_id"] == "audio-variant.synthetic-v1" and audio["steps"][0]["event"]["payload"]["audio_ref"] == "clip.mp3"
        from participant.media import MediaError, MediaLoader
        from evaluation.samsung_challenge.oracle import evaluate_case
        class ReadProbe:
            def __init__(self):
                self.trace = []
            def log(self, **entry):
                self.trace.append({"t_ms": 0, **entry})
        probe = ReadProbe()
        checks["generic_setup_refusal_is_not_invalid_media_handling"] = all(
            not invalid_media_attempts(r, [{"kind": "action", "text": "Unable to process this request."}])["passed"]
            for _, _, r in invalid_records)
        for kind, invalid_case, invalid_record in invalid_records:
            invalid_probe = ReadProbe()
            with observe_media_reads(invalid_probe, invalid_record, MediaLoader):
                try:
                    asyncio.run(MediaLoader(invalid_record["media_root"]).prepare(
                        [invalid_case["steps"][0]["event"]]))
                except MediaError:
                    pass
            checks[kind + "_actual_failure_proves_attempt_without_success"] = (
                invalid_media_attempts(invalid_record, invalid_probe.trace)["passed"]
                and len(invalid_probe.trace) == 1 and invalid_probe.trace[0].get("status") == "read_error")
        checks["staging_does_not_fabricate_read"] = not probe.trace
        with observe_media_reads(probe, audio_record, MediaLoader):
            asyncio.run(MediaLoader(audio_record["media_root"]).prepare([audio_case["steps"][0]["event"]]))
        verdict = evaluate_case({"oracle": [{"id": "read", "op": "media", "media_ref": "clip.mp3"}]}, probe.trace)
        checks["actual_threaded_wav_read_maps_to_original_oracle"] = verdict["passed"] and probe.trace[0]["sha256"] == sha(clip.getvalue())
        checks["observer_hooks_restored"] = sys.getprofile() is None and threading.getprofile() is None
        wrong = deepcopy(audio_record)
        wrong["assets"][0]["sha256"] = "0" * 64
        mismatch_probe = ReadProbe()
        with observe_media_reads(mismatch_probe, wrong, MediaLoader):
            asyncio.run(MediaLoader(audio_record["media_root"]).prepare([audio_case["steps"][0]["event"]]))
        checks["unexpected_read_bytes_fail_observation"] = any(r["kind"] == "adapter_error" for r in mismatch_probe.trace) and not any(r["kind"] == "media_access" for r in mismatch_probe.trace)
        header = b"IHDR" + struct.pack(">IIBBBBB", 20000, 20000, 8, 2, 0, 0, 0)
        bomb = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + header + struct.pack(">I", zlib.crc32(header)) + b"\0\0\0\0IEND\xaeB`\x82"
        (source / "huge.png").write_bytes(bomb)
        huge_binding = deepcopy(binding)
        huge_binding["assets"][0].update(bound_ref="huge.png", bytes=len(bomb), sha256=sha(bomb))
        checks["image_header_bomb_retained_as_blocked"] = stage(b=huge_binding)[1]["status"] == "blocked"
    report = {"scope": "Synthetic binding controls, including actual MediaLoader helper reads; zero full ParticipantAgent executions or provider calls", "checks": checks}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": sum(checks.values()), "controls": len(checks), "out": str(args.out)}))
    raise SystemExit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    main()
