"""Mocked and loopback-only delivery observer controls; no provider access."""
import argparse
import asyncio
from contextlib import contextmanager, redirect_stderr
from copy import deepcopy
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpcore
import httpx
from httpcore._trace import Trace

from . import record
from .delivery import DeliveryObserver, PHASES
from .quota import TransportObserver


PRIVATE = "PRIVATE-DELIVERY-SENTINEL"
LOGGER = logging.getLogger("httpcore.http11")


class DeliveryChecks(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.transport = TransportObserver()
        self.observer = DeliveryObserver(self.transport)

    @contextmanager
    def observing(self):
        def fanout(frame, event, result):
            self.transport.capture(frame, event, result)
            self.observer.capture(frame, event, result)
        old = sys.getprofile()
        sys.setprofile(fanout)
        try:
            yield
        finally:
            sys.setprofile(old)

    def evidence(self):
        self.assertEqual(self.observer.errors, [])
        self.assertNotIn(PRIVATE, json.dumps(self.observer.rows))
        for row in self.observer.rows:
            if "phase" in row:
                self.assertIn(row["phase"], PHASES)
        return self.observer.rows

    async def test_loopback_concurrency_and_actual_wire_bytes(self):
        async def run(enabled):
            received = []
            async def serve(reader, writer):
                try:
                    head = await reader.readuntil(b"\r\n\r\n")
                    length = int(next(line.split(b":")[1] for line in head.split(b"\r\n")
                                      if line.lower().startswith(b"content-length:")))
                    received.append(await reader.readexactly(length))
                    await asyncio.sleep(.002)
                    writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 11\r\nConnection: close\r\n\r\n{"ok":true}')
                    await writer.drain()
                finally:
                    writer.close()
                    await writer.wait_closed()
            server = await asyncio.start_server(serve, "127.0.0.1", 0)
            port = server.sockets[0].getsockname()[1]
            async with server, httpx.AsyncClient(trust_env=False) as client:
                requests = [client.build_request("POST", f"http://127.0.0.1:{port}/?q={PRIVATE}",
                    content=body, headers={"x-private": PRIVATE}) for body in (b'first', b'second')]
                extensions = [deepcopy(r.extensions) for r in requests]
                if enabled:
                    with self.observing():
                        replies = await asyncio.gather(*(client.send(r) for r in requests))
                else:
                    replies = await asyncio.gather(*(client.send(r) for r in requests))
                self.assertEqual([r.extensions for r in requests], extensions)
                self.assertEqual([r.json() for r in replies], [{"ok": True}] * 2)
            return sorted(received)
        self.assertEqual(await run(False), await run(True))
        rows = self.evidence()
        starts = [r for r in rows if r["event"] == "dispatch_start"]
        self.assertEqual(len(starts), 2)
        self.assertEqual(len({r["task_id"] for r in starts}), 2)
        for start in starts:
            related = [r for r in rows if r.get("dispatch_id") == start["dispatch_id"]]
            phases = {r.get("phase") for r in related}
            self.assertTrue({"connection.connect_tcp", "http11.send_request_body",
                "http11.receive_response_headers", "http11.receive_response_body", "http11.response_closed"} <= phases)
            end = next(r for r in related if r["event"] == "dispatch_end")
            body = next(r for r in related if r.get("phase") == "http11.receive_response_body")
            self.assertLessEqual(end["at_monotonic_ns"], body["at_monotonic_ns"])
            self.assertTrue(all(r["at_monotonic_ns"] >= start["at_monotonic_ns"] for r in related))
        self.assertEqual(len(self.transport.rows), 2)
        self.assertEqual(self.observer.take()["open_stages"], [])

    async def test_concurrent_cancel_and_same_request_resend(self):
        waiting = asyncio.Event()
        async def respond(request):
            async with Trace("start_tls", logging.getLogger("httpcore.connection"), kwargs={"private": PRIVATE}):
                await asyncio.sleep(.001)
            async with Trace("receive_response_headers", LOGGER):
                if request.content == b'cancel':
                    waiting.set()
                    await asyncio.Event().wait()
                await asyncio.sleep(.001)
            return httpx.Response(200, json={"ok": True})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            shared = client.build_request("POST", "https://fixture.invalid/", content=b'same')
            with self.observing():
                canceled = asyncio.create_task(client.post("https://fixture.invalid/", content=b'cancel'), name=PRIVATE)
                successful = asyncio.create_task(client.send(shared))
                await waiting.wait()
                canceled.cancel()
                await asyncio.gather(canceled, return_exceptions=True)
                await successful
                await client.send(shared)
        rows = self.evidence()
        starts = [r for r in rows if r["event"] == "dispatch_start"]
        self.assertEqual(len(starts), 3)
        same = [r for r in starts if r["body_sha256"] == hashlib.sha256(b'same').hexdigest()]
        self.assertEqual(len({r["dispatch_id"] for r in same}), 2)
        failed = next(r for r in rows if r.get("failure_type") == "CancelledError")
        canceled_id = next(r["dispatch_id"] for r in starts if r["body_sha256"] == hashlib.sha256(b'cancel').hexdigest())
        self.assertEqual(failed["dispatch_id"], canceled_id)
        self.assertEqual(failed["outcome"], "failed")
        self.assertEqual(len(self.transport.rows), 3)
        self.assertEqual(self.observer.take()["open_dispatches"], [])

    async def test_response_body_consumed_in_another_task_keeps_exact_response(self):
        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                async with Trace("receive_response_body", LOGGER, kwargs={"headers": PRIVATE}):
                    await asyncio.sleep(.001)
                    yield b'{}'
            async def aclose(self):
                async with Trace("response_closed", LOGGER):
                    await asyncio.sleep(.001)
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Body()))) as client:
            with self.observing():
                first = await client.send(client.build_request("POST", "https://fixture.invalid/", content=b'first'), stream=True)
                second = await client.send(client.build_request("POST", "https://fixture.invalid/", content=b'second'), stream=True)
                await asyncio.gather(asyncio.create_task(second.aread()), asyncio.create_task(first.aread()))
        rows = self.evidence()
        for start in (r for r in rows if r["event"] == "dispatch_start"):
            body = [r for r in rows if r.get("phase") == "http11.receive_response_body"
                    and r["dispatch_id"] == start["dispatch_id"]]
            self.assertEqual(len(body), 2)
            self.assertNotEqual(body[0]["task_id"], start["task_id"])
            self.assertTrue(all(r["association"] == "matched" for r in body))

    async def test_unmatched_child_and_unknown_failure_are_not_guessed_or_leaked(self):
        secret_type = type(PRIVATE, (Exception,), {})
        async def unassociated():
            try:
                async with Trace("receive_response_headers", LOGGER, kwargs={"headers": PRIVATE}):
                    raise secret_type(PRIVATE)
            except secret_type:
                pass
            async with Trace(PRIVATE, LOGGER):
                pass
        async def respond(_):
            await asyncio.create_task(unassociated())
            return httpx.Response(200, json={"ok": True})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with self.observing():
                await client.get("https://fixture.invalid/?private=" + PRIVATE)
        rows = self.evidence()
        stages = [r for r in rows if r["event"].startswith("stage_")]
        self.assertEqual(len(stages), 2)
        self.assertTrue(all(r["dispatch_id"] is None and r["association"] == "unmatched" for r in stages))
        self.assertEqual(stages[-1]["failure_type"], "other")
        self.assertEqual(self.observer.take()["ignored_phase_boundaries"], 2)

    async def test_reused_response_cannot_be_attributed_to_either_send(self):
        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                async with Trace("receive_response_body", LOGGER):
                    yield b'{}'
        response = httpx.Response(200, stream=Body())
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)) as client:
            with self.observing():
                for body in (b'first', b'second'):
                    await client.send(client.build_request("POST", "https://fixture.invalid/", content=body), stream=True)
                await response.aread()
        stages = [r for r in self.evidence() if r["event"].startswith("stage_")]
        self.assertEqual(len(stages), 2)
        self.assertTrue(all(r["dispatch_id"] is None for r in stages))

    async def test_old_untracked_stream_inside_new_dispatch_stays_unmatched(self):
        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                async with Trace("receive_response_body", LOGGER):
                    yield b'old body'
            async def aclose(self):
                async with Trace("response_closed", LOGGER):
                    pass
        old = None
        async def respond(request):
            if request.content == b'old':
                return httpx.Response(200, stream=Body())
            async for _ in old.aiter_bytes():
                pass
            return httpx.Response(200, json={"new": True})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with self.observing():
                old = await client.send(client.build_request("POST", "https://fixture.invalid/", content=b'old'), stream=True)
                await client.post("https://fixture.invalid/", content=b'new')
        rows = self.evidence()
        body = [r for r in rows if r.get("phase") == "http11.receive_response_body"]
        closed = [r for r in rows if r.get("phase") == "http11.response_closed"]
        self.assertEqual(len(body), 2)
        self.assertTrue(all(r["dispatch_id"] is None and r["association"] == "unmatched" for r in body), body)
        self.assertEqual([r["dispatch_id"] for r in closed], [1, 1])

    async def test_yielded_trace_boundary_and_incomplete_segment(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def callback(name, info):
            await asyncio.sleep(.001)
        core_request = httpcore.Request("GET", "https://fixture.invalid/", extensions={"trace": callback})
        async def respond(_):
            async with Trace("send_request_body", LOGGER, core_request, kwargs={"private": PRIVATE}):
                entered.set()
                await release.wait()
            return httpx.Response(200, json={"ok": True})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with self.observing():
                pending = asyncio.create_task(client.get("https://fixture.invalid/"))
                await entered.wait()
                first = self.observer.take()
                release.set()
                await pending
        second = self.observer.take()
        self.assertEqual(len(first["open_dispatches"]), 1)
        self.assertEqual(len(first["open_stages"]), 1)
        self.assertEqual(second["open_stages"], [])
        self.assertEqual([r["event"] for r in first["events"]], ["dispatch_start", "stage_start"])
        self.assertEqual([r["event"] for r in second["events"]], ["stage_end", "dispatch_end"])
        self.assertEqual(first["open_stages"][0], second["events"][0]["stage_id"])
        self.assertEqual(self.observer.errors, [])

    def test_unsupported_pins_and_missing_caps_reject_before_output_or_env_loading(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            command = ["record", "--submission", str(root), "--kit", str(root), "--reference-kit", str(root),
                "--out", str(root / 'must-not-exist'), "--mode", "real-provider", "--delivery-evidence",
                "--env-file", str(root / 'must-not-read'), "--max-generation-requests", "1",
                "--max-embedding-requests", "0", "--cap-generation-model", "gemini-3.5-flash-lite"]
            for target, value in (("httpx.__version__", "unsupported"), ("httpcore.__version__", "unsupported"),
                                  ("sys.version_info", (3, 12, 0))):
                with self.subTest(target=target), patch(target, value), patch.object(sys, "argv", command), \
                        patch("dotenv.load_dotenv") as load, redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as stopped:
                        record.main()
                    self.assertEqual(stopped.exception.code, 2)
                    load.assert_not_called()
                    self.assertFalse((root / 'must-not-exist').exists())
            with patch.object(sys, "argv", command[:-6]), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    record.main()
                self.assertFalse((root / 'must-not-exist').exists())


def recorder_check(out):
    # Reuse the existing authored decision fixture, never an official scenario.
    from .decision_selfcheck import PLANNER, AGENT, EMBEDDING, EVALUATOR
    with tempfile.TemporaryDirectory(prefix="delivery-recorder-") as folder:
        root = Path(folder)
        kit, candidate = root / "kit", root / "candidate"
        (kit / "harness").mkdir(parents=True)
        (kit / "scenarios").mkdir()
        (candidate / "participant").mkdir(parents=True)
        (kit / "harness/__init__.py").write_text("")
        (kit / "harness/mock_env.py").write_text("TOOL_REGISTRY = {}\n")
        (kit / "submission.yaml").write_text("authored fixture\n")
        (kit / "eval_submission.py").write_text(EVALUATOR)
        (candidate / "participant/__init__.py").write_text("")
        (candidate / "PACKAGE_MANIFEST.json").write_text('{"source_git_revision":"authored-delivery-fixture"}')
        for name, code in {"planner": PLANNER, "agent": AGENT, "embedding": EMBEDDING}.items():
            (candidate / "participant" / (name + ".py")).write_text(code)
        for index, mode in enumerate(("clarification", "validation", "cancel")):
            (kit / "scenarios" / f"{index}-{mode}.json").write_text(json.dumps(
                {"scenario_id": mode, "mode": mode, "revision": index + 1, "events": [], "ground_truth": {}}))
        env = {key: os.environ[key] for key in ("SYSTEMROOT", "TEMP", "TMP") if key in os.environ}
        env["THREAD_API_KEY"] = "OFFLINE-CREDENTIAL-SENTINEL"
        command = [sys.executable, "-B", "-m", "evaluation.samsung_acceptance.record",
            "--submission", str(candidate), "--kit", str(kit), "--reference-kit", str(kit),
            "--mode", "real-provider", "--reps", "1", "--decision-evidence",
            "--max-generation-requests", "3", "--max-embedding-requests", "1",
            "--cap-generation-model", "gemini-3.5-flash-lite"]
        for flag in (False, True):
            target = out / ("enabled" if flag else "default")
            process = subprocess.run([*command, "--out", str(target), *(["--delivery-evidence"] if flag else [])],
                                     env=env, capture_output=True, timeout=30)
            (out / (target.name + ".stdout")).write_bytes(process.stdout)
            (out / (target.name + ".stderr")).write_bytes(process.stderr)
            assert process.returncode == 0, process.stderr.decode(errors="replace")
        for old in (out / "default").glob("attempt-[0-9]*.json"):
            before, after = json.loads(old.read_text()), json.loads((out / "enabled" / old.name).read_text())
            for field in ("trace", "score", "transport_requests", "decision_evidence", "request_budget"):
                assert before[field] == after[field], (old.name, field)
            assert "delivery_evidence" not in before
            assert after["delivery_evidence"]["httpcore_stages"] == "absent"
            assert sum(r["event"] == "dispatch_start" for r in after["delivery_evidence"]["events"]) == len(after["transport_requests"])
        manifest = json.loads((out / "enabled/manifest.json").read_text())
        assert manifest["sources_unchanged"] and not manifest["delivery_observer_errors"]
        assert manifest["request_budget"]["admitted_starts"] == {"generation": 3, "embedding": 1}
        # Same observer ordering must preserve the existing stop before dispatch.
        capped = command[:]
        capped[capped.index("--max-generation-requests") + 1] = "0"
        process = subprocess.run([*capped, "--delivery-evidence", "--out", str(out / "capped")],
                                 env=env, capture_output=True, timeout=30)
        assert process.returncode == 76
        stopped = json.loads((out / "capped/manifest.json").read_text())
        assert stopped["request_cap_stopped"] and stopped["request_budget"]["admitted_starts"] == {"generation": 0, "embedding": 0}
        for path in (out / "capped").glob("attempt-[0-9]*.json"):
            assert not json.loads(path.read_text())["delivery_evidence"]["events"]
        # Corrupt only observer bookkeeping once, inside an already-started
        # mocked send. The real capture catches it; the recorder must abort.
        effects = root / "fault-effects.jsonl"
        injected = '''
import logging
from pathlib import Path
from httpcore._trace import Trace
from evaluation.samsung_acceptance.delivery import DeliveryObserver
_capture = DeliveryObserver.capture
_injected = False
def fail_once(self, frame, event, result):
    global _injected
    if not _injected and frame.f_code is self.enter and event == 'return' and result is not None:
        _injected = True
        saved, self.stages = self.stages, None
        try: _capture(self, frame, event, result)
        finally: self.stages = saved
    else:
        _capture(self, frame, event, result)
DeliveryObserver.capture = fail_once
def effect(kind):
    with Path(EFFECT_PATH).open('a') as stream: stream.write(kind + '\\n')
'''.replace("EFFECT_PATH", repr(str(effects)))
        faulty = PLANNER.replace("            body = json.loads(request.content)",
            "            effect('send')\n            async with Trace('send_request_body', logging.getLogger('httpcore.http11')):\n                await asyncio.sleep(.001)\n            body = json.loads(request.content)")
        faulty = faulty.replace("async def close(self): await self.client.aclose()",
                               "async def close(self):\n        await self.client.aclose()\n        effect('client_closed')")
        (candidate / "participant/planner.py").write_text(injected + faulty)
        supervised = out / "capture-failure"
        process = subprocess.run([sys.executable, "-B", "-m", "evaluation.samsung_acceptance.run",
            "--out", str(supervised), "--wall-seconds", "15", "--", *command[4:], "--delivery-evidence"],
            env=env, capture_output=True, timeout=20)
        (out / "capture-failure.stdout").write_bytes(process.stdout)
        (out / "capture-failure.stderr").write_bytes(process.stderr)
        failed = json.loads((supervised / "run/manifest.json").read_text())
        status = json.loads((supervised / "run/process-status.json").read_text())
        calls = effects.read_text().splitlines()
        first = json.loads(next((supervised / "run").glob("attempt-001-*.json")).read_text())
        receipt = {"exit_code": process.returncode, "actual_mock_sends": calls.count("send"),
            "clients_closed": calls.count("client_closed"), "attempts": len(failed["attempts"]),
            "unrun": failed.get("unrun_attempts", []), "partial_status": first["status"],
            "partial_delivery_events": first["delivery_evidence"]["events"],
            "observer_errors": failed["delivery_observer_errors"], "budget": failed["request_budget"],
            "process_completed": status["completed"], "process_timed_out": status["timed_out"],
            "sources_unchanged": failed["sources_unchanged"], "provider_calls": 0}
        (out / "capture-failure-check.json").write_text(json.dumps(receipt, indent=2) + "\n")
        assert process.returncode == status["exit_code"] == 77, receipt
        assert failed["delivery_observer_error"] and first["status"] == "delivery_observer_error"
        assert not failed.get("quota_stopped") and not failed.get("request_cap_stopped")
        assert calls == ["send", "client_closed"] and len(failed["attempts"]) == 1, receipt
        assert len(failed["unrun_attempts"]) == 2 and all(
            r["status"] == "unrun_after_delivery_observer_error" for r in failed["unrun_attempts"])
        assert first["delivery_evidence"]["events"] and first["transport_requests"]
        assert failed["request_budget"]["admitted_starts"] == {"generation": 1, "embedding": 0}
        assert status["completed"] and not status["timed_out"] and failed["sources_unchanged"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=False)
    attempts = []
    original = socket.socket.connect
    def loopback_only(sock, address):
        if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "::1", "localhost"):
            attempts.append("external_connection_blocked")
            raise AssertionError("Offline controls permit loopback only")
        return original(sock, address)
    with patch.object(socket.socket, "connect", loopback_only), (args.out / "controls.log").open("w") as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(DeliveryChecks))
    assert result.wasSuccessful(), (args.out / "controls.log").read_text()
    recorder_check(args.out)
    receipt = {"passed": True, "focused_methods": result.testsRun, "recorder_default_and_opt_in_equal": True,
               "cap_stops_before_dispatch": True, "native_decisions_and_request_bodies_preserved": True,
               "capture_failure_stops_with_partial_unrun_and_cleanup": True,
               "external_network_attempts": attempts, "provider_calls": 0}
    (args.out / "checks.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
