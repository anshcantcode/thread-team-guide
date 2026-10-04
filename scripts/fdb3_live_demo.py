"""Operator-only, one-recording live demo. No evaluator, service startup or campaign.

--list reads released metadata here only. The child gets neutral input.wav,
the public contract and normal worker options, never an ID or expected answer.
"""
import argparse
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import unquote, urlsplit
import uuid
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ROUTES = {"/": "demo-live.html", "/demo-live.html": "demo-live.html",
          "/identity.json": "identity.json", "/demo-status.json": "demo-status.json",
          "/input.wav": "input.wav"}
ROUTES.update({"/benchmark/" + name: "benchmark/" + name for name in (
    "stt-requests.jsonl", "model-requests.jsonl", "tool-calls.jsonl", "tts-requests.jsonl",
    "controller-events.jsonl", "voice-events.jsonl", "playback.jsonl", "result.json", "spoken.wav")})


def file_hash(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)


def asset_path(assets, row):
    data = (assets / "evaluator-data").resolve()
    audio = (data / row["relative_path"]).resolve()
    if not audio.is_relative_to(data) or audio.name != "input.wav":
        raise ValueError("Recording path escapes the released audio directory")
    return audio


def demo_candidates(assets, manifest):
    # Shared public tool classification, not a list of selected benchmark IDs.
    from thread_agent.fdb3 import WRITES
    candidates = []
    for index, row in enumerate(manifest["recordings"]):
        metadata = asset_path(assets, row).with_name("metadata.json")
        if file_hash(metadata) != row["metadata_sha256"]:
            raise ValueError("Released metadata hash mismatch at index " + str(index))
        body = json.loads(metadata.read_text(encoding="utf-8"))
        features = set(body.get("disfluency_features", []))
        calls = body.get("expected_tool_calls", [])
        if (features & {"SELF_CORRECTION", "FALSE_START"} and len(calls) == 1
                and calls[0].get("function") in WRITES):
            # Do not print dialogue, expected arguments or expected reply text.
            candidates.append({"index": index, "id": row["recording"],
                               "seconds": row["duration_seconds"],
                               "features": sorted(features & {"SELF_CORRECTION", "FALSE_START"}),
                               "write": calls[0]["function"]})
    return candidates


def select_recording(manifest, selection):
    rows = manifest["recordings"]
    if selection.isdecimal():
        index = int(selection)
        if index < len(rows):
            return index, rows[index]
    else:
        matches = [(i, row) for i, row in enumerate(rows) if row["recording"] == selection]
        if len(matches) == 1:
            return matches[0]
    raise ValueError("Unknown recording: use a zero-based manifest index or exact recording ID")


def create_take(parent):
    parent = parent.resolve()
    if not parent.is_relative_to(ROOT) or any(part.casefold() == ".thread-run" for part in parent.parts):
        raise ValueError("Demo evidence must stay inside this checkout, outside .thread-run and external junctions")
    parent.mkdir(parents=True, exist_ok=True)
    take = parent / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8])
    take.mkdir(exist_ok=False)
    return take


