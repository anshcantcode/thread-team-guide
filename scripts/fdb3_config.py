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
LINUX_BUILD_CONFIG = ROOT / "config/fdb3-linux-build.json"


def load_config(environ=None):
    """Resolve the explicit recognizer choice; the JSON owns the only default."""
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    seed = config["llama"].get("seed")
    args = config["llama"]["args"]
    if (type(seed) is not int or not 0 <= seed < 4294967295
            or args.count("--seed") != 1
            or args.index("--seed") + 1 >= len(args)
            or args[args.index("--seed") + 1] != str(seed)):
        raise ValueError("Candidate drift: one explicit non-random llama seed must match the declared seed")
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


def verify_llama(binary, version_text):
    """Accept the pinned commit, or an exact previously evidenced archive build.

    Archive builds truthfully report an unknown commit. A caller-supplied
    manifest is not proof: only an exact hash in our recorded build pins counts.
    """
    config = load_config()["llama"]
    with Path(binary).open("rb") as handle:
        sha = hashlib.file_digest(handle, "sha256").hexdigest()
    identity = {"binary_sha256": sha, "source_commit": config["commit"],
                "version_text": version_text}
    if config["commit"][:9] in version_text:
        return {**identity, "verified_by": "commit_version"}
    build = json.loads(LINUX_BUILD_CONFIG.read_text(encoding="utf-8"))
    receipt = build.get("archive_build_receipts", {}).get(sha, {})
    if (receipt.get("source_commit") != config["commit"]
            or receipt.get("source_archive_sha256") != build["llama_source_sha256"]):
        raise ValueError("LLAMA_SERVER must match the pinned commit or an exact recorded archive-build SHA-256")
    return {**identity, "verified_by": "recorded_archive_build", "build_receipt": receipt}


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
                                      'requirements-fdb3-bench.lock',
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
    # Release source archives have no Git metadata. A nested export must not
    # borrow the commit of a containing checkout: the file hashes identify it.
    identity = {'source_kind': 'source_archive', 'source_commit': None,
                'dirty': None, 'source_hashes': hashes}
    try:
        git_root = subprocess.check_output(
            ['git', '-C', str(ROOT), 'rev-parse', '--show-toplevel'],
            text=True, stderr=subprocess.DEVNULL).strip()
        if Path(git_root).resolve() == ROOT.resolve():
            identity.update(source_kind='git_checkout', source_commit=subprocess.check_output(
                ['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
                dirty=bool(subprocess.check_output(
                    ['git', '-C', str(ROOT), 'status', '--porcelain'], text=True)))
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    (destination / 'source-identity.json').write_text(json.dumps(identity, indent=2), encoding='utf-8')
    return identity


def shell_config():
    if os.environ.get('THREAD_FDB3_PROFILE', 'candidate') != 'candidate':
        raise ValueError('Full Linux reproduction requires the candidate profile, not cpu-component')
    config = load_config()
    livekit = json.loads(LINUX_BUILD_CONFIG.read_text(encoding="utf-8"))["livekit"]
    values = candidate_environment()
    lines = [f"export {key}={shlex.quote(value)}" for key, value in values.items()]
    constants = {
        "UPSTREAM_COMMIT": config["upstream_commit"], "ARCHIVE_SHA256": config["archive_sha256"],
        "LLAMA_COMMIT": config["llama"]["commit"], "LLAMA_VERSION": config["llama"]["version"],
        "MODEL_URL": config["model"]["url"], "MODEL_SHA256": config["model"]["sha256"],
        "WHISPER_REPO": config["whisper"]["repo"], "WHISPER_REV": config["whisper"]["revision"],
        "LIVEKIT_DOWNLOAD_URL": livekit["url"], "LIVEKIT_ARCHIVE_SHA256": livekit["archive_sha256"],
        "LIVEKIT_BINARY_SHA256": livekit["binary_sha256"],
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
    modes.add_argument("--verify-llama", type=Path, help="Verify a CUDA server against the pinned source/build identity")
    parser.add_argument("--llama-version-file", type=Path)
    args = parser.parse_args()
    try:
        if args.snapshot:
            print(json.dumps(snapshot_source(args.snapshot), indent=2))
        elif args.verify_whisper:
            print(json.dumps(verify_whisper(args.verify_whisper), indent=2))
        elif args.verify_llama:
            if not args.llama_version_file:
                parser.error("--verify-llama requires --llama-version-file")
            print(json.dumps(verify_llama(args.verify_llama, args.llama_version_file.read_text()), indent=2))
        else:
            print(shell_config() if args.shell else json.dumps(load_config(), indent=2))
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
