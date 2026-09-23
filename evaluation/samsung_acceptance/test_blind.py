"""Generic structural controls only: no held-out inputs, real participant or network.

Temporary repeated records exercise the bundle schema, not new semantic stories.
The fake participant uses MockTransport, and every subprocess has a key-free env.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from . import blind, run
from .record import fingerprint, write_json
from .media_bindings import observe_media_reads
from .request_cap_selfcheck import transport_control


REPO = Path(__file__).resolve().parents[2]
PYTHON = sys.executable
MODEL = "gemini-generic-control"
SENTINEL = "WITHHELD_GENERIC_EXPECTATION"
PLANNER = '''
import asyncio, contextlib, hashlib, json, os
from pathlib import Path
import httpx
from . import embedding
sink = None
@contextlib.contextmanager
def planner_trace(callback):
    global sink
    sink = callback
    try: yield
    finally: sink = None
class Planner:
    async def setup(self):
        self.model = "gemini-generic-control"
        self.thinking, self.thinking_budget, self.image_embedding, self.timeout = "low", None, True, 2
        prewarm = "1"
        async def reply(request):
            await asyncio.sleep(.001)
            return httpx.Response(int(os.environ.get("FIXTURE_HTTP_STATUS", "200")), json={
                "candidates": [{"content": {"parts": [{"text": '{"response":"generic"}'}]}}],
                "embedding": {"values": [0.5, 0.5]}})
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
        await self._warmup()
    async def _warmup(self):
        response = await self.client.post("https://generativelanguage.googleapis.com/v1beta/models/" + self.model + ":generateContent", json={"setup": True})
    async def _decide(self, context):
        response = await self.client.post("https://generativelanguage.googleapis.com/v1beta/models/" + self.model + ":generateContent", json={"generic": True})
        record = {"phase": "planning", "status": response.status_code, "input_media": context.get("media", [])}
        if sink: sink(record)
        return {"response": "generic"}
    async def _perceive_audio(self):
        pass
    async def plan(self, context):
        if context.get("image"):
            await embedding.embed_image(self.client, context["media"][0])
        return await self._decide(context)
    async def close(self):
        await self.client.aclose()
        self.client = None
        with Path(os.environ["FIXTURE_CLOSED"]).open("a") as stream: stream.write("closed" + chr(10))
'''
AGENT = '''
import asyncio, hashlib, os
from .planner import Planner
from .media import MediaLoader
class ParticipantAgent:
    def __init__(self, in_q, out_q):
        self.in_q, self.out_q, self.planner = in_q, out_q, Planner()
        self.revision = 1
    async def setup(self):
        await self.planner.setup()
    async def _apply(self, decision):
        await self.out_q.put({"action": "final_response", "payload": {"text": decision["response"]}})
    async def run(self):
        try:
            while True:
                event = await self.in_q.get()
                assert "oracle" not in event and "answer" not in event
                if event["event_type"] == "tool_manifest": continue
                context = {"revision": 1, "media": []}
                for key, kind in (("audio_ref", "audio"), ("image_ref", "image")):
                    ref = event["payload"].get(key)
                    if ref:
                        raw, mime = await asyncio.to_thread(MediaLoader(os.environ["PARTICIPANT_MEDIA_ROOT"])._read, ref, kind)
                        context["media"].append({"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "mime_type": mime})
                        context["image"] = kind == "image"
                await self._apply(await self.planner.plan(context))
        finally:
            await self.planner.close()
'''
MEDIA = '''
from pathlib import Path
class MediaLoader:
    def __init__(self, root): self.root = Path(root)
    def _read(self, reference, kind):
        return (self.root / reference).read_bytes(), "audio/mpeg" if kind == "audio" else "image/png"
'''
EMBEDDING = '''
async def embed_image(client, source):
    response = await client.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:embedContent", json={"generic": True})
    evidence = {"input_sha256": source["sha256"], "input_bytes": source["bytes"], "status": "success"}
    return {"values": [0.5, 0.5], "evidence": evidence}
'''


def fixture(root):
    reference, candidate, bundle = [root / name for name in ("reference", "candidate", "bundle")]
    for path in (reference, candidate, bundle):
        path.mkdir()
    official = {"submission.yaml": "generic structural fixture\n", "harness/__init__.py": "",
                "harness/protocol.py": "def validate_action(action): return []\n"}
    for folder in (reference, candidate):
        for name, text in official.items():
            path = folder / name
            path.parent.mkdir(exist_ok=True)
            path.write_text(text, encoding="utf-8")
    (candidate / "participant").mkdir()
    for name, text in {"__init__.py": "", "agent.py": AGENT, "planner.py": PLANNER,
                       "media.py": MEDIA, "embedding.py": EMBEDDING}.items():
        (candidate / "participant" / name).write_text(text, encoding="utf-8")
    write_json(candidate / "PACKAGE_MANIFEST.json", {"files": fingerprint(candidate),
        "original_submission_yaml_sha256": blind.sha(reference / "submission.yaml"),
        "official_kit_files": {k: v for k, v in fingerprint(reference).items() if k != "submission.yaml"}})
    archive = candidate.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w") as zipped:
        for path in candidate.rglob("*"):
            if path.is_file(): zipped.write(path, path.relative_to(candidate).as_posix())
    (bundle / "generic.mp3").write_bytes(b"generic mocked speech bytes")
    (bundle / "generic.png").write_bytes(b"generic mocked image bytes")
    cases = []
    for mode, event_type, payload in (
        ("e2e_text", "user_speech_chunk", {"text": "generic", "end_of_turn": True}),
        ("e2e_audio", "user_audio_chunk", {"audio_ref": "generic.mp3", "end_of_turn": True}),
        ("e2e_visual", "video_frame", {"image_ref": "generic.png", "frame_id": "generic"})):
        for i in range(6):
            cases.append({"id": f"generic-{mode}-{i}", "mode": mode, "tools": {}, "replies": [], "tail_ms": 90,
                          "steps": [{"label": "generic", "at_ms": 0, "event": {"timestamp_ms": 0,
                                     "event_type": event_type, "payload": payload}}]})
    (bundle / "inputs.jsonl").write_text("\n".join(json.dumps(case) for case in cases), encoding="utf-8")
    (bundle / "answers.private.jsonl").write_text("\n".join(json.dumps({"id": case["id"], "oracle": [
        {"id": "one_generic_final", "op": "count", "select": {"kind": "action", "action": "final_response"}, "min": 1, "max": 1},
        {"id": "generic_text", "op": "text", "all_of": ["generic"]}],
        "private_note": SENTINEL}) for case in cases), encoding="utf-8")
    write_json(bundle / "provenance.json", {"scope": "generic structural control only"})
    freeze = {"files": {p.name: {"sha256": blind.sha(p), "bytes": p.stat().st_size} for p in bundle.iterdir()},
              "oracle_sources": {name: blind.sha(REPO / name) for name in
                  ("evaluation/samsung_challenge/oracle.py", "evaluation/samsung_challenge/semantic_oracle_v2.py")}}
    write_json(bundle / "FREEZE.json", freeze)
    return SimpleNamespace(candidate=candidate, kit=candidate, reference_kit=reference, bundle=bundle,
                           archive_sha256=blind.sha(archive), freeze_sha256=blind.sha(bundle / "FREEZE.json"))


class BlindControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="blind-generic-control-")
        cls.root = Path(cls.tmp.name)
        cls.args = fixture(cls.root)
        cls.env = {"SYSTEMROOT": os.environ.get("SYSTEMROOT", "C:\\Windows"), "PATH": os.defpath,
                   "PYTHONIOENCODING": "utf-8"}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def command(self, out, cap=40):
        a = self.args
        return [PYTHON, "-B", "-m", "evaluation.samsung_acceptance.run", "--worker", "adapter", "--out", str(out),
                "--wall-seconds", "20", "--", "--candidate", str(a.candidate), "--kit", str(a.kit),
                "--reference-kit", str(a.reference_kit), "--bundle", str(a.bundle),
                "--freeze-sha256", a.freeze_sha256, "--archive-sha256", a.archive_sha256,
                "--execution", "real-provider", "--clock", "real", "--max-generation-requests", str(cap),
                "--max-embedding-requests", "6", "--cap-generation-model", MODEL]

    def recorded(self, name, cap=40, status=200):
        out = self.root / name
        closed = self.root / (name + "-closed.txt")
        result = subprocess.run(self.command(out, cap), cwd=REPO,
            env={**self.env, "FIXTURE_HTTP_STATUS": str(status), "FIXTURE_CLOSED": str(closed)},
            capture_output=True, text=True, timeout=30)
        evidence = out / "run"
        manifest = blind.read(evidence / "manifest.json")
        rows = [blind.read(evidence / f"attempt-{i:03d}.json") for i in range(1, 19)]
        self.assertTrue(manifest["sources_unchanged"])
        self.assertNotIn(SENTINEL, result.stdout + result.stderr + "".join(json.dumps(row) for row in rows))
        self.assertTrue(blind.read(evidence / "process-status.json")["completed"])
        self.assertEqual(len(closed.read_text().splitlines()), sum(r["status"] != "unrun" for r in rows))
        return result, manifest, rows, evidence

    def test_combined_observers_and_private_review(self):
        result, manifest, rows, evidence = self.recorded("complete")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([r["status"] for r in rows], ["returned"] * 18)
        self.assertEqual(manifest["request_budget"]["admitted_starts"], {"generation": 36, "embedding": 6})
        self.assertFalse(any(manifest["observer_errors"].values()))
        self.assertTrue(all(any(r.get("kind") == "media_access" and r.get("status") == "read" for r in row["trace"]) for row in rows[6:]))
        self.assertTrue(all({"provider_response", "planner_return", "controller_apply"} <=
                            {d["stage"] for d in row["decision_evidence"]} for row in rows))
        self.assertTrue(all(any(d["stage"] == "embedding_return" and d["provider_response"].get("embedding_values") == [.5, .5]
                                for d in row["decision_evidence"]) for row in rows[12:]))
        args = SimpleNamespace(**vars(self.args), review_evidence=evidence)
        with patch.object(blind.importlib, "import_module", side_effect=AssertionError("Review imported participant")):
            report = blind.review(args)
        self.assertFalse(report["evidence_valid"])  # Mock transport is never real-provider evidence.
        self.assertFalse(report["semantic_qualification"])
        self.assertTrue(all(value for key, value in report["checks"].items() if key != "actual_provider_media_and_decisions"), report["checks"])
        path = evidence / "attempt-001.json"
        path.write_text(path.read_text() + " ")
        self.assertFalse(blind.review(args)["checks"]["hashed_receipts"])

    def test_frozen_input_tamper_rejects_before_candidate_import(self):
        root = self.root / "tamper-fixture"
        root.mkdir()
        args = fixture(root)
        args.out, args.provider_case_limit = root / "never-started", 20
        (args.bundle / "inputs.jsonl").write_text("changed generic bytes")
        with patch.object(blind.importlib, "import_module", side_effect=AssertionError("Imported candidate")):
            with self.assertRaisesRegex(ValueError, "Frozen bundle changed"):
                blind.execute(args)
        self.assertFalse(args.out.exists())

    def test_legacy_media_context_still_observes_and_restores(self):
        path = self.root / "standalone-media"
        path.write_bytes(b"generic")
        class Loader:
            root = path.parent
            def _read(self, reference): return (self.root / reference).read_bytes(), "image/png"
        rows = []
        driver = SimpleNamespace(log=lambda **row: rows.append(row))
        record = {"assets": [{"staged": str(path), "original_ref": path.name,
                  "sha256": blind.sha(path), "bytes": 7, "mime_type": "image/png"}]}
        with observe_media_reads(driver, record, Loader):
            self.assertEqual(Loader()._read(path.name)[0], b"generic")
        self.assertEqual([r["status"] for r in rows], ["read"])
        self.assertIsNone(sys.getprofile())

    def test_import_failure_retains_all_unrun_markers(self):
        args = SimpleNamespace(**vars(self.args), out=self.root / "import-failure", provider_case_limit=20,
            env_file=None, settle_turns=40, max_generation_requests=2, max_embedding_requests=0,
            cap_generation_model=MODEL)
        with patch.dict(os.environ, {}, clear=True), patch.object(blind.importlib, "import_module", side_effect=RuntimeError("generic failure")):
            result = blind.execute(args)
        self.assertFalse(result["execution_complete"])
        self.assertEqual(result["statuses"], {"unrun": 18})
        self.assertEqual(len(blind.read(args.out / "attempt-index.json")), 18)

    def test_embedding_review_rejects_fabricated_vector_and_stale_image(self):
        row = {"trace": [{"kind": "event", "event_type": "video_frame", "payload": {"image_ref": "generic.png"}},
                         {"action": "tool_call", "args": {"image_embedding": [.5, .5]}}],
               "transport_requests": [{"body_sha256": "request", "status": 200, "transport": "AsyncHTTPTransport",
                   "host": "generativelanguage.googleapis.com", "path": "/models/gemini-embedding-2:embedContent"}],
               "decision_evidence": [{"stage": "embedding_return", "request_body_sha256": "request",
                   "provider_response": {"http_status": 200, "embedding_values": [.5, .5]},
                   "value": {"values": [.5, .5]}, "runtime_metadata": {"input_sha256": "image", "input_bytes": 3}}]}
        binding = {"assets": [{"original_ref": "generic.png", "sha256": "image", "bytes": 3, "mime_type": "image/png"}]}
        self.assertTrue(blind.embedding_matches(row, binding))
        row["trace"][-1]["args"]["image_embedding"] = [.7, .3]
        self.assertFalse(blind.embedding_matches(row, binding))
        row["trace"][-1]["args"]["image_embedding"] = [.5, .5]
        row["decision_evidence"][0]["runtime_metadata"]["input_sha256"] = "stale-image"
        self.assertFalse(blind.embedding_matches(row, binding))

    def test_cap_spans_setup_and_later_cases(self):
        result, manifest, rows, _ = self.recorded("cap", cap=3)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([r["status"] for r in rows[:2]], ["returned", "request_cap_stopped"])
        self.assertTrue(all(r["status"] == "unrun" for r in rows[2:]))
        self.assertEqual(manifest["request_budget"]["admitted_starts"], {"generation": 3, "embedding": 0})
        self.assertEqual(sum(len(r.get("transport_requests", [])) for r in rows), 3)

    def test_zero_cap_stops_before_any_transport(self):
        _, manifest, rows, _ = self.recorded("zero", cap=0)
        self.assertEqual(rows[0]["status"], "request_cap_stopped")
        self.assertEqual(manifest["request_budget"]["admitted_starts"], {"generation": 0, "embedding": 0})
        self.assertTrue(all(not r.get("transport_requests") for r in rows))

    def test_first_429_stops_current_and_remaining_cases(self):
        _, manifest, rows, _ = self.recorded("quota", status=429)
        self.assertEqual(rows[0]["status"], "quota_stopped")
        self.assertEqual(len(rows[0]["http429_metadata"]), 1)
        self.assertTrue(all(r["status"] == "unrun" for r in rows[1:]))
        self.assertEqual(manifest["request_budget"]["admitted_starts"], {"generation": 1, "embedding": 0})

    def test_ordinary_http_failure_does_not_spend_a_retry(self):
        result, manifest, rows, _ = self.recorded("ordinary", status=500)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(all(r["status"] == "returned" for r in rows))
        self.assertIsNone(manifest["stop_reason"])
        self.assertEqual(manifest["request_budget"]["admitted_starts"], {"generation": 36, "embedding": 6})

    def test_existing_counter_handles_cancellation_reuse_and_endpoint_rejection(self):
        with patch.dict(os.environ, {}, clear=True):
            for mode in ("reuse", "cancelled", "separate", "concurrent", "method", "model", "query", "host"):
                with self.subTest(mode=mode):
                    transport_control(mode)

    def test_selectors_and_old_python_reject_before_execution(self):
        parser = SimpleNamespace(error=lambda message: (_ for _ in ()).throw(ValueError(message)))
        base = dict(vars(self.args), cases=None, oracle=None, partition=None, family=None, case_mode=None,
                    first_per_family=None, limit=None, block_family=[], settle_turns=40, provider_case_limit=20,
                    review_evidence=None, env_file=None, out=self.root / "never-created", execution="real-provider",
                    clock="real", max_generation_requests=2, max_embedding_requests=0, cap_generation_model=MODEL)
        with patch.object(blind, "execute", side_effect=AssertionError("Executed")):
            with self.assertRaises(ValueError): blind.main(SimpleNamespace(**{**base, "limit": 1}), parser)
            with patch.object(sys, "version_info", (3, 12)):
                with self.assertRaises(ValueError): blind.main(SimpleNamespace(**base), parser)
        self.assertFalse(base["out"].exists())

    def test_profile_collision_is_rejected_and_existing_profile_preserved(self):
        callback = lambda *args: None
        sys.setprofile(callback)
        try:
            with self.assertRaises(RuntimeError):
                with blind.profiles(callback, callback): pass
            self.assertIs(sys.getprofile(), callback)
        finally:
            sys.setprofile(None)

    def test_supervisor_timeout_reaps_adapter_and_preserves_public_default(self):
        class Process:
            pid, returncode, killed = 123, None, False
            def wait(self, timeout=None):
                if timeout is not None: raise subprocess.TimeoutExpired("generic", timeout)
                self.returncode = -9
            def kill(self): self.killed = True
        for worker in ("record", "adapter"):
            with self.subTest(worker=worker):
                out = self.root / ("supervisor-" + worker)
                extra = (["--submission", str(self.args.candidate)] if worker == "record" else
                         ["--candidate", str(self.args.candidate), "--bundle", str(self.args.bundle)])
                argv = ["run", "--out", str(out)] + ([] if worker == "record" else ["--worker", worker]) + ["--", *extra,
                    "--kit", str(self.args.kit), "--reference-kit", str(self.args.reference_kit)]
                process = Process()
                with patch.object(sys, "argv", argv), patch.object(run.subprocess, "Popen", return_value=process) as popen, contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised: run.main()
                self.assertEqual(raised.exception.code, 124)
                self.assertTrue(process.killed)
                self.assertEqual(process.returncode, -9)
                self.assertIn("evaluation.samsung_acceptance." + worker, popen.call_args.args[0])
                self.assertTrue(blind.read(out / "run/process-status.json")["timed_out"])
                self.assertTrue((out / "run/evidence-sha256.json").is_file())


class BlindCorrectionControls(unittest.TestCase):
    """Only observer-stop and local-text review corrections; no original stories."""
    setUpClass = classmethod(BlindControls.setUpClass.__func__)
    tearDownClass = classmethod(BlindControls.tearDownClass.__func__)
    command = BlindControls.command
    recorded = BlindControls.recorded

    def variant(self, name, planner=None, media=None):
        root = self.root / (name + "-sources")
        root.mkdir()
        with patch.multiple(sys.modules[__name__], PLANNER=planner or PLANNER, MEDIA=media or MEDIA):
            args = fixture(root)
        with patch.object(self, "args", args):
            result, manifest, rows, evidence = self.recorded(name)
        return args, result, manifest, rows, evidence

    def stopped(self, name, planner=None, media=None, attempt=1, generation=0, error_kind="decisions"):
        _, result, manifest, rows, _ = self.variant(name, planner, media)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(manifest["stop_reason"], "observer_stopped")
        self.assertEqual(rows[attempt - 1]["status"], "observer_stopped")
        self.assertTrue(manifest["observer_errors"][error_kind])
        self.assertTrue(rows[attempt - 1]["observer_errors"][error_kind])
        self.assertTrue(all(row["status"] == "unrun" and not row.get("transport_requests") for row in rows[attempt:]))
        self.assertEqual(manifest["request_budget"]["admitted_starts"], {"generation": generation, "embedding": 0})
        self.assertTrue(rows[attempt - 1]["trace"] or attempt == 1)

    def test_decision_capture_failure_stops_current_and_remaining_attempts(self):
        planner = PLANNER.replace('return {"response": "generic"}',
            'return {"response": "generic", "capture_control": "x" * 1048640}')
        self.stopped("decision-capture-error", planner=planner, generation=2)

    def test_quota_capture_failure_stops_before_later_dispatch(self):
        old = '        response = await self.client.post("https://generativelanguage.googleapis.com/v1beta/models/" + self.model + ":generateContent", json={"setup": True})'
        new = '''        class GenericBrokenQuotaMetadata:
            accesses = 0
            @property
            def status_code(self):
                self.accesses += 1
                if self.accesses > 1: raise ValueError("generic quota metadata fault")
                return 200
        response = GenericBrokenQuotaMetadata()'''
        self.assertIn(old, PLANNER)
        self.stopped("quota-capture-error", planner=PLANNER.replace(old, new), error_kind="quota")

    def test_threaded_media_capture_failure_stops_before_planning(self):
        media = MEDIA.replace('"audio/mpeg" if kind == "audio" else "image/png"', '"wrong/generic-mime"')
        self.stopped("media-capture-error", media=media, attempt=7, generation=13, error_kind="media")

    @staticmethod
    def local_planner(*, canceled=False, all_modes=False, fallback=False):
        gate = "True" if all_modes or fallback else 'not context.get("media")'
        body = f'    async def plan(self, context):\n        if {gate}:\n'
        if canceled:
            body += '''            old = asyncio.create_task(self._decide(context))
            await asyncio.sleep(0)
            old.cancel()
            await asyncio.gather(old, return_exceptions=True)
            if sink: sink({"revision": context["revision"], "phase": "planning", "status": "cancelled", "input_media": []})
'''
        if not fallback:
            body += '''            if sink: sink({"revision": context["revision"], "phase": "local_planning", "status": "local", "input_media": []})
'''
        body += '            return {"response": "' + ("unavailable" if fallback else "generic") + '"}'
        return PLANNER.replace("    async def plan(self, context):", body)

    def test_local_text_preserves_zero_planning_and_canceled_request_histories(self):
        for canceled in (False, True):
            with self.subTest(canceled=canceled):
                args, result, manifest, rows, evidence = self.variant("local-" + str(canceled), planner=self.local_planner(canceled=canceled))
                self.assertEqual(result.returncode, 0)
                self.assertEqual(manifest["request_budget"]["admitted_starts"], {"generation": 36 if canceled else 30, "embedding": 6})
                report = blind.review(SimpleNamespace(**vars(args), review_evidence=evidence))
                self.assertTrue(report["checks"]["bounded_requests"])
                for row in report["attempts"][:6]:
                    self.assertTrue(row["oracle"]["passed"])
                    self.assertTrue(row["execution_evidence_valid"])
                    self.assertEqual(row["execution_evidence"], "local_text_no_native")
                    self.assertFalse(row["native_planning"])
                self.assertFalse(report["semantic_qualification"])
                if canceled:
                    self.assertTrue(all(any(t["status"] == "no_response_observed" for t in row["transport_requests"]) for row in rows[:6]))
                    self.assertTrue(all(any(e.get("status") == "cancelled" for e in row["model_evidence"]) for row in rows[:6]))

    def test_media_without_native_proof_never_uses_local_text_admission(self):
        args, _, _, _, evidence = self.variant("media-local", planner=self.local_planner(all_modes=True))
        report = blind.review(SimpleNamespace(**vars(args), review_evidence=evidence))
        self.assertTrue(all(row["local_text_outcome"] for row in report["attempts"][:6]))
        self.assertTrue(all(not row["execution_evidence_valid"] and not row["local_text_outcome"] for row in report["attempts"][6:]))
        self.assertFalse(report["checks"]["actual_provider_media_and_decisions"])

    def test_failure_fallback_is_not_labeled_a_deterministic_shortcut(self):
        args, _, _, _, evidence = self.variant("fallback", planner=self.local_planner(fallback=True))
        report = blind.review(SimpleNamespace(**vars(args), review_evidence=evidence))
        self.assertTrue(all(not row["local_text_outcome"] and not row["execution_evidence_valid"]
                            and not row["oracle"]["passed"] for row in report["attempts"]))
        self.assertTrue(all(row["execution_evidence"] == "no_verified_local_or_native_outcome" for row in report["attempts"]))


class BlindTerminalProvenanceControls(unittest.TestCase):
    """Generic same-revision provenance sequences; no participant execution."""
    @staticmethod
    def sequence(order):
        case = {"mode": "e2e_text", "steps": [{"event": {"payload": {"text": "generic"}}}]}
        row = {"status": "returned", "trace": [], "model_evidence": [], "decision_evidence": []}
        for kind, value, apply in order:
            row["model_evidence"].append({"revision": 1, "input_media": [],
                "phase": "local_planning" if kind == "local" else "planning",
                "status": "local" if kind == "local" else "cancelled" if kind == "cancelled" else 200})
            if kind == "native":
                row["decision_evidence"].append({"stage": "provider_response", "phase": "planning",
                    "revision": 1, "provider_response": {"http_status": 200}})
            row["decision_evidence"].append({"stage": "planner_return", "revision": 1,
                "return_state": "no_return_value" if value is None else "returned", "value": value})
            if apply:
                row["decision_evidence"].append({"stage": "controller_apply", "revision": 1, "decision": value})
        return case, row, {"passed": True}

    def test_same_revision_local_then_native_is_not_a_local_outcome(self):
        local = {"response": "generic local"}
        for native in ({"response": "generic native"}, local):
            with self.subTest(equal_values=native == local):
                self.assertFalse(blind.local_text_outcome(*self.sequence([
                    ("local", local, True), ("native", native, True)])))

    def test_earlier_native_or_canceled_then_final_local_remains_local(self):
        for kind, earlier in (("native", {"response": "generic native"}), ("cancelled", None)):
            with self.subTest(earlier=kind):
                self.assertTrue(blind.local_text_outcome(*self.sequence([
                    (kind, earlier, earlier is not None), ("local", {"response": "generic local"}, True)])))

    def test_later_unapplied_return_cannot_borrow_an_earlier_local_apply(self):
        local = {"response": "generic local"}
        for later in ({"response": "generic later"}, local):
            with self.subTest(equal_values=later == local):
                self.assertFalse(blind.local_text_outcome(*self.sequence([
                    ("local", local, True), ("local", later, False)])))


if __name__ == "__main__":
    unittest.main()