def viewer_server(take, port=0):
    """Bind itself to reserve a free loopback port; never expose arbitrary files."""
    if not 0 <= port <= 65535 or port == 8765:
        raise ValueError("Viewer port must be 0 (automatic) or a free port other than 8765")
    root = take.resolve()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def read_file(self, head=False):
            hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if self.headers.get("Host") not in hosts:
                self.send_error(403)
                return
            route = ROUTES.get(unquote(urlsplit(self.path).path))
            if route is None:
                self.send_error(404)
                return
            requested = root / route
            target = requested.resolve()
            if target != requested or not target.is_relative_to(root) or not target.is_file():
                self.send_error(404)
                return
            limit = (32 if target.suffix == ".wav" else 8) * 1024 * 1024
            try:
                with target.open("rb") as handle:
                    content = handle.read(limit + 1)
            except OSError:
                self.send_error(404)
                return
            if len(content) > limit:
                self.send_error(413, "Evidence exceeds viewer limit; inspect the raw local file")
                return
            kind = {".html": "text/html; charset=utf-8", ".wav": "audio/wav",
                    ".json": "application/json", ".jsonl": "text/plain; charset=utf-8"}[target.suffix]
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; "
                             "style-src 'unsafe-inline'; connect-src 'self'; media-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            if not head:
                self.wfile.write(content)

        def do_GET(self):
            self.read_file()

        def do_HEAD(self):
            self.read_file(head=True)

        def reject_write(self):
            self.send_error(405, "Read-only evidence viewer")

        do_POST = do_PUT = do_PATCH = do_DELETE = reject_write

    class ExclusiveServer(ThreadingHTTPServer):
        allow_reuse_address = False

        def server_bind(self):
            # Windows SO_REUSEADDR can let two listeners claim the same port.
            if os.name == "nt":
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()

    server = ExclusiveServer(("127.0.0.1", port), Handler)
    if server.server_port == 8765:  # Also exclude it if an OS ever selects it for port 0.
        server.server_close()
        return viewer_server(take, 0)
    return server


def worker_command(take, whisper, endpoint, model):
    return [sys.executable, str(take / "source/scripts/fdb3_audio_worker.py"),
            "--audio", str(take / "input.wav"), "--output", str(take / "benchmark"),
            "--contract", str(take / "contract"), "--whisper", str(whisper.resolve()),
            "--endpoint", endpoint, "--model", model, "--room", "--demo"]


def prepare_take(args, manifest, index, row):
    from scripts.fdb3_config import candidate_environment, load_config, snapshot_source, verify_whisper
    endpoint = urlsplit(args.endpoint)
    if endpoint.scheme != "http" or endpoint.hostname not in {"127.0.0.1", "localhost"} or endpoint.username or endpoint.password:
        raise ValueError("Demo requires an existing local HTTP planner, never hosted spending")
    if os.name != "nt" or os.environ.get("THREAD_FDB3_TTS_COMMAND"):
        raise ValueError("This demo profile requires Windows SAPI, without THREAD_FDB3_TTS_COMMAND")
    config = load_config()
    environment = candidate_environment()  # Preserve candidate flags; reject conflicting overrides.
    verify_whisper(args.whisper, config=config)  # Offline hash check, no model instantiation.
    audio = asset_path(args.assets, row)
    if file_hash(audio) != row["sha256"]:
        raise ValueError("Released input hash mismatch")
    take = create_take(args.evidence_root)
    print("Evidence: " + str(take), flush=True)
    try:
        source = snapshot_source(take / "source")
        shutil.copyfile(ROOT / "web/demo-live.html", take / "demo-live.html")
        shutil.copyfile(audio, take / "input.wav")
        if file_hash(take / "input.wav") != row["sha256"]:
            raise ValueError("Input changed while copying")
        contract = take / "contract"
        contract.mkdir()
        required = {"mock_apis.py", "latency_injector.py", "cascaded_agent.py"}
        if set(manifest["contract_hashes"]) != required:
            raise ValueError("Unexpected public contract file set")
        for name, expected in manifest["contract_hashes"].items():
            shutil.copyfile(args.assets / "agent-contract" / name, contract / name)
            if file_hash(contract / name) != expected:
                raise ValueError("Public contract hash mismatch: " + name)
        command = worker_command(take, args.whisper, args.endpoint, args.model)
        identity = {"mode": "opt-in live demo; not a benchmark score", "created_at": time.time(),
                    "source": source, "manifest_index": index, "recording": row["recording"],
                    "input_sha256": row["sha256"], "duration_seconds": row["duration_seconds"],
                    "manifest_sha256": file_hash(args.assets / "dataset-manifest.json"),
                    "contract_hashes": manifest["contract_hashes"], "candidate": config,
                    "config_sha256": file_hash(ROOT / "config/fdb3-candidate.json"),
                    "viewer_sha256": file_hash(take / "demo-live.html"),
                    "planner_service_identity": "operator must verify the owned service and model hash",
                    "python": sys.version, "tts": "Windows SAPI", "judge": "none", "paid_requests": 0,
                    "command": command, "environment": environment,
                    "playback": "default output; input 48 kHz and received reply 24 kHz mono PCM"}
        atomic_json(take / "identity.json", identity)
        # No selection, dialogue or expected answers in this child environment/argv.
        child_environment = dict(os.environ, **environment)
        child_environment["THREAD_FDB3_CACHE_OWNER_FILE"] = str(take / "cache-owner")
        child_environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return take, command, child_environment
    except BaseException as exc:
        atomic_json(take / "demo-status.json", {"status": "preparation_failed", "error": str(exc)})
        raise


