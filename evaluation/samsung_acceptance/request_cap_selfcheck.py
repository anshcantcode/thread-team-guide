"""Offline dispatch-cap and ordinary-failure continuation controls.

Uses httpx MockTransport and an authored miniature evaluator, never a live
provider or the official kit. Reuses the real recorder and process supervisor.
"""
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import httpx

from .quota import RequestCapStop, TransportObserver


MODEL = "gemini-3.5-flash-lite"
GEN = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
EMBED = "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:embedContent"


def transport_control(mode):
    observer = TransportObserver({"generation": 2 if mode == "reuse" else 1, "embedding": 1}, MODEL)
    sent, clients, owned = [], [], []

    async def reply(request):
        sent.append(str(request.url))
        await asyncio.sleep(.001)
        return httpx.Response(200, json={})

    async def go():
        owned.append(asyncio.current_task())
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            clients.append(client)
            if mode == "reuse":
                request = client.build_request("POST", GEN, content=b"fixture")
                for _ in range(3):
                    await client.send(request)
                    observer.rows.clear()  # Same clearing boundary as each case.
            elif mode == "cancelled":
                task = asyncio.create_task(client.post(GEN, content=b"fixture"))
                await asyncio.sleep(0)
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                await client.post(GEN, content=b"fixture")
            elif mode == "separate":
                await client.post(GEN, content=b"fixture")
                await client.post(EMBED, content=b"fixture")
                await client.post(EMBED, content=b"fixture")
            elif mode == "concurrent":
                tasks = [asyncio.create_task(client.post(GEN, content=b"fixture")) for _ in range(2)]
                owned.extend(tasks)
                try:
                    await asyncio.gather(*tasks)
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
            else:
                method, url = {"method": ("GET", GEN), "model": ("POST", GEN.replace(MODEL, "gemini-other")),
                               "query": ("POST", GEN + "?key=PRIVATE-SENTINEL"),
                               "host": ("POST", GEN.replace("googleapis.com", "invalid"))}[mode]
                await client.request(method, url, content=b"fixture")

    sys.setprofile(observer.capture)
    try:
        try:
            asyncio.run(go())
        except RequestCapStop as exc:
            assert exc.code == 76
        else:
            raise AssertionError("Unallocated request was not stopped")
    finally:
        sys.setprofile(None)
    for task in owned:
        assert task.done()
        if not task.cancelled():
            error = task.exception()
            assert error is None or isinstance(error, RequestCapStop)
    expected = {"reuse": (2, {"generation": 2, "embedding": 0}),
                "cancelled": (1, {"generation": 1, "embedding": 0}),
                "concurrent": (1, {"generation": 1, "embedding": 0}),
                "separate": (2, {"generation": 1, "embedding": 1})}.get(mode, (0, {"generation": 0, "embedding": 0}))
    assert len(sent) == expected[0] and observer.counts == expected[1]
    assert all(client.is_closed for client in clients) and len(observer.blocked) == 1 and not observer.errors
    assert "PRIVATE-SENTINEL" not in json.dumps(observer.budget())


