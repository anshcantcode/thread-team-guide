"""Shared, provider-free Linux/container candidate configuration.

Conflicting inherited flags are errors, not silent changes to the candidate.
The explicit cpu-component profile is not a measured benchmark configuration.
"""
import argparse
import json
import os
from pathlib import Path
import shlex
import hashlib
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/fdb3-candidate.json"


def load_config(environ=None):
    """Resolve the explicit recognizer choice; the JSON owns the only default."""
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    inherited = os.environ if environ is None else environ
    catalog = config["whisper"]
    name = inherited.get("THREAD_FDB3_WHISPER_MODEL", catalog["default_model"])
    if name not in catalog["models"]:
        raise ValueError("Candidate drift: THREAD_FDB3_WHISPER_MODEL must be base.en or small.en")
    config["whisper"] = {"name": name, **catalog["models"][name]}
    config["environment"]["THREAD_FDB3_WHISPER_MODEL"] = name
    return config


def verify_whisper(directory, *, config=None):
    """Hash every required local asset before use; never download or infer a model."""
    selected = (load_config() if config is None else config)["whisper"]
    for name, expected in selected["sha256"].items():
        path = Path(directory) / name
        if not path.is_file():
            raise ValueError(f"Missing {selected['name']} recognizer asset: {path}")
        with path.open("rb") as handle:
            actual = hashlib.file_digest(handle, "sha256").hexdigest()
        if actual != expected:
            raise ValueError(f"SHA-256 mismatch for {selected['name']} recognizer asset: {path}")
    return selected


def candidate_environment(profile="candidate", environ=None):
    if profile not in {"candidate", "cpu-component"}:
        raise ValueError("THREAD_FDB3_PROFILE must be candidate or cpu-component")
    inherited = os.environ if environ is None else environ
    values = dict(load_config(environ=inherited)["environment"])
    if profile == "cpu-component":
        values["THREAD_FDB3_WHISPER_DEVICE"] = "cpu"
    for key, value in values.items():
        if key in inherited and inherited[key] != value:
            raise ValueError(f"Candidate drift: {key} must be {value!r}; unset the override or register a new profile")
    return values


def apply_environment():
    values = candidate_environment(os.environ.get("THREAD_FDB3_PROFILE", "candidate"))
    os.environ.update(values)
    return values


def snapshot_source(destination):
    destination.mkdir(parents=False, exist_ok=False)
    files = [path for folder in ('participant', 'thread_agent', 'scripts', 'config')
             for path in (ROOT / folder).iterdir()
             if path.is_file() and path.suffix in {'.py', '.sh', '.json'}]
    files += [ROOT / name for name in ('requirements-fdb3.lock', 'requirements-fdb3-bench.txt',
                                      'requirements-fdb3-cuda.txt')]
    hashes = {}
    for path in files:
        relative = path.relative_to(ROOT)
        expected = hashlib.sha256(path.read_bytes()).hexdigest()
        target = destination / relative
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(path, target)
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise ValueError('Source changed while snapshotting: ' + str(relative))
        hashes[relative.as_posix()] = expected
    identity = {'source_commit': subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
                'dirty': bool(subprocess.check_output(['git', '-C', str(ROOT), 'status', '--porcelain'], text=True)),
                'source_hashes': hashes}
    (destination / 'source-identity.json').write_text(json.dumps(identity, indent=2), encoding='utf-8')
    return identity


def shell_config():
    if os.environ.get('THREAD_FDB3_PROFILE', 'candidate') != 'candidate':
        raise ValueError('Full Linux reproduction requires the candidate profile, not cpu-component')
    config = load_config()
    values = candidate_environment()
    lines = [f"export {key}={shlex.quote(value)}" for key, value in values.items()]
    constants = {
        "UPSTREAM_COMMIT": config["upstream_commit"], "ARCHIVE_SHA256": config["archive_sha256"],
        "LLAMA_COMMIT": config["llama"]["commit"], "LLAMA_VERSION": config["llama"]["version"],
        "MODEL_URL": config["model"]["url"], "MODEL_SHA256": config["model"]["sha256"],
        "WHISPER_REPO": config["whisper"]["repo"], "WHISPER_REV": config["whisper"]["revision"],
    }
    lines.extend(f"{key}={shlex.quote(value)}" for key, value in constants.items())
    lines.append("LLAMA_ARGS=(" + shlex.join(config["llama"]["args"]) + ")")
    lines.append("declare -A WHISPER_SHA256=(" + " ".join(
        f"[{shlex.quote(key)}]={shlex.quote(value)}" for key, value in config["whisper"]["sha256"].items()) + ")")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--shell", action="store_true")
    modes.add_argument("--snapshot", type=Path)
    modes.add_argument("--verify-whisper", type=Path, help="Offline SHA-256 check of the selected model directory")
    args = parser.parse_args()
    try:
        if args.snapshot:
            print(json.dumps(snapshot_source(args.snapshot), indent=2))
        elif args.verify_whisper:
            print(json.dumps(verify_whisper(args.verify_whisper), indent=2))
        else:
            print(shell_config() if args.shell else json.dumps(load_config(), indent=2))
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