def run_demo(args, manifest, index, row):
    take, command, environment = prepare_take(args, manifest, index, row)
    status = {"status": "ready", "qualification": False, "paid_requests": 0}
    server = thread = child = None
    try:
        server = viewer_server(take, args.port)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/"
        status["viewer_url"] = url
        atomic_json(take / "demo-status.json", status)
        print("Read-only viewer: " + url, flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        if not args.start_now:
            input("Start capture with the viewer visible, then press Enter to feed the recording. ")
        status.update(status="running", started_at=time.time())
        atomic_json(take / "demo-status.json", status)
        with (take / "worker.log").open("w", encoding="utf-8") as log:
            child = subprocess.Popen(command, cwd=take / "contract", env=environment,
                                     stdout=log, stderr=subprocess.STDOUT)
            try:
                code = child.wait(timeout=450)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
                code = 124
        result_path = take / "benchmark/result.json"
        result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {}
        status.update(status="completed" if code == 0 and result.get("status") == "completed" else "failed",
                      worker_exit_code=code, worker_status=result.get("status", "missing; outcome unknown"),
                      finished_at=time.time())
        atomic_json(take / "demo-status.json", status)
        print(f"Demo {status['status']}. Evidence retained: {take}", flush=True)
        print("Viewer stays available; worker has exited. Kitchen may now start. Ctrl+C closes only this viewer.", flush=True)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        if status["status"] in {"ready", "running"}:
            status.update(status="aborted", finished_at=time.time())
        return 0 if status["status"] == "completed" else 1
    except BaseException as exc:
        status.update(status="failed", error=str(exc), finished_at=time.time())
        raise
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.wait()
            status["worker_exit_code"] = child.returncode
        atomic_json(take / "demo-status.json", status)
        if server is not None:
            if thread is not None:
                server.shutdown()
                thread.join(timeout=5)
            server.server_close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--recording", help="Zero-based manifest index or exact recording ID")
    selection.add_argument("--list", action="store_true", help="Offline operator-only candidate selection")
    parser.add_argument("--assets", type=Path, default=ROOT / ".runtime/fdb-assets")
    parser.add_argument("--whisper", type=Path, help="Pinned local small.en model directory (required for playback)")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8098/v1")
    parser.add_argument("--model", default="Qwen3.5-4B")
    parser.add_argument("--evidence-root", type=Path, default=ROOT / ".demo-evidence")
    parser.add_argument("--port", type=int, default=0, help="0 reserves an OS-selected free port; 8765 is forbidden")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--start-now", action="store_true", help="Skip the recorder-ready Enter prompt")
    args = parser.parse_args(argv)
    try:
        args.assets = args.assets.resolve()
        manifest = json.loads((args.assets / "dataset-manifest.json").read_text(encoding="utf-8"))
        if args.list:
            print("Operator selection only: correction/false-start + exactly one expected call, a write.")
            print("No expected arguments/dialogue are printed or sent to the worker. Rehearsal still required.")
            for row in demo_candidates(args.assets, manifest):
                print(f"{row['index']:3d}  {row['seconds']:6.2f}s  {row['id']}  "
                      f"{','.join(row['features'])}  {row['write']}")
            return 0
        if args.whisper is None:
            parser.error("--whisper is required for playback; --list needs no model or audio device")
        index, row = select_recording(manifest, args.recording)
        return run_demo(args, manifest, index, row)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
