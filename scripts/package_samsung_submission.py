"""Build a local, allowlisted Samsung participant package from an external kit.

No publication, tagging, model calls, or edits to the supplied kit occur here.
The official fixtures stay in the evaluation layout, outside participant/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile


ROOT = Path(__file__).resolve().parents[1]
KIT_FILES = (
    ".gitignore", "README.md", "WALKTHROUGH.md", "run_local.py", "eval_submission.py", "submission.yaml",
    "agent/__init__.py", "agent/agent.py", "audio/.gitkeep", "audio/pub_05_turn1.mp3",
    "audio/pub_05_turn2.mp3", "audio/pub_06_turn1_part1.mp3", "audio/pub_06_turn1_part2.mp3",
    "frames/.gitkeep", "frames/pub_07_f017.png", "harness/__init__.py", "harness/mock_env.py",
    "harness/protocol.py", "harness/runner.py", "harness/scenario_gen.py", "harness/scorer.py",
    "docs/PROTOCOL.md", "docs/SCORING.md", "docs/SUBMISSION.md", "docs/TOOLS.md",
    "scenarios/pub_01_text_simple.json", "scenarios/pub_02_text_interrupt.json",
    "scenarios/pub_03_text_chained_booking.json", "scenarios/pub_04_text_no_tool.json",
    "scenarios/pub_05_audio_asr_ambiguity.json", "scenarios/pub_06_audio_disfluency.json",
    "scenarios/pub_07_visual_port_lookup.json", "scenarios/pub_08_text_tool_failure.json",
    "scenarios/pub_09_text_unseen_tool.json",
)
SOURCE_FILES = ("submission.yaml", "requirements-submission.txt", "Dockerfile.submission",
                ".dockerignore", "scripts/package_samsung_submission.py",
                "scripts/verify_samsung_submission.py", "scripts/check_gemini_config.py",
                "docs/GEMINI_SETUP.md", "docs/submission/README.md",
                "docs/submission/GEMINI_QUICKSTART.md", ".env.example")
REQUIRED_RUNTIME = ("__init__.py", "agent.py", "planner.py", "media.py", "authorization.py",
                    "embedding.py", "schema.py")
EXCLUDED = {"__pycache__", ".pytest_cache", ".git", ".venv", ".runtime", "node_modules"}
SECRET = re.compile(rb"AIza[0-9A-Za-z_-]{35}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
# Only this reviewed blank template may enter a package. Normalize line endings,
# not values, so the same checkout works on Windows and Linux.
ENV_TEMPLATE = ".env.example"
ENV_TEMPLATE_SHA256 = "d51f494e0c87c5c3f8d9fa2e7d54001def693a355a53acdd4f6ad95fac97be5d"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_member(root: Path, path: Path) -> tuple[str, bytes]:
    name = path.relative_to(root).as_posix()
    if (any(parent.is_symlink() for parent in (path, *path.parents) if parent != root)
            or not path.resolve().is_relative_to(root) or not path.is_file()):
        raise ValueError(f"missing, symlinked, or external package member: {name}")
    if any(p in EXCLUDED or (p.startswith(".env") and name != ENV_TEMPLATE)
           for p in path.relative_to(root).parts):
        raise ValueError(f"private/runtime package member: {name}")
    data = path.read_bytes()
    if name == ENV_TEMPLATE and digest(data.replace(b"\r\n", b"\n")) != ENV_TEMPLATE_SHA256:
        raise ValueError("environment template differs from the reviewed blank template")
    if SECRET.search(data):
        raise ValueError(f"credential-shaped bytes in {name}; package not written")
    return name, data


def collect(kit: Path, source: Path) -> tuple[dict[str, bytes], dict]:
    payload = dict(read_member(kit, kit / name) for name in KIT_FILES)
    for name in SOURCE_FILES:
        if name != "submission.yaml" and (kit / name).exists():
            raise ValueError(f"candidate would replace official files: {name}")
    original_yaml = payload.pop("submission.yaml")
    official_hashes = {name: digest(data) for name, data in sorted(payload.items())}

    additions = dict(read_member(source, source / name) for name in SOURCE_FILES)
    runtime = dict(read_member(source, source / "participant" / name) for name in REQUIRED_RUNTIME)
    additions.update(runtime)
    collision = payload.keys() & additions.keys()
    if collision:
        raise ValueError(f"candidate would replace official files: {sorted(collision)}")
    payload.update(additions)
    try:
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=source, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        revision = None
    record = {
        "format": "samsung-participant-package-v1",
        "status": "local draft; no publication or submission performed",
        "entry_point": "participant.agent:ParticipantAgent",
        "source_git_revision": revision,
        "source_identity": "File hashes below describe actual bytes, including uncommitted changes.",
        "original_submission_yaml_sha256": digest(original_yaml),
        "official_kit_files": official_hashes,
        "files": {name: digest(data) for name, data in sorted(payload.items())},
        "runtime_files": sorted(runtime),
        "scope": "Explicit file allowlist only. Official fixtures are evaluation inputs; participant/ contains runtime Python only.",
    }
    payload["PACKAGE_MANIFEST.json"] = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode()
    return payload, record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit", type=Path, required=True, help="unchanged external official kit root")
    parser.add_argument("--source", type=Path, default=ROOT, help="integrated source root")
    parser.add_argument("--output", type=Path, required=True, help="new candidate directory; never overwritten")
    args = parser.parse_args()
    kit, source, output = (p.resolve() for p in (args.kit, args.source, args.output))
    archive_path = output.with_name(output.name + ".zip")
    if output.exists() or archive_path.exists():
        parser.error("output directory or sibling zip already exists; choose a new attempt name")
    if output == source or output.is_relative_to(kit) or kit.is_relative_to(output):
        parser.error("output must not replace the source or overlap the official kit")
    if any(output.is_relative_to(source / p) for p in ("participant", "scripts", "docs")):
        parser.error("output must not be inside source files selected for packaging")

    payload, record = collect(kit, source)
    output.mkdir(parents=True, exist_ok=False)
    for name, data in sorted(payload.items()):
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(payload.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("archive CRC verification failed")
        for name, data in payload.items():
            if archive.read(name) != data or (output / name).read_bytes() != data:
                raise RuntimeError(f"package round-trip mismatch: {name}")
    # Verify our source reads did not alter any official file.
    for name, expected in record["official_kit_files"].items():
        if digest((kit / name).read_bytes()) != expected:
            raise RuntimeError(f"official kit changed during packaging: {name}")
    if digest((kit / "submission.yaml").read_bytes()) != record["original_submission_yaml_sha256"]:
        raise RuntimeError("official submission.yaml changed during packaging")
    print(json.dumps({"candidate": str(output), "archive": str(archive_path),
                      "archive_sha256": digest(archive_path.read_bytes()),
                      "files": len(payload), "official_files_preserved": len(record["official_kit_files"]),
                      "runtime_files": record["runtime_files"]}, indent=2))


if __name__ == "__main__":
    main()
