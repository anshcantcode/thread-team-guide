"""Offline adapter checks; the tiny agent below is not a participant/model run."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
from pathlib import Path

from . import adapter


class OwnedPlanner:
    client = object()


class RealStyleAgent:
    """Owns its planner and emits a call after the scheduler starts waiting."""

    def __init__(self, in_q, out_q):
        self.in_q, self.out_q = in_q, out_q
        self.planner = OwnedPlanner()
        self.received, self.pending = [], []

    async def setup(self):
        pass

    async def delayed_call(self):
        await asyncio.sleep(0.1)
        await self.out_q.put({"action": "tool_call", "payload": {
            "call_id": "offline-call", "api_name": "lookup", "args": {"city": "Current"}}})

    async def run(self):
        try:
            while True:
                event = await self.in_q.get()
                self.received.append(event)
                if event["event_type"] == "user_speech_chunk":
                    self.pending.append(asyncio.create_task(self.delayed_call()))
                if event["event_type"] == "tool_result":
                    await self.out_q.put({"action": "final_response", "payload": {
                        "text": json.dumps(event["payload"]["result"])},
                        "state_snapshot": {"intent": "lookup", "slots": {}}})
        finally:
            for task in self.pending:
                task.cancel()
            await asyncio.gather(*self.pending, return_exceptions=True)
            self.planner.client = None


def fixture():
    return {
        "id": "PRIVATE-CASE-METADATA", "oracle": [{"private": "ORACLE-MARKER"}],
        "tools": {"lookup": {"kind": "read_only", "args": {
            "city": {"type": "string", "required": True}}}},
        "steps": [
            {"label": "request", "at_ms": 0, "event": {"timestamp_ms": 0,
                "event_type": "user_speech_chunk", "payload": {"text": "Look up Current.", "end_of_turn": True}}},
            {"label": "end", "at_ms": 5, "event": {"timestamp_ms": 5,
                "event_type": "scenario_end", "payload": {}}},
        ],
        "replies": [{"api_name": "lookup", "call_index": 0, "delay_ms": 10,
            "deliveries": [{"offset_ms": 0, "result": {"status": "success", "city": "Current"}}]}],
        "tail_ms": 500,
    }


async def check(module):
    instances = []

    def construct(in_q, out_q):
        agent = RealStyleAgent(in_q, out_q)
        instances.append(agent)
        return agent

    driver = module.Driver(fixture(), construct, lambda action: [], clock_mode="real", injected=False)
    trace = await driver.run()
    results = [row for row in trace if row.get("kind") == "tool_completed"]
    finals = [row for row in trace if row.get("action") == "final_response"]
    visible = json.dumps(instances[0].received)
    checks = {
        "no_planner_injection": type(driver.planner) is OwnedPlanner,
        "new_reply_wakes_real_scheduler": len(results) == 1 and results[0]["t_ms"] < 300,
        "result_reaches_agent_within_tail": len(finals) == 1 and finals[0]["t_ms"] < 300,
        "only_runtime_input_delivered": "PRIVATE-CASE-METADATA" not in visible and "ORACLE-MARKER" not in visible,
        "clean_shutdown": trace[-1].get("pending_tasks") == 0 and trace[-1].get("planner_closed") is True,
    }
    args_trace = []
    if hasattr(module, "matches_args"):
        args_case = fixture()
        args_case["replies"] = [
            {"api_name": "lookup", "call_index": 0, "match_args": {"city": "Obsolete"}, "delay_ms": 10,
             "deliveries": [{"result": {"status": "success", "city": "Obsolete"}}]},
            {"api_name": "lookup", "call_index": 42, "match_args": {"city": "Current"}, "delay_ms": 10,
             "deliveries": [{"result": {"status": "success", "city": "Current"}}]},
        ]
        args_driver = module.Driver(args_case, construct, lambda action: [], clock_mode="real", injected=False)
        args_trace = await args_driver.run()
        args_results = [row for row in args_trace if row.get("kind") == "tool_completed"]
        checks["reply_selected_by_args_ignoring_call_index"] = (
            len(args_results) == 1 and args_results[0]["result"]["city"] == "Current")
        checks["args_nested_subset"] = module.matches_args(
            {"opts": {"a": 2, "b": "extra"}}, {"opts": {"a": 2}})
        checks["args_do_not_coerce_bool_or_string"] = not module.matches_args(
            {"a": True}, {"a": 1}) and not module.matches_args({"a": "1"}, {"a": 1})
        checks["args_exact_array_order_length"] = not module.matches_args(
            {"a": [1, 2]}, {"a": [2, 1]}) and not module.matches_args({"a": [1, 2]}, {"a": [1]})
        checks["args_do_not_match_missing_fields"] = not module.matches_args({}, {"city": "Current"})
        checks["json_numbers_match_across_int_float"] = module.matches_args({"a": 1.0}, {"a": 1})
    return {"synthetic_adapter_check": True, "provider_calls": 0, "checks": checks,
            "trace": trace, "args_trace": args_trace}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", type=Path, help="Preserved earlier adapter for a negative control")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    module = adapter
    if args.adapter:
        spec = importlib.util.spec_from_file_location("evaluation.samsung_acceptance._prior_adapter", args.adapter)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    report = asyncio.run(check(module))
    if args.out.exists():
        raise FileExistsError("Preserve the earlier report; select a new output path")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in ("trace", "args_trace")}, indent=2))
    raise SystemExit(0 if all(report["checks"].values()) else 1)


if __name__ == "__main__":
    main()
