"""Offline negative controls: retain crashes and count attempted mock transport.

The tiny evaluator here is an authored test fixture, never an official kit edit.
"""
import asyncio
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import sys
import tempfile
import subprocess
from unittest.mock import Mock, patch

import httpx

from . import record, run
from .quota import TransportObserver


async def transport_check():
    observer = TransportObserver()
    async def respond(request):
        await asyncio.sleep(.001)  # Coroutine resumes must not multiply calls.
        if request.url.path == "/fail":
            raise httpx.ConnectError("synthetic failure")
        return httpx.Response(429, json={"error": {"message": "private fixture"}})
    with_context = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    async with with_context as client:
        sys.setprofile(observer.capture)
        try:
            await client.post("https://fixture.invalid/ok?private=omitted", content=b"fixture",
                              headers={"x-goog-api-key": "private-fixture"})
            try:
                await client.post("https://fixture.invalid/fail", content=b"fixture")
            except httpx.ConnectError:
                pass
        finally:
            sys.setprofile(None)
    assert not observer.errors
    assert len(observer.rows) == 2
    assert [r["status"] for r in observer.rows] == [429, "no_response_observed"]
    assert all(r["transport"] == "MockTransport" for r in observer.rows)
    assert "private" not in json.dumps(observer.rows)


def supervisor_cleanup_check():
    with tempfile.TemporaryDirectory(prefix="acceptance-supervisor-control-") as directory:
        root = Path(directory)
        out, source = root / "out", root / "source"
        process = Mock(pid=12345, returncode=None)
        process.wait.side_effect = lambda: setattr(process, "returncode", -9)
        failure = OSError("authored initial-status-write failure")

        def persist(path, value):
            if not value["completed"]:
                raise failure
            record.write_json(path, value)

        command = ["run", "--out", str(out), "--", "--submission", str(source),
                   "--kit", str(source), "--reference-kit", str(source), "--mode", "scripted"]
        with patch.object(sys, "argv", command), patch.object(run.subprocess, "Popen", return_value=process), \
                patch.object(run, "write_json", side_effect=persist):
            try:
                run.main()
            except OSError as exc:
                assert exc is failure
            else:
                raise AssertionError("initial status persistence failure was swallowed")
        process.kill.assert_called_once_with()
        process.wait.assert_called_once_with()
        status = json.loads((out / "process-status.json").read_text())
        assert status["completed"] and status["exit_code"] == -9


