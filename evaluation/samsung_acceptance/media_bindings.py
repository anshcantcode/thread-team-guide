"""Stage predeclared media bindings; annotations never enter runtime events.

Original human-capture requirements cannot be satisfied by synthetic variants.
Only file references (and declared synthetic duration hints) may be overlaid.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import threading
import wave

from PIL import Image


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load_bindings(path):
    raw = path.read_text(encoding="utf-8")
    rows = ([json.loads(line) for line in raw.splitlines() if line.strip()]
            if path.suffix == ".jsonl" else json.loads(raw))
    if isinstance(rows, dict):
        rows = rows["cases"]
    result = {r["case_id"]: r for r in rows}
    if len(result) != len(rows):
        raise ValueError("Duplicate binding case IDs")
    return result


def beneath(root, reference):
    if not isinstance(reference, str) or not reference or ":" in reference or "\\" in reference:
        raise ValueError("Binding paths must be relative POSIX file references")
    relative = Path(reference)
    path = root / relative
    if relative.is_absolute() or ".." in relative.parts or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Binding path escapes its declared root or is a symlink")
    return path


def stage_case(case, line_sha, binding, asset_root, stage_root, kit, variant="original"):
    record = {"case_id": case["id"], "original_line_sha256": line_sha,
              "status": "blocked", "executed": False, "original_recipe": variant == "original"}
    if not binding:
        return None, {**record, "reason": "No predeclared asset binding"}
    try:
        if binding["original_line_sha256"] != line_sha or binding["partition"] != case["partition"]:
            raise ValueError("Binding does not identify these exact frozen case bytes/partition")
        record.update(variant=binding["variant"], binding=binding)
        original = binding["variant"] in {"exact_original", "original-invalid"}
        if (variant == "original" and not original) or (variant != "original" and binding["variant"] != variant):
            raise ValueError("Original recipe unavailable or requested variant does not match")
        requirements = case.get("requirements", [])
        if any(r["kind"] not in {"media_asset", "environment"} for r in requirements):
            raise ValueError("Unimplemented fixture requirement")
        assets = {a["original_ref"]: a for a in binding["assets"]}
        media_requirements = {r["media_ref"]: r for r in requirements if r["kind"] == "media_asset"}
        refs = {s["event"].get("payload", {}).get(k) for s in case["steps"] for k in ("audio_ref", "image_ref")}
        refs.discard(None)
        if len(assets) != len(binding["assets"]) or set(assets) != set(media_requirements) or refs != set(assets):
            raise ValueError("Every actual event media reference needs exactly one requirement and binding")
        environment = [r for r in requirements if r["kind"] == "environment"]
        if binding.get("environment", environment) != environment:
            raise ValueError("Binding changes an environment recipe")
        style = environment[0]["relative_ref_style"] if environment else "normal"
        if len(environment) > 1 or style not in {"normal", "spaces_in_root", "unicode_root", "absolute_within_root"}:
            raise ValueError("Unimplemented cwd fixture")
        root_name = {"spaces_in_root": "media root with spaces", "unicode_root": "media-\u00e9-\u6d4b\u8bd5"}.get(style, "media")
        root = beneath(stage_root, case["id"]) / root_name
        root.mkdir(parents=True, exist_ok=False)
        staged, normalized_assets = deepcopy(case), []
        for ref, requirement in media_requirements.items():
            asset = assets[ref]
            source = beneath(asset_root, asset["bound_ref"])
            runtime_ref = ref.replace("\\", "/")
            if not original and asset["state"] == "materialized":
                runtime_ref = Path(runtime_ref).with_suffix(source.suffix).as_posix()
            destination = beneath(root, runtime_ref)
            state = asset["state"]
            if state == "expected_absent":
                if source.exists() or asset.get("sha256") is not None or asset.get("bytes") != 0:
                    raise ValueError("Expected-absent binding has bytes or an existing source")
                if requirement.get("stage", {}).get("operation") != "ensure_absent":
                    raise ValueError("Missing file is not the authored fixture")
                raw = None
            elif state in {"materialized", "staged_corrupt"}:
                if not source.is_file() or source.stat().st_size > 8_000_000:
                    raise ValueError("Asset missing or too large")
                raw = source.read_bytes()
                if sha(raw) != asset["sha256"] or len(raw) != asset["bytes"]:
                    raise ValueError("Asset bytes differ from their predeclared identity")
                if state == "staged_corrupt" and (requirement.get("stage", {}).get("operation") != "write_bytes"
                        or raw != bytes.fromhex(requirement["stage"]["hex"])):
                    raise ValueError("Corruption bytes differ from original fixture")
                if state == "materialized":
                    supported = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                                 ".webp": "image/webp", ".wav": "audio/wav", ".mp3": "audio/mpeg"}
                    if supported.get(destination.suffix.lower()) != asset.get("mime_type"):
                        raise ValueError("Staged reference extension differs from materialized MIME")
                    if asset.get("mime_type", "").startswith("image/"):
                        with Image.open(io.BytesIO(raw)) as image:
                            if image.width * image.height > 12_000_000:
                                raise ValueError("Image exceeds candidate pixel limit")
                            if Image.MIME.get(image.format) != asset["mime_type"]:
                                raise ValueError("Image MIME differs from binding")
                            image.verify()
                    elif asset.get("mime_type") == "audio/wav":
                        with wave.open(io.BytesIO(raw)) as audio:
                            if audio.getnframes() <= 0 or audio.getframerate() <= 0:
                                raise ValueError("Empty audio")
                            if len(audio.readframes(audio.getnframes())) != audio.getnframes() * audio.getnchannels() * audio.getsampwidth():
                                raise ValueError("Truncated audio")
                    elif asset.get("mime_type") != "audio/mpeg" or not (raw.startswith(b"ID3") or (len(raw) > 1 and raw[0] == 255 and raw[1] & 224 == 224)):
                        raise ValueError("Missing or unsupported media MIME/signature")
                if state == "materialized" and original:
                    if requirement.get("status") == "available_from_kit":
                        if raw != beneath(kit, requirement["source_kit_ref"]).read_bytes():
                            raise ValueError("Public-regression image differs from official bytes")
                    elif requirement.get("status") == "requires_acquisition":
                        provenance = asset.get("provenance", {})
                        if (provenance.get("human_checked_content") is not True
                                or provenance.get("kind") not in {"human_capture", "human_camera_capture", "human_recording"}
                                or any(not isinstance(provenance.get(key), str) or not provenance[key].strip()
                                       for key in ("creator_or_source", "capture_conditions"))):
                            raise ValueError("Original human-content prerequisite remains unverified")
                    else:
                        raise ValueError("Unexpected materialized original fixture")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(raw)
            else:
                raise ValueError("Asset is blocked or uses an unknown materialization state")
            normalized_assets.append({"original_ref": ref, "source": str(source), "staged": str(destination),
                                      "state": state, "sha256": sha(raw) if raw is not None else None,
                                      "bytes": len(raw) if raw is not None else 0, "mime_type": asset.get("mime_type")})
            for step in staged["steps"]:
                payload = step["event"].get("payload", {})
                for key in ("audio_ref", "image_ref"):
                    if payload.get(key) == ref:
                        payload[key] = str(destination) if style == "absolute_within_root" else runtime_ref
                        if not original and key == "audio_ref" and asset.get("duration_ms") is not None:
                            payload["duration_ms"] = asset["duration_ms"]
        cwd = root.parent / "empty-cwd"
        cwd.mkdir(exist_ok=False)
        record.update(status="ready", media_root=str(root), cwd=str(cwd), assets=normalized_assets,
                      original_recipe=original, variant_id=binding.get("variant_id"),
                      environment_recipe=environment)
        return staged, record
    except (ValueError, KeyError, TypeError, OSError, EOFError, wave.Error, Image.DecompressionBombError) as exc:
        return None, {**record, "reason": f"{type(exc).__name__}: {exc}"}


def assets_unchanged(record):
    for asset in record.get("assets", []):
        for key in ("source", "staged"):
            path = Path(asset[key])
            if asset["state"] == "expected_absent":
                if path.exists():
                    return False
            elif not path.is_file() or sha(path.read_bytes()) != asset["sha256"]:
                return False
    return True


def media_evidence(case, record, evidence):
    """Actual current bytes must appear in a returned perception/planning record.

    No transcript, filename, recipe, model-proposed hash or asset count is proof.
    Superseded frames intentionally need not be consumed by the participant.
    """
    refs = []
    for step in case["steps"]:
        payload = step["event"].get("payload", {})
        if "audio_ref" in payload:
            refs.append(payload["audio_ref"])
    frames = [s["event"]["payload"]["image_ref"] for s in case["steps"] if "image_ref" in s["event"].get("payload", {})]
    if frames:
        refs.append(frames[-1])
    expected = {a["sha256"] for a in record["assets"] if a["state"] == "materialized" and a["original_ref"] in refs}
    observed = {m.get("sha256") for row in evidence if row.get("status") == 200 or row.get("usage")
                for m in row.get("input_media", []) if m.get("bytes", 0) > 0}
    return {"passed": expected <= observed, "expected_sha256": sorted(expected),
            "observed_sha256": sorted(observed),
            "scope": "Provider input telemetry; original invalid fixtures require no successful perception"}


def invalid_media_attempts(record, trace):
    """A generic setup refusal must not masquerade as invalid-media handling."""
    expected = {a["original_ref"] for a in record["assets"] if a["state"] in {"expected_absent", "staged_corrupt"}}
    observed = {r["media_ref"] for r in trace if r.get("kind") == "media_access" and r.get("status") in {"read", "read_error"}}
    return {"passed": expected <= observed, "expected_refs": sorted(expected), "observed_refs": sorted(observed)}


def media_read_observer(driver, record, loader):
    """Observe validated candidate read returns, including asyncio worker threads.

    No loader patch or input event is introduced. Timestamps mean evidence receipt,
    not a fabricated file-open time. Profiling and hashing overhead is disclosed.
    """
    expected = {str(Path(a["staged"]).resolve()): a for a in record["assets"]}
    code = loader._read.__code__

    def observe(frame, event, result):
        if event != "return" or frame.f_code is not code:
            return
        try:
            local = frame.f_locals
            path = (local["self"].root / local["reference"].replace("\\", "/")).resolve()
            asset = expected.get(str(path))
            if asset is None:
                raise ValueError("Candidate attempted an unbound media path")
            if not isinstance(result, tuple) or len(result) != 2 or not isinstance(result[0], bytes):
                driver.log(kind="media_access", media_ref=asset["original_ref"], status="read_error",
                           observed_method="candidate MediaLoader._read exited without validated bytes; read-only profiler",
                           timestamp_basis="observer receipt; not file-open timestamp")
                return
            raw, mime = result
            if sha(raw) != asset["sha256"] or len(raw) != asset["bytes"] or mime != asset["mime_type"]:
                raise ValueError("Actual loader return differs from staged binding")
            driver.log(kind="media_access", media_ref=asset["original_ref"], status="read",
                       sha256=sha(raw), bytes=len(raw), mime_type=mime,
                       observed_method="candidate MediaLoader._read return; read-only profiler",
                       timestamp_basis="observer receipt; not file-open timestamp")
        except Exception as exc:
            driver.log(kind="adapter_error", error=f"Media-read observer: {type(exc).__name__}: {exc}")

    return observe


@contextmanager
def observe_media_reads(driver, record, loader):
    if sys.getprofile() is not None or threading.getprofile() is not None:
        raise RuntimeError("Media observer refuses to replace an existing profiler")
    observe = media_read_observer(driver, record, loader)
    sys.setprofile(observe)
    threading.setprofile(observe)
    try:
        yield
    finally:
        threading.setprofile(None)
        sys.setprofile(None)


@contextmanager
def runtime_environment(record):
    previous_root, previous_cwd = os.environ.get("PARTICIPANT_MEDIA_ROOT"), Path.cwd()
    try:
        os.environ["PARTICIPANT_MEDIA_ROOT"] = record["media_root"]
        os.chdir(record["cwd"])
        yield
    finally:
        os.chdir(previous_cwd)
        if previous_root is None:
            os.environ.pop("PARTICIPANT_MEDIA_ROOT", None)
        else:
            os.environ["PARTICIPANT_MEDIA_ROOT"] = previous_root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, action="append", required=True)
    parser.add_argument("--bindings", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--variant", default="original")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=False)
    bindings, records = load_bindings(args.bindings), []
    for path in args.cases:
        for line in path.read_bytes().splitlines():
            if not line.strip():
                continue
            case = json.loads(line)
            if case["id"] in bindings:
                _, record = stage_case(case, sha(line), bindings[case["id"]], args.asset_root.resolve(),
                                       args.out / "staging", args.kit.resolve(), args.variant)
                records.append(record)
    report = {"provider_calls": 0, "participant_executions": 0, "records": records,
              "bindings_sha256": sha(args.bindings.read_bytes()),
              "cases_sha256": {str(p): sha(p.read_bytes()) for p in args.cases},
              "counts": dict(Counter(r["status"] for r in records))}
    (args.out / "preflight.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"counts": report["counts"], "out": str(args.out), "provider_calls": 0}))


if __name__ == "__main__":
    main()
