"""Record three real-time THREAD attempts for one official public scenario.

Run explicitly with ``python scripts/replay_public_trace.py --scenario pub_04_text_no_tool``.
The report keeps each untouched harness trace and full official score. It omits
the source fixture as a separate blob, raw audio/image bytes, credential values,
and provider prompts or HTTP bodies. Public media reference strings and event
text can still appear in the harness trace.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "theme5_kit" / "participant-kit" / "participant-kit"
REPETITIONS = 3
TIME_SCALE = 1.0
SECRET_NAMES = ("SECRET_GEMINI_API_KEY", "THREAD_API_KEY")
OMITTED = [
    "The source fixture and ground-truth JSON as separate fields; the public scenario ID, metadata, fixture SHA-256, and official trace are retained.",
    "Raw audio or image bytes; the official trace can retain public media reference strings.",
    "Credential values, provider prompts, and HTTP request or response bodies.",
]

sys.path[:0] = [str(ROOT), str(KIT)]

from harness.runner import EvaluationHarness  # noqa: E402
from harness.scorer import score_scenario  # noqa: E402
from participant.agent import ParticipantAgent  # noqa: E402


def _scenario_path(scenario_id: str) -> Path:
    path = next((case for case in (KIT / "scenarios").glob("pub_*.json") if case.stem == scenario_id), None)
    if path is None:
        raise ValueError("scenario must name a public kit case, such as pub_04_text_no_tool")
    return path


def _secret_values() -> list[str]:
    values = (os.environ.get(name, "") for name in SECRET_NAMES)
    return sorted((value for value in values if len(value) >= 4), key=len, reverse=True)


def _redact(value, secrets):
    if isinstance(value, dict):
        return {_redact(key, secrets): _redact(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[REDACTED]")
    return value


def _module_file_identities(package: str) -> list[dict[str, str]]:
    identities = []
    for import_path, module in sorted(sys.modules.items()):
        if import_path != package and not import_path.startswith(package + "."):
            continue
        source = getattr(module, "__file__", None)
        if not source:
            continue
        path = Path(source).resolve()
        if path.suffix != ".py" or not path.is_file():
            continue
        try:
            relative_path = path.relative_to(ROOT).as_posix()
        except ValueError:
            continue
        identities.append({
            "import_path": import_path,
            "path": relative_path,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    return identities


def _resolved_participant_config(agents) -> dict[str, str]:
    if not agents:
        return {}
    planner = getattr(agents[0], "planner", None)
    return {name: value for name in ("model", "audio_mode")
            if isinstance((value := getattr(planner, name, None)), str) and value}


def _observed_manifest_identity(agents):
    if not agents or not isinstance((manifest := getattr(agents[0], "tools", None)), dict):
        return None
    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    return {"sha256": hashlib.sha256(canonical).hexdigest(),
            "tool_names": sorted(manifest)}


async def replay_public_scenario(scenario_id: str, *, agent_factory=None) -> dict:
    """Replay a public case three times; agent_factory is only an offline test seam."""
    path = _scenario_path(scenario_id)
    raw_scenario = path.read_bytes()
    scenario = json.loads(raw_scenario)
    factory = agent_factory or (lambda in_q, out_q: ParticipantAgent(in_q, out_q))
    attempts = []
    for attempt in range(1, REPETITIONS + 1):
        agents = []
        def record_agent(in_q, out_q):
            agent = factory(in_q, out_q)
            agents.append(agent)
            return agent
        harness = EvaluationHarness(scenario, record_agent, time_scale=TIME_SCALE, verbose=False)
        trace = await harness.run()
        records = [record for agent in agents if getattr(agent, "planner", None) is not None
                   for record in getattr(agent.planner, "evidence", [])]
        row = {"attempt": attempt, "score": score_scenario(scenario, trace),
               "trace": trace, "planner_records": records}
        resolved_config = _resolved_participant_config(agents)
        if resolved_config:
            row["participant_runtime"] = resolved_config
        if (manifest_identity := _observed_manifest_identity(agents)) is not None:
            row["observed_tool_manifest"] = manifest_identity
        attempts.append(row)

    scenario_relative_path = path.relative_to(ROOT).as_posix()

    report = {
        "scenario_id": scenario_id,
        "scenario_metadata": scenario.get("metadata", {}),
        "scenario_sha256": hashlib.sha256(raw_scenario).hexdigest(),
        "repetitions": REPETITIONS,
        "time_scale": TIME_SCALE,
        "participant": {
            "entry_point": "participant.agent.ParticipantAgent",
            "provider": os.environ.get("THREAD_PROVIDER", "gemini"),
            "model": os.environ.get("PARTICIPANT_MODEL", os.environ.get("THREAD_MODEL", "gemini-3.5-flash-lite")),
            "thinking_level": os.environ.get("PARTICIPANT_THINKING_LEVEL", "minimal"),
        },
        "evaluator": "official theme5_kit EvaluationHarness and score_scenario",
        "identity": {
            "participant_runtime_modules": _module_file_identities("participant"),
            "official_evaluator": {
                "entry_points": ["harness.runner.EvaluationHarness", "harness.scorer.score_scenario"],
                "modules": _module_file_identities("harness"),
            },
            "scenario": {"path": scenario_relative_path,
                         "sha256": hashlib.sha256(raw_scenario).hexdigest()},
        },
        "attempts": attempts,
        "omitted": OMITTED,
    }
    return _redact(report, _secret_values())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True, help="public scenario ID, for example pub_04_text_no_tool")
    parser.add_argument("--env-file", type=Path, help="optional local credential file read by THREAD's planner")
    parser.add_argument("--out", type=Path, help="JSON report path (default: ignored .runtime directory)")
    args = parser.parse_args()

    try:
        _scenario_path(args.scenario)
    except ValueError as exc:
        parser.error(str(exc))
    if args.env_file:
        os.environ["PARTICIPANT_ENV_FILE"] = str(args.env_file.expanduser().resolve())
    configured_env_file = os.environ.get("PARTICIPANT_ENV_FILE")
    if configured_env_file:
        env_file = Path(configured_env_file).expanduser().resolve()
        if not env_file.is_file():
            parser.error("PARTICIPANT_ENV_FILE must name an existing file")
        # Match Planner's setting precedence: process credentials select the
        # process environment as a whole; otherwise load the file as a whole.
        if not any(name in os.environ for name in SECRET_NAMES):
            try:
                from dotenv import dotenv_values

                for name, value in dotenv_values(env_file).items():
                    if value is not None:
                        os.environ.setdefault(name, value)
            except (OSError, UnicodeError):
                parser.error("PARTICIPANT_ENV_FILE could not be read")
        os.environ["PARTICIPANT_ENV_FILE"] = str(env_file)
    os.environ["PARTICIPANT_MEDIA_ROOT"] = str(KIT)
    if os.environ.get("THREAD_PROVIDER", "gemini") != "gemini":
        parser.error("this participant supports THREAD_PROVIDER=gemini only")
    if not any(os.environ.get(name) for name in SECRET_NAMES):
        parser.error("set SECRET_GEMINI_API_KEY or THREAD_API_KEY, or pass --env-file")

    report = asyncio.run(replay_public_scenario(args.scenario))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.out or ROOT / ".runtime" / "public-traces" / f"{args.scenario}-{stamp}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    scores = ", ".join(str(row["score"]["total"]) for row in report["attempts"])
    print(f"{args.scenario}: scores {scores}")
    print(f"Trace report: {output.resolve()}")


if __name__ == "__main__":
    main()
