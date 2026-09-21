"""Check Gemini configuration locally; never import a planner or contact a provider."""
from __future__ import annotations

import argparse
from collections.abc import Mapping
import os
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = re.compile(r"gemini-[a-zA-Z0-9_.-]{1,100}\Z")
KEY_NAMES = ("THREAD_API_KEY", "SECRET_GEMINI_API_KEY")
SDK_KEYS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")


def check(profile: str, environ: Mapping[str, str], root: Path = ROOT) -> int:
    """Mirror only config-file/key/model loading, without evaluating provider access."""
    failures = 0

    def report(kind: str, message: str) -> None:
        nonlocal failures
        failures += kind == "FAIL"
        print(f"{kind}: {message}")

    print(f"Gemini configuration: {profile} (offline)")
    try:
        from dotenv import dotenv_values
    except ImportError:
        dependency_file = "requirements.lock" if profile == "app" else "requirements-submission.txt"
        report("FAIL", f"Install this profile's dependencies: python -m pip install -r {dependency_file}")
        return 1

    if profile == "app":
        path = root / ".env"
    else:
        path = Path(environ["PARTICIPANT_ENV_FILE"]) if environ.get("PARTICIPANT_ENV_FILE") else None
    local = {}
    if path is not None:
        try:
            if path.is_file():
                local = dotenv_values(path)
                report("PASS", "Configuration file loaded; values are not displayed.")
            elif profile == "participant":
                report("FAIL", "PARTICIPANT_ENV_FILE does not identify a readable file.")
            else:
                report("INFO", "No repository .env file; checking process environment only.")
        except (OSError, ValueError, UnicodeError):
            report("FAIL", "Cannot read the selected configuration file; check its path and UTF-8 encoding.")
    else:
        report("INFO", "Participant uses process environment only. Set PARTICIPANT_ENV_FILE to load .env.")

    names = KEY_NAMES + SDK_KEYS + ("THREAD_PROVIDER", "THREAD_MODEL", "PARTICIPANT_MODEL", "THREAD_LIVE_MODEL")
    for name in names:
        if name in environ and local.get(name) and environ[name] != local[name]:
            report("WARN", f"Process {name} overrides the file value; remove the process override if unintended.")

    def value(*names: str, default: str = "") -> str:
        if profile == "app":
            return environ.get(names[0], local.get(names[0]) or default)
        # The official planner selects a complete tier before resolving aliases.
        # Even a blank process alias suppresses fallback to the file's aliases.
        source = environ if any(name in environ for name in names) else local
        if source is environ and len(names) > 1 and any(local.get(name) for name in names):
            report("INFO", f"Process configuration selects the entire {' / '.join(names)} alias group over the file.")
        found = {source.get(name) for name in names} - {None, ""}
        if len(found) > 1:
            report("FAIL", f"Conflicting {' / '.join(names)} values; configure one alias or make them identical.")
            return ""
        return next(iter(found), default)

    provider = value("THREAD_PROVIDER", default="gemini")
    if provider != "gemini":
        report("FAIL", "Set THREAD_PROVIDER=gemini for this setup.")
    else:
        report("PASS", "Gemini provider selected.")

    key_names = ("THREAD_API_KEY",) if profile == "app" else ("SECRET_GEMINI_API_KEY", "THREAD_API_KEY")
    key = value(*key_names)
    if not key:
        report("FAIL", "No usable key. Set THREAD_API_KEY in the loaded file or process environment."
               + (" The organizer may instead inject SECRET_GEMINI_API_KEY." if profile == "participant" else ""))
    elif key != key.strip() or key.lower() in {"your_gemini_key", "your_api_key", "your_key_here", "replace_me"} or key.startswith("<"):
        report("FAIL", "Replace the placeholder or whitespace in the configured key; its value is hidden.")
    else:
        report("PASS", "Key present; validity and quota are untested.")
    if any(environ.get(name, local.get(name)) for name in SDK_KEYS):
        report("WARN", "GEMINI_API_KEY and GOOGLE_API_KEY are SDK names; this project's loaders do not use them.")
    if profile == "app" and environ.get("SECRET_GEMINI_API_KEY", local.get("SECRET_GEMINI_API_KEY")):
        report("INFO", "SECRET_GEMINI_API_KEY belongs to the official participant; the app requires THREAD_API_KEY.")

    model_names = ("THREAD_MODEL",) if profile == "app" else ("PARTICIPANT_MODEL", "THREAD_MODEL")
    model = value(*model_names)
    if model:
        if not MODEL_ID.fullmatch(model) or "live" in model:
            report("FAIL", "Use a bare Gemini text-output model ID for planning; Live has its own setting.")
        else:
            report("PASS", "Planning model ID has valid syntax; model access and media support are untested.")
    elif profile == "app" and "THREAD_MODEL" in environ:
        report("FAIL", "Blank process THREAD_MODEL shadows the file; remove it or set a model ID.")
    else:
        report("INFO", "No explicit planning model; the bundled planner default applies. Set THREAD_MODEL to pin it.")

    if profile == "app":
        live = value("THREAD_LIVE_MODEL")
        if live and (not MODEL_ID.fullmatch(live) or "live" not in live):
            report("FAIL", "THREAD_LIVE_MODEL must be a bare Gemini Live model ID.")
        elif not live and "THREAD_LIVE_MODEL" in environ:
            report("FAIL", "Blank process THREAD_LIVE_MODEL shadows the file; remove it or set a Live model ID.")
        else:
            report("INFO", "Live session access is untested; typed browser requests also use Live.")

    print("Result: " + ("fix the failures above." if failures else "local key/provider/model checks passed."))
    print("Other optional runtime settings are outside this check.")
    print("No network requests made. This does not verify model availability, quota, latency, or task correctness.")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("app", "participant"), default="app")
    return check(parser.parse_args().profile, os.environ)


if __name__ == "__main__":
    raise SystemExit(main())
