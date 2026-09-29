"""Bounded real-clock controller probes after a local unknown write outcome.

Uses an explicitly injected planner and simulated tool results. No provider or
external service is called; frozen challenge definitions remain unchanged.
"""
import argparse
import asyncio
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import sys
import time


class Planner:
    async def setup(self):
        pass

    async def close(self):
        pass

    async def plan(self, context):
        if context["messages"][-1]["event_type"] == "interruption":
            return {"intent": "cancel", "slots": {}, "response": "Stopped work on that request."}
        return {"intent": "create_note", "slots": {}, "tool_calls": [{
            "api_name": "create_note", "args": {"text": "ready"},
            "authorization": {"quote": "Create a note saying ready.", "message_index": 0},
            "response_template": "Saved {note_id}."}]}


async def probe(cls, variant):
    incoming, outgoing = asyncio.Queue(), asyncio.Queue()
    started = time.perf_counter()
    trace = []
    processed = {}

    def now():
        return round((time.perf_counter() - started) * 1000, 3)

    class ObservedAgent(cls):
        def _handle(self, event):
            trace.append({"t_ms": now(), "kind": "handler_enter", "event_type": event.get("event_type"),
                          "call_id": event.get("payload", {}).get("call_id")})
            try:
                return super()._handle(event)
            finally:
                trace.append({"t_ms": now(), "kind": "handler_exit", "event_type": event.get("event_type"),
                              "call_id": event.get("payload", {}).get("call_id")})
                processed[id(event)].set()

    agent = ObservedAgent(incoming, outgoing, planner=Planner())
    await agent.setup()

    def send(event_type, payload):
        trace.append({"t_ms": now(), "kind": "input", "event_type": event_type, "payload": deepcopy(payload)})
        event = {"timestamp_ms": now(), "event_type": event_type, "payload": payload}
        handled = processed[id(event)] = asyncio.Event()
        incoming.put_nowait(event)
        return handled

    async def take(predicate, timeout=1.2):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                value = await asyncio.wait_for(outgoing.get(), timeout=max(.001, deadline - time.monotonic()))
            except asyncio.TimeoutError:
                return None
            trace.append({"t_ms": now(), "kind": "output", **deepcopy(value)})
            if predicate(value):
                return value
        return None

    def drain():
        while not outgoing.empty():
            trace.append({"t_ms": now(), "kind": "output", **deepcopy(outgoing.get_nowait())})

    async def run():
        try:
            await agent.run()
        finally:
            trace.append({"t_ms": now(), "kind": "agent_exit"})

    task = asyncio.create_task(run())
    hard_stop = None
    tail_ms = None
    checks = {}
    call_id = None
    try:
        upper = 10000 if variant == "near_tail_matching_success" else 10
        send("tool_manifest", {"tools": {"create_note": {"kind": "state_modifying", "delay_range_ms": [0, upper],
             "description": "Create a note and return its note_id.", "args": {"text": {"type": "string", "required": True}}}}})
        send("user_speech_chunk", {"text": "Create a note saying ready.", "end_of_turn": True})
        call = await take(lambda row: row.get("action") == "tool_call")
        if call is None:
            return {"probe": variant, "passed": False, "checks": {"authorized_dispatch": False}, "trace": trace}
        call_id = call["payload"]["call_id"]
        send("scenario_end", {})
        if variant == "near_tail_matching_success":
            tail_ms = now() + 6000

            def stop():
                trace.append({"t_ms": now(), "kind": "hard_stop"})
                task.cancel()

            hard_stop = asyncio.get_running_loop().call_later(6.0, stop)
            trace.append({"t_ms": now(), "kind": "hard_stop_scheduled", "nominal_tail_ms": tail_ms})
        if variant == "cancel_pending_then_success":
            send("interruption", {"text": "Never mind that note. Stop this request."})
            await take(lambda row: row.get("action") == "final_response")
        else:
            unknown = await take(lambda row: row.get("action") == "final_response" and "could not confirm" in row.get("payload", {}).get("text", ""), timeout=6.1)
            checks["local_unknown_observed"] = unknown is not None and agent.operations[call_id]["status"] == "unknown"
        if variant == "stale_revision_then_success":
            send("interruption", {"text": "Never mind that note. Stop this request."})
            await take(lambda row: row.get("action") == "final_response" and "Stopped" in row.get("payload", {}).get("text", ""))
        result = {"call_id": call_id, "api_name": "create_note", "status": "success", "result": {"status": "success", "note_id": "NOTE-LATE"}}
        if variant in {"wrong_api_then_success", "wrong_call_then_success"}:
            wrong = deepcopy(result)
            wrong["api_name" if variant == "wrong_api_then_success" else "call_id"] = "foreign-identity"
            handled = send("tool_result", wrong)
            await asyncio.wait_for(handled.wait(), timeout=.3)
            drain()
            checks["wrong_identity_ignored"] = agent.operations[call_id]["status"] == "unknown" and "note_id" not in agent.state["slots"]
        if variant == "definite_error_then_conflicting_success":
            handled = send("tool_result", {"call_id": call_id, "api_name": "create_note", "status": "error", "result": {"status": "error", "error": "invalid_args", "detail": "No operation committed."}})
            await asyncio.wait_for(handled.wait(), timeout=.3)
            drain()
        await asyncio.sleep(.04 if variant == "near_tail_matching_success" else .025)
        before_success = len(trace)
        if tail_ms is not None:
            checks["success_queued_before_nominal_tail"] = now() < tail_ms
            checks["success_queued_while_running"] = not task.done() and task.cancelling() == 0
        handled = send("tool_result", result)
        positive = variant in {"matching_success", "wrong_api_then_success", "wrong_call_then_success", "near_tail_matching_success"}
        if positive:
            final = await take(lambda row: row.get("action") == "final_response" and "NOTE-LATE" in row.get("payload", {}).get("text", ""), timeout=.3)
            checks["matched_success_reconciled"] = agent.operations[call_id]["status"] == "success"
            checks["corrected_final_emitted"] = final is not None
            if tail_ms is not None:
                checks["matched_result_handler_entered"] = handled.is_set()
        else:
            await asyncio.wait_for(handled.wait(), timeout=.3)
            drain()
            later = trace[before_success:]
            checks["no_obsolete_confirmation"] = not any(row.get("kind") == "output" and row.get("action") == "final_response" and "NOTE-LATE" in row.get("payload", {}).get("text", "") for row in later)
            checks["no_old_receipt_promoted"] = "note_id" not in agent.state["slots"]
            checks["ledger_rule"] = agent.operations[call_id]["status"] == ("error" if variant == "definite_error_then_conflicting_success" else "success")
        drain()
        checks["one_write_no_retry"] = sum(row.get("kind") == "output" and row.get("action") == "tool_call" for row in trace) == 1
        return {"probe": variant, "passed": all(checks.values()), "checks": checks,
                "final_operation": deepcopy(agent.operations[call_id]), "trace": trace}
    finally:
        if hard_stop:
            hard_stop.cancel()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Preserve earlier review attempts; choose a new output file")
    root = args.candidate.resolve()
    paths = sorted((root / "participant").glob("*.py"))
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    sys.path.insert(0, str(root))
    module = importlib.import_module("participant.agent")
    if not Path(module.__file__).resolve().is_relative_to(root):
        raise ValueError("Wrong participant import")
    variants = ["matching_success", "wrong_api_then_success", "wrong_call_then_success", "stale_revision_then_success",
                "cancel_pending_then_success", "definite_error_then_conflicting_success", "near_tail_matching_success"]
    results = [asyncio.run(probe(module.ParticipantAgent, variant)) for variant in variants]
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    report = {"scope": "Seven supplemental real-clock controller probes, explicitly injected planner and simulated results; not additional frozen cases or actual-provider runs.",
              "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "clock": "Unmodified real monotonic controller timers; trace timestamps use perf_counter. Local subclass records handler entry/exit without changing behavior.",
              "source_sha256": before, "sources_unchanged": before == after, "import_path": module.__file__,
              "provider_calls": 0, "external_service_calls": 0, "passed": sum(r["passed"] for r in results), "total": len(results), "results": results}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, indent=2))
    for row in results:
        print(json.dumps({key: value for key, value in row.items() if key in {"probe", "passed", "checks"}}))
    raise SystemExit(0 if before == after and all(row["passed"] for row in results) else 1)


if __name__ == "__main__":
    main()