def main():
    asyncio.run(transport_check())
    supervisor_cleanup_check()
    with tempfile.TemporaryDirectory(prefix="acceptance-record-control-") as directory:
        root = Path(directory)
        kit, candidate, out = root / "kit", root / "candidate", root / "out"
        (kit / "harness").mkdir(parents=True)
        (kit / "scenarios").mkdir()
        candidate.mkdir()
        (candidate / "PACKAGE_MANIFEST.json").write_text(json.dumps({"source_git_revision": "authored-fixture-source"}))
        (kit / "harness/__init__.py").write_text("")
        (kit / "harness/mock_env.py").write_text("TOOL_REGISTRY = {}\n")
        (kit / "submission.yaml").write_text("fixture\n")
        fixture = '''
def run_once(scenario, cls, time_scale, wall_cap_s, setup_cap_s):
    trace = [{"kind":"fixture","t_ms":0}]
    raise RuntimeError("authored evaluator crash")
run_once({"scenario_id":"pub_04_text_no_tool","events":[]}, None, 1, 120, 300)
'''
        (kit / "eval_submission.py").write_text(fixture)
        command = ["record", "--submission", str(candidate), "--kit", str(kit),
                   "--reference-kit", str(kit), "--out", str(out), "--mode", "scripted"]
        # Isolate authored harness imports from any real kit loaded by a caller.
        saved = {k: v for k, v in sys.modules.items() if k == "harness" or k.startswith("harness.")}
        for name in saved:
            del sys.modules[name]
        try:
            with patch.object(sys, "argv", command), patch.object(sys, "path", [str(kit), *sys.path]), \
                    patch.object(record.subprocess, "check_output", side_effect=AssertionError("packaged source must not spawn git")), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                try:
                    record.main()
                except SystemExit as exc:
                    assert exc.code != 0
                else:
                    raise AssertionError("crashing evaluator was accepted")
        finally:
            for name in list(sys.modules):
                if name == "harness" or name.startswith("harness."):
                    del sys.modules[name]
            sys.modules.update(saved)
        rows = list(out.glob("attempt-*.json"))
        rows = [p for p in rows if p.name != "attempt-index.json"]
        assert len(rows) == 1
        row = json.loads(rows[0].read_text())
        assert row["status"] == "aborted" and row["score"] is None and row["trace"]
        manifest = json.loads((out / "manifest.json").read_text())
        assert manifest["official_exit_code"] == 1 and len(manifest["attempts"]) == 1
        assert manifest["git_head"] == "authored-fixture-source" and manifest["git_head_source"] == "frozen_package_manifest"
        assert not manifest["attempts"][0]["accepted"]
        supervised = root / "supervised"
        result = subprocess.run([sys.executable, "-B", "-m", "evaluation.samsung_acceptance.run",
            "--out", str(supervised), "--wall-seconds", "5", "--",
            "--submission", str(candidate), "--kit", str(kit), "--reference-kit", str(kit),
            "--mode", "scripted"], capture_output=True, timeout=10)
        status = json.loads((supervised / "run/process-status.json").read_text())
        assert result.returncode != 0 and status["exit_code"] != 0 and not status["timed_out"]
        assert (supervised / "run/attempt-001-pub_04_text_no_tool.json").is_file()
        (kit / "eval_submission.py").write_text(fixture.replace(
            'raise RuntimeError("authored evaluator crash")', 'import time; time.sleep(10)'))
        timed = root / "timed"
        result = subprocess.run([sys.executable, "-B", "-m", "evaluation.samsung_acceptance.run",
            "--out", str(timed), "--wall-seconds", "1", "--",
            "--submission", str(candidate), "--kit", str(kit), "--reference-kit", str(kit),
            "--mode", "scripted"], capture_output=True, timeout=10)
        status = json.loads((timed / "run/process-status.json").read_text())
        assert result.returncode != 0 and status["timed_out"]
        unfinished = json.loads((timed / "run/attempt-001-pub_04_text_no_tool.json").read_text())
        assert unfinished["status"] == "started" and unfinished["score"] is None
        (candidate / "participant").mkdir()
        (candidate / "participant/__init__.py").write_text("")
        (candidate / "participant/planner.py").write_text('''
from contextlib import nullcontext
import httpx
def planner_trace(observer): return nullcontext()
class Planner:
    client = None
    async def setup(self):
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(429, json={"error":{"details":[]}})))
    async def _decide(self):
        response = await self.client.post("https://fixture.invalid/generate", content=b"fixture")
        response.raise_for_status()
    async def close(self): await self.client.aclose()
''')
        (kit / "eval_submission.py").write_text('''
import asyncio
from participant.planner import Planner
def run_once(scenario, cls, time_scale, wall_cap_s, setup_cap_s):
    async def go():
        p=Planner()
        await p.setup()
        try: await p._decide()
        finally: await p.close()
    asyncio.run(go())
for _ in range(2):
    run_once({"scenario_id":"pub_04_text_no_tool","events":[]}, None, 1, 120, 300)
''')
        quota = root / "quota"
        result = subprocess.run([sys.executable, "-B", "-m", "evaluation.samsung_acceptance.run",
            "--out", str(quota), "--wall-seconds", "5", "--",
            "--submission", str(candidate), "--kit", str(kit), "--reference-kit", str(kit),
            "--mode", "real-provider"], capture_output=True, timeout=10)
        manifest = json.loads((quota / "run/manifest.json").read_text())
        stopped = json.loads((quota / "run/attempt-001-pub_04_text_no_tool.json").read_text())
        assert result.returncode == 75 and manifest["quota_stopped"]
        assert len(manifest["attempts"]) == 1 and stopped["status"] == "quota_stopped"
        assert len(stopped["transport_requests"]) == 1 and stopped["transport_requests"][0]["status"] == 429
        assert stopped["transport_requests"][0]["transport"] == "MockTransport"
        assert not (quota / "run/attempt-002-pub_04_text_no_tool.json").exists()
    print("Offline recorder controls passed: crash/timeout/429 retained, failed initial status write reaps child, subprocess status recorded, mock requests counted, secrets omitted")


if __name__ == "__main__":
    main()
