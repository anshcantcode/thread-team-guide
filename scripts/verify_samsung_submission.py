"""Offline participant verification using the unchanged external official kit.

This checks import provenance, declared dependencies, the organizer's exact two
admission gates, and an injected queue/tool/result/final/cancellation exchange.
It makes no cloud calls and is not a public-scenario or model-quality score.
The selected profile must disable setup prewarming without a hidden override.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
from contextlib import contextmanager, redirect_stdout
import hashlib
import importlib
import importlib.metadata
import inspect
import io
import json
import os
from pathlib import Path
import runpy
import socket
import sys
import tempfile
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
OFFLINE_OVERRIDES = {}
AUDIO_MODES = ("independent", "single_call_reads")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextmanager
def offline_environment():
    """Leave the OS loopback socketpair available, deny external network access."""
    names = [name for name in os.environ if name.startswith(("PARTICIPANT_", "THREAD_"))
             or name in {"SECRET_GEMINI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"}]
    previous = {name: os.environ.pop(name) for name in names}
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_getaddrinfo = socket.getaddrinfo
    attempts = []

    def guarded_connect(sock, address):
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(sock, address)
        attempts.append("connect")
        raise RuntimeError("external network disabled during offline verification")

    def guarded_connect_ex(sock, address):
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect_ex(sock, address)
        attempts.append("connect_ex")
        raise RuntimeError("external network disabled during offline verification")

    def guarded_getaddrinfo(host, *args, **kwargs):
        if host in {None, "localhost", "127.0.0.1", "::1", b"localhost", b"127.0.0.1", b"::1"}:
            return original_getaddrinfo(host, *args, **kwargs)
        attempts.append("dns")
        raise RuntimeError("external DNS disabled during offline verification")

    try:
        with patch.object(socket.socket, "connect", guarded_connect), \
             patch.object(socket.socket, "connect_ex", guarded_connect_ex), \
             patch.object(socket, "getaddrinfo", guarded_getaddrinfo), \
             patch.dict(os.environ, OFFLINE_OVERRIDES):
            yield attempts
    finally:
        os.environ.update(previous)


class SmokePlanner:
    """An explicit test double; no public fixture or production planning logic."""

    def __init__(self):
        self.closed = False
        self.contexts = []

    async def setup(self):
        pass

    async def plan(self, context):
        self.contexts.append(context)
        return {"intent": "lookup", "slots": {"sample": "package-check"},
                "tool_calls": [{"api_name": "inspect_sample",
                                "args": {"sample": "package-check"},
                                "response_template": "Observed {label}."}]}

    async def close(self):
        self.closed = True


async def exercise_contract(cls, validate_action):
    incoming, outgoing = asyncio.Queue(), asyncio.Queue()
    planner = SmokePlanner()
    agent = cls(incoming, outgoing, planner=planner)
    await asyncio.wait_for(agent.setup(), timeout=5)
    before = set(asyncio.all_tasks())
    task = asyncio.create_task(agent.run())
    actions = []

    async def next_action(kind):
        for _ in range(20):
            action = await asyncio.wait_for(outgoing.get(), timeout=3)
            require(not validate_action(action), f"malformed output action: {action!r}")
            actions.append(action)
            if action["action"] == kind:
                return action
        raise RuntimeError(f"too many actions before {kind}")

    try:
        await incoming.put({"timestamp_ms": 0, "event_type": "tool_manifest", "payload": {
            "schema_version": "1.0", "tools": {"inspect_sample": {
                "kind": "read_only", "description": "Inspect a named sample.",
                "args": {"sample": {"type": "string", "required": True}}
            }}}})
        await incoming.put({"timestamp_ms": 1, "event_type": "user_speech_chunk",
                            "payload": {"text": "Inspect the package-check sample.", "end_of_turn": True}})
        call = await next_action("tool_call")
        require(call["payload"].get("api_name") == "inspect_sample", "wrong synthetic tool")
        require(call["payload"].get("args") == {"sample": "package-check"}, "wrong synthetic arguments")
        call_id = call["payload"].get("call_id")
        require(isinstance(call_id, str) and bool(call_id), "missing participant call ID")
        # The end marker closes user input; the real harness still delivers results in its tail.
        await incoming.put({"timestamp_ms": 2, "event_type": "scenario_end", "payload": {}})
        await incoming.put({"timestamp_ms": 3, "event_type": "tool_result", "payload": {
            "call_id": call_id, "api_name": "inspect_sample", "status": "success",
            "result": {"label": "offline sample"}}})
        final = await next_action("final_response")
        require(final["payload"]["text"] == "Observed offline sample.", "result did not reach final response")
        require(final.get("state_snapshot", {}).get("slots", {}).get("sample") == "package-check",
                "final response missing current top-level snapshot")
        require(not task.done(), "run() stopped before harness cancellation")
    finally:
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=3)
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0)
    require(planner.closed, "run cancellation did not close the planner")
    leaked = [t for t in asyncio.all_tasks() - before if not t.done()]
    require(not leaked, "run cancellation leaked background tasks")
    require(bool(planner.contexts) and "inspect_sample" in planner.contexts[0].get("tools", {}),
            "raw manifest was not delivered to the planner")
    return {"actions": actions, "planner_calls": len(planner.contexts),
            "tool_result_after_scenario_end": True, "planner_closed": True, "leaked_tasks": 0}


async def exercise_real_planner():
    """Execute real media/client/schema code with a synthetic in-memory provider."""
    import httpx
    from PIL import Image
    from participant.planner import DEFAULT_MODEL, Planner, PlannerError

    with tempfile.TemporaryDirectory(prefix="samsung-package-smoke-") as folder:
        picture = Path(folder) / "sample.png"
        Image.new("RGB", (2, 2), "blue").save(picture)
        image_bytes = picture.read_bytes()
        requests = []

        async def respond(request):
            body = json.loads(request.content)
            parts = body["contents"][0]["parts"]
            encoded = [part["inlineData"] for part in parts if "inlineData" in part]
            require(len(encoded) == 1 and encoded[0]["mimeType"] == "image/png", "PNG was not attached")
            require(base64.b64decode(encoded[0]["data"]) == image_bytes, "PNG transport changed its bytes")
            requests.append(1)
            decision = {"observations": [{"message_index": 0, "type": "image", "uncertain": False,
                                          "visible_text": [],
                                          "observation": "A small solid blue square."}],
                        "intent": "describe", "slots": {}, "tool_calls": [], "clarification": None,
                        "response": "Offline planner transport completed."}
            return httpx.Response(200, json={"modelVersion": DEFAULT_MODEL, "candidates": [{
                "finishReason": "STOP", "content": {"parts": [{"text": json.dumps(decision)}]}}]})

        with patch.dict(os.environ, {"SECRET_GEMINI_API_KEY": "offline-verification-placeholder",
                                     "PARTICIPANT_MEDIA_ROOT": folder}):
            planner = Planner(transport=httpx.MockTransport(respond))
            try:
                await planner.setup()
                client = planner.client
                decision = await planner.plan({"revision": 1, "tools": {},
                    "state": {"intent": "", "slots": {}}, "tool_results": [], "messages": [
                        {"message_index": 0, "event_type": "video_frame", "payload": {"image_ref": "sample.png"}},
                        {"message_index": 1, "event_type": "user_speech_chunk",
                         "payload": {"text": "Describe the sample.", "end_of_turn": True}}]})
                require(decision.get("response") == "Offline planner transport completed.",
                        "real planner did not parse the synthetic provider response")
                require(len(requests) == 1, "real planner made an unexpected number of mocked requests")
            finally:
                await planner.close()
            require(client.is_closed, "real planner did not close its HTTP client")

            # A transport may swallow cancellation and return late. Neither a user
            # cancellation nor an expired deadline may turn that into a decision.
            for mode in ("cancel", "timeout"):
                started = asyncio.Event()

                async def late_response(_request):
                    started.set()
                    try:
                        await asyncio.sleep(60)
                    except asyncio.CancelledError:
                        value = {"observations": [], "intent": "", "slots": {}, "tool_calls": [],
                                 "clarification": None, "response": "Late synthetic reply."}
                        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP",
                            "content": {"parts": [{"text": json.dumps(value)}]}}]})

                timeout = "0.03" if mode == "timeout" else "4.5"
                with patch.dict(os.environ, {"PARTICIPANT_TIMEOUT_SECONDS": timeout}):
                    bounded = Planner(transport=httpx.MockTransport(late_response))
                    await bounded.setup()
                    bounded_client = bounded.client
                    task = asyncio.create_task(bounded.plan({}))
                    try:
                        await asyncio.wait_for(started.wait(), timeout=1)
                        if mode == "cancel":
                            task.cancel()
                        rejected = False
                        try:
                            await asyncio.wait_for(task, timeout=1)
                        except asyncio.CancelledError:
                            require(mode == "cancel", "deadline was misreported as user cancellation")
                            rejected = True
                        except PlannerError:
                            require(mode == "timeout" and bounded.evidence[-1]["status"] == "timeout",
                                    "cancellation/deadline failed for an unrelated reason")
                            rejected = True
                        require(rejected, f"{mode} accepted a late synthetic provider reply")
                    finally:
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                        await bounded.close()
                    require(bounded_client.is_closed, "bounded planner did not close its client")
    return {"transport": "httpx.MockTransport; synthetic response, no model inference",
            "successful_requests": len(requests), "actual_png_bytes": len(image_bytes), "client_closed": True,
            "cancelled_late_response_rejected": True, "expired_late_response_rejected": True}


def verify_manifest(submission: Path, kit: Path):
    path = submission / "PACKAGE_MANIFEST.json"
    if not path.is_file():
        return {"present": False, "scope": "source-tree verification"}
    record = json.loads(path.read_text(encoding="utf-8"))
    actual_files = set()
    for member in submission.rglob("*"):
        relative = member.relative_to(submission)
        require(not member.is_symlink(), f"symlink in candidate: {relative}")
        if "__pycache__" not in relative.parts and member.suffix not in {".pyc", ".pyo"} and member.is_file():
            actual_files.add(relative.as_posix())
    require(actual_files == set(record["files"]) | {"PACKAGE_MANIFEST.json"},
            "candidate contains missing or unmanifested files")
    for name, expected in record["files"].items():
        candidate = (submission / name).resolve()
        require(candidate.is_relative_to(submission), f"external manifest path: {name}")
        require(candidate.is_file() and sha256(candidate) == expected, f"package hash mismatch: {name}")
    for name, expected in record["official_kit_files"].items():
        original = (kit / name).resolve()
        require(original.is_relative_to(kit), f"external kit manifest path: {name}")
        require(original.is_file() and sha256(original) == expected, f"official kit hash mismatch: {name}")
    if kit != submission:
        require(sha256(kit / "submission.yaml") == record["original_submission_yaml_sha256"],
                "upstream submission.yaml no longer matches package provenance")
    return {"present": True, "verified_files": len(record["files"]),
            "official_files_preserved": len(record["official_kit_files"])}


def verify_onboarding(submission: Path):
    """Check the delivered doctor entry point under the caller's network guard."""
    required = (".env.example", "scripts/check_gemini_config.py", "docs/GEMINI_SETUP.md",
                "docs/submission/GEMINI_QUICKSTART.md")
    for name in required:
        require((submission / name).is_file(), f"missing onboarding file: {name}")
    doctor = submission / "scripts/check_gemini_config.py"
    output = io.StringIO()
    with patch.object(sys, "argv", [str(doctor), "--help"]), redirect_stdout(output):
        try:
            runpy.run_path(str(doctor), run_name="__main__")
        except SystemExit as exc:
            require(exc.code in (None, 0), "offline doctor --help failed")
    require("--profile" in output.getvalue() and "participant" in output.getvalue(),
            "offline doctor does not expose the participant profile")
    return {"files": {name: sha256(submission / name) for name in required},
            "doctor_help": "passed", "scope": "CLI delivery only; no key file loaded or provider access tested"}