def main():
    process_checks = []
    for mode in ("reuse", "cancelled", "separate", "concurrent", "method", "model", "query", "host"):
        transport_control(mode)
    with tempfile.TemporaryDirectory(prefix="acceptance-cap-control-") as folder:
        root = Path(folder)
        kit, candidate = root / "kit", root / "candidate"
        (kit / "scenarios").mkdir(parents=True)
        (kit / "harness").mkdir()
        (kit / "harness/__init__.py").write_text("")
        (kit / "harness/mock_env.py").write_text("TOOL_REGISTRY = {}\n")
        (kit / "submission.yaml").write_text("authored fixture\n")
        for index in range(4):
            (kit / f"scenarios/fixture_{index}.json").write_text(json.dumps(
                {"scenario_id": f"fixture_{index}", "events": [], "ground_truth": {}}))
        (candidate / "participant").mkdir(parents=True)
        (candidate / "participant/__init__.py").write_text("")
        (candidate / "PACKAGE_MANIFEST.json").write_text('{"source_git_revision":"authored-cap-fixture"}')
        (kit / "eval_submission.py").write_text('''
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from participant.planner import Planner
CONCURRENT = False
def run_once(scenario, cls, time_scale, wall_cap_s, setup_cap_s):
    trace = [{"kind":"authored_fixture", "t_ms":0}]
    async def go():
        planner=Planner()
        await planner.setup()
        tasks=[]
        try:
            if CONCURRENT:
                async def later():
                    await asyncio.sleep(.1)
                    await planner._decide()
                tasks=[asyncio.create_task(planner._decide()) for _ in range(2)]
                tasks.append(asyncio.create_task(later()))
                await asyncio.gather(*tasks)
            else:
                await planner._decide()
        finally:
            for task in tasks: task.cancel()
            if tasks: await asyncio.gather(*tasks, return_exceptions=True)
            await planner.close()
    asyncio.run(go())
    return {"scenario_id":scenario["scenario_id"], "total":0, "breakdown":{}}
for path in sorted((Path(__file__).parent / "scenarios").glob("*.json")):
    run_once(json.loads(path.read_text()), None, 1, 120, 300)
''')
        evaluator = (kit / "eval_submission.py").read_text()
        for label, cap, status_code in (("ordinary_failures", None, 200), ("cap", 2, 200),
                                        ("zero", 0, 200), ("quota", 10, 429), ("prescenario", 1, 200),
                                        ("cap_concurrent", 1, 200), ("quota_concurrent", 10, 429)):
            code = evaluator.replace("CONCURRENT = False", "CONCURRENT = True") if label.endswith("_concurrent") else evaluator
            (kit / "eval_submission.py").write_text(code.replace('for path in sorted(', '''
async def smoke():
    planner=Planner()
    await planner.setup()
    try: await planner._decide()
    finally: await planner.close()
asyncio.run(smoke())
for path in sorted(''') if label == "prescenario" else code)
            log = root / (label + ".jsonl")
            (candidate / "participant/planner.py").write_text(f'''
import asyncio, json
from contextlib import nullcontext
from pathlib import Path
import httpx
def planner_trace(observer): return nullcontext()
def log(kind):
    with Path({str(log)!r}).open("a") as stream: stream.write(json.dumps({{"kind":kind}})+"\\n")
class Planner:
    client=None
    async def setup(self):
        async def reply(request):
            log("actual_mock_transport")
            await asyncio.sleep(.001)
            return httpx.Response({status_code},json={{"error":{{"details":[]}}}})
        self.client=httpx.AsyncClient(transport=httpx.MockTransport(reply))
    async def _decide(self):
        response=await self.client.post({GEN!r},content=b"authored-fixture")
        response.raise_for_status()
    async def close(self):
        await self.client.aclose()
        log("client_closed")
''')
            out = root / label
            command = [sys.executable, "-B", "-m", "evaluation.samsung_acceptance.run", "--out", str(out),
                       "--wall-seconds", "10", "--", "--submission", str(candidate), "--kit", str(kit),
                       "--reference-kit", str(kit), "--scenarios", str(kit / "scenarios"),
                       "--mode", "real-provider", "--reps", "1", "--time-scale", "1"]
            if cap is not None:
                command += ["--max-generation-requests", str(cap), "--max-embedding-requests", "2",
                            "--cap-generation-model", MODEL]
            process = subprocess.run(command, capture_output=True, timeout=15)
            m = json.loads((out / "run/manifest.json").read_text())
            status = json.loads((out / "run/process-status.json").read_text())
            entries = [json.loads(line)["kind"] for line in log.read_text().splitlines()]
            quota_stop = label in {"quota", "quota_concurrent"}
            wanted = 4 if label == "ordinary_failures" else 2 if label == "quota_concurrent" else 1 if quota_stop else cap
            assert entries.count("actual_mock_transport") == wanted
            assert status["completed"] and status["exit_code"] == process.returncode
            assert m["sources_unchanged"] and not m["observer_errors"] and not m["transport_observer_errors"], (
                label, m["sources_unchanged"], m["observer_errors"], m["transport_observer_errors"])
            assert entries.count("client_closed") == len(m["attempts"]) + (label == "prescenario")
            assert not any(row["accepted"] for row in m["attempts"])
            if label == "ordinary_failures":
                assert process.returncode == 0 and len(m["attempts"]) == 4
                assert m["request_caps"] is None
            else:
                reason = "quota_stopped" if quota_stop else "request_cap_stopped"
                assert process.returncode == (75 if quota_stop else 76) and m[reason]
                assert m["request_budget"]["admitted_starts"] == {"generation": wanted, "embedding": 0}
                if label == "prescenario":
                    assert len(m["prescenario_transport_requests"]) == 1
                assert len(m["attempts"]) + len(m["unrun_attempts"]) == 4
                current = json.loads(next((out / "run").glob(f"attempt-{len(m['attempts']):03d}-fixture_*.json")).read_text())
                assert current["status"] == reason and current["score"] is None
            process_checks.append({"control": label, "exit_code": process.returncode,
                "actual_mock_transports": entries.count("actual_mock_transport"),
                "closed_clients": entries.count("client_closed"), "attempts": len(m["attempts"]),
                "unrun": len(m.get("unrun_attempts", [])), "source_unchanged": m["sources_unchanged"],
                "child_completed": status["completed"], "budget": m.get("request_budget")})
    print(json.dumps({"process_controls": process_checks, "real_provider_calls": 0}))
    print("Offline cap controls passed: unique/reused/resumed/canceled sends, separate budgets, exact endpoints, zero/total caps, ordinary-failure continuation, 429 stop and child/client cleanup; provider calls=0")


if __name__ == "__main__":
    main()