async def verify_configuration(submission: Path, audio_mode: str = "independent"):
    """Compare shipped instructions to real key-only and explicit-file setup offline."""
    import httpx
    from dotenv import dotenv_values
    from participant.planner import Planner

    doctor = runpy.run_path(str(submission / "scripts/check_gemini_config.py"))
    expected = doctor["PARTICIPANT_DEFAULTS"]
    require(audio_mode in AUDIO_MODES, "unsupported audio mode for offline verification")
    selected = {**expected, "PARTICIPANT_AUDIO_MODE": audio_mode}
    example_path = submission / ".env.example"
    example = dotenv_values(example_path)
    guide = (submission / "docs/submission/GEMINI_QUICKSTART.md").read_text(encoding="utf-8")
    for name, value in expected.items():
        require(example.get(name) == value, f"example differs from selected profile: {name}")
        require(f"`{name}={value}`" in guide, f"quickstart differs from selected profile: {name}")
    require(not example.get("PARTICIPANT_THINKING_BUDGET"), "example retains a conflicting thinking budget")
    require(not any(example.get(name) for name in doctor["KEY_NAMES"] + doctor["SDK_KEYS"]),
            "example must contain no credentials")
    require(expected["PARTICIPANT_PREWARM"] == "0", "submission profile must disable setup prewarming")

    with tempfile.TemporaryDirectory(prefix="samsung-config-smoke-") as folder:
        env_file = Path(folder) / "settings.env"
        env_file.write_text(example_path.read_text(encoding="utf-8").replace(
                            "PARTICIPANT_AUDIO_MODE=independent", f"PARTICIPANT_AUDIO_MODE={audio_mode}") +
                            "\nTHREAD_API_KEY=offline-verification-placeholder\n", encoding="utf-8")
        effective_modes = {}
        for mode, values, profile in (
            ("key_only", {"SECRET_GEMINI_API_KEY": "offline-verification-placeholder"}, expected),
            ("explicit_process", {"SECRET_GEMINI_API_KEY": "offline-verification-placeholder",
                                  "PARTICIPANT_AUDIO_MODE": audio_mode}, selected),
            ("explicit_file", {"PARTICIPANT_ENV_FILE": str(env_file)}, selected),
        ):
            requests = []

            async def respond(request):
                requests.append(request.method)
                return httpx.Response(200, json={})

            output = io.StringIO()
            with patch.dict(os.environ, values), redirect_stdout(output):
                require(doctor["check"]("participant", os.environ, submission) == 0,
                        f"doctor rejected {mode} selected profile")
                planner = Planner(transport=httpx.MockTransport(respond))
                try:
                    await planner.setup()
                    actual = {
                        "THREAD_MODEL": planner.model,
                        "PARTICIPANT_THINKING_LEVEL": planner.thinking,
                        "PARTICIPANT_TIMEOUT_SECONDS": str(planner.timeout),
                        "PARTICIPANT_IMAGE_EMBEDDING": "1" if planner.image_embedding else "0",
                        "PARTICIPANT_AUDIO_MODE": planner.audio_mode,
                    }
                    for name, value in actual.items():
                        require(value == profile[name], f"runtime {mode} differs from selected profile: {name}")
                    effective_modes[mode] = planner.audio_mode
                    require(planner.thinking_budget is None, f"runtime {mode} retained a thinking budget")
                    require(bool(planner._key), f"runtime {mode} did not load the synthetic key")
                    require(not requests, f"runtime {mode} attempted a setup provider request; prewarm must default to 0")
                finally:
                    await planner.close()
            require("offline-verification-placeholder" not in output.getvalue(), "doctor displayed synthetic key")
    return {"selected_profile": selected, "qualification": "unqualified; offline setup only",
            "effective_audio_modes": effective_modes, "experimental_audio_mode": audio_mode == "single_call_reads",
            "example_and_quickstart": "matched", "key_only_setup": "passed", "explicit_file_setup": "passed",
            "explicit_process_setup": "passed",
            "mocked_setup_requests": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--submission", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, help="new JSON evidence file; never overwritten")
    parser.add_argument("--audio-mode", choices=AUDIO_MODES, default="independent",
                        help="explicit offline setup mode; single_call_reads is experimental")
    args = parser.parse_args()
    kit, submission = args.kit.resolve(), args.submission.resolve()
    require((3, 10) <= sys.version_info[:2] <= (3, 12), "this participant supports Python 3.10-3.12; use 3.11")
    require((kit / "eval_submission.py").is_file(), "--kit must contain unchanged eval_submission.py")
    if args.out:
        require(not args.out.exists(), "evidence output already exists; choose a new attempt name")
        require(not args.out.resolve().is_relative_to(kit), "write evidence outside the unchanged kit")
        if (submission / "PACKAGE_MANIFEST.json").is_file():
            require(not args.out.resolve().is_relative_to(submission), "write evidence outside the frozen candidate")
    sys.dont_write_bytecode = True
    manifest = verify_manifest(submission, kit)
    sys.path.insert(0, str(kit))
    evaluator = importlib.import_module("eval_submission")
    require(Path(evaluator.__file__).resolve() == kit / "eval_submission.py", "wrong evaluator imported")
    original_cwd = Path.cwd()
    os.chdir(kit)
    try:
        with offline_environment() as network_attempts:
            onboarding = verify_onboarding(submission)
            config, cls, errors = evaluator.validate_submission(str(submission))
            require(not errors, "official stage 1: " + "; ".join(errors))
            require(config["entry_point"] == "participant.agent:ParticipantAgent", "unexpected entry point")
            requirements = [line.strip() for line in
                            (submission / "requirements-submission.txt").read_text(encoding="utf-8").splitlines()
                            if line.strip() and not line.lstrip().startswith("#")]
            require(sorted(config.get("requirements", [])) == sorted(requirements),
                    "submission.yaml requirements differ from requirements-submission.txt")
            installed = {}
            for requirement in requirements:
                name, sep, expected = requirement.partition("==")
                require(bool(sep), f"require exact dependency pins: {requirement}")
                installed[name] = importlib.metadata.version(name)
                require(installed[name] == expected, f"installed {name} version differs from pin")
            require(config.get("python") in {"3.10", "3.11", "3.12"}, "unsupported manifest Python")
            require(config.get("env") == ["SECRET_GEMINI_API_KEY"], "unexpected required environment list")
            require(Path(inspect.getfile(cls)).resolve().is_relative_to(submission / "participant"),
                    "participant was imported outside the candidate")
            configuration = asyncio.run(verify_configuration(submission, args.audio_mode))
            with patch.dict(os.environ, {"PARTICIPANT_AUDIO_MODE": args.audio_mode}):
                smoke_errors = evaluator.contract_smoke_test(cls, setup_cap_s=300.0)
                require(not smoke_errors, "official stage 2: " + "; ".join(smoke_errors))
                protocol = importlib.import_module("harness.protocol")
                exchange = asyncio.run(exercise_contract(cls, protocol.validate_action))
                planner_exchange = asyncio.run(exercise_real_planner())
            require(not network_attempts, "runtime attempted external network in offline gates")
            imported = {name: str(Path(module.__file__).resolve()) for name, module in sys.modules.items()
                        if name.startswith(("participant", "harness")) and getattr(module, "__file__", None)}
            for name, path in imported.items():
                expected = submission / "participant" if name.startswith("participant") else kit / "harness"
                require(Path(path).is_relative_to(expected), f"wrong import origin: {name}")
            verify_manifest(submission, kit)
    finally:
        os.chdir(original_cwd)
    report = {"scope": "offline packaging and queue contract only; no public or model-quality score",
              "python": sys.version, "executable": sys.executable, "platform": sys.platform,
              "submission": str(submission), "kit": str(kit), "team": config["team"],
              "draft_team": config["team"] == "LOCAL_DRAFT_TEAM_METADATA_REQUIRED",
              "official_stage_1": "passed", "official_stage_2": "passed", "installed": installed,
              "package_manifest": manifest, "imports": imported, "exchange": exchange,
              "onboarding": onboarding,
              "configuration": configuration,
              "runtime_sha256": {Path(path).relative_to(submission).as_posix(): sha256(Path(path))
                                 for name, path in imported.items() if name.startswith("participant")},
              "verification_script_sha256": sha256(Path(__file__)),
              "offline_environment_overrides": dict(OFFLINE_OVERRIDES),
              "real_planner_exchange": planner_exchange,
              "external_network_attempts": len(network_attempts)}
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
