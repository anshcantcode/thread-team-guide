"""Execute independent challenges with explicit controller or real-provider modes.

This is deliberately NOT the official evaluator. Only the fixture scheduler uses
virtual time; production clocks and asyncio are not patched. Timeout/network/media
quality claims therefore require real-provider, real-clock evidence, with the
official public results obtained separately from the unchanged evaluator.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from contextlib import nullcontext
from copy import deepcopy
import hashlib
import heapq
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

from .record import fingerprint, write_json


def matches_args(actual, expected):
    """Contract: object subset, ordered lists, JSON numbers excluding bools."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and matches_args(actual[key], value) for key, value in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(
            matches_args(a, e) for a, e in zip(actual, expected))
    if type(expected) in (int, float):
        return type(actual) in (int, float) and actual == expected
    return type(actual) is type(expected) and actual == expected


def provider_unavailable(evidence):
    """A returned decision or ordinary task failure is not a provider outage."""
    statuses = [row.get("status") for row in evidence if row.get("phase") == "planning"]
    return 200 not in statuses and any(
        status in {400, 401, 403, 404, 429, 500, 502, 503, 504, "transport_error"}
        for status in statuses)


class ScriptedPlanner:
    def __init__(self, driver):
        self.driver, self.used, self.closed = driver, set(), False

    async def setup(self):
        pass

    async def close(self):
        self.closed = True

    def substitute(self, value):
        if isinstance(value, dict):
            if set(value) == {"$call_id"}:
                ref = value["$call_id"]
                key = (ref["api_name"], ref["call_index"])
                if key not in self.driver.call_ids:
                    raise ValueError(f"Missing fixture call binding {key}")
                return self.driver.call_ids[key]
            return {key: self.substitute(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.substitute(item) for item in value]
        return value

    async def plan(self, context):
        rules = []
        for index, rule in enumerate(self.driver.case.get("injected_plans", [])):
            if index in self.used:
                continue
            trigger = rule["trigger"]
            milestone = self.driver.step_seen.get(trigger["after_step"])
            if milestone is None:
                continue
            if "after_result" in trigger:
                result = trigger["after_result"]
                key = (result["api_name"], result["call_index"], result["delivery_index"])
                if key not in self.driver.result_seen:
                    continue
                milestone = max(milestone, self.driver.result_seen[key])
            rules.append((milestone, index, rule))
        if not rules:
            self.driver.log(kind="planner_call", matched_rule=None, revision=context.get("revision"))
            return {}
        _, index, rule = max(rules, key=lambda item: (item[0], item[1]))
        self.used.add(index)
        self.driver.log(kind="planner_call", matched_rule=index, revision=context.get("revision"))
        deadline = self.driver.now + rule.get("delay_ms", 0)
        while self.driver.now < deadline:
            try:
                await self.driver.delay_until(deadline)
            except asyncio.CancelledError:
                self.driver.log(kind="planner_cancelled", matched_rule=index,
                                resisted=bool(rule.get("resist_cancel") and not self.driver.stopping))
                if not rule.get("resist_cancel") or self.driver.stopping:
                    raise
        try:
            return self.substitute(deepcopy(rule["decision"]))
        except (KeyError, ValueError) as exc:
            self.driver.log(kind="adapter_error", error=str(exc))
            raise


class Driver:
    def __init__(self, case, cls, validate_action, settle_turns=40, clock_mode="virtual", injected=True):
        self.case, self.cls, self.validate_action = case, cls, validate_action
        self.clock_mode, self.started = clock_mode, None
        self.now, self.order, self.milestone = 0.0, 0, 0
        self.heap, self.trace = [], []
        self.schedule_changed = asyncio.Event()
        self.in_q, self.out_q = asyncio.Queue(), asyncio.Queue()
        self.step_seen, self.result_seen, self.call_ids = {}, {}, {}
        self.counts, self.operations = Counter(), {}
        self.stopping = False
        self.settle_turns = settle_turns
        self.injected = injected
        self.planner = ScriptedPlanner(self) if injected else None

    @property
    def now(self):
        if self.clock_mode == "real" and self.started is not None:
            return (time.monotonic() - self.started) * 1000
        return self._now

    @now.setter
    def now(self, value):
        self._now = value

    def log(self, **entry):
        self.trace.append({"t_ms": self.now, **entry})

    def schedule(self, at, callback):
        self.order += 1
        heapq.heappush(self.heap, (float(at), self.order, callback))
        self.schedule_changed.set()

    async def delay_until(self, at):
        future = asyncio.get_running_loop().create_future()
        self.schedule(at, lambda: None if future.done() else future.set_result(None))
        await future

    def deliver_step(self, step):
        self.milestone += 1
        self.step_seen[step["label"]] = self.milestone
        event = deepcopy(step["event"])
        if isinstance(event, dict):
            self.log(kind="event", event_type=event.get("event_type"), payload=event.get("payload", {}),
                     scheduled_ms=step["at_ms"])
        else:
            self.log(kind="event", event_type="malformed", raw=event, scheduled_ms=step["at_ms"])
        self.in_q.put_nowait(event)

    def deliver_result(self, operation, delivery, delivery_index):
        if operation["cancelled"] and not operation["reply"].get("ignore_cancel"):
            return
        result = deepcopy(delivery["result"])
        api = delivery.get("api_name_override", operation["api_name"])
        cid = delivery.get("call_id_override", operation["call_id"])
        status = result.get("status", "success") if isinstance(result, dict) else "error"
        self.log(kind="tool_completed", call_id=cid, api_name=api, args=deepcopy(operation["args"]),
                 status=status, result=result)
        self.milestone += 1
        key = (operation["api_name"], operation["call_index"], delivery_index)
        self.result_seen[key] = self.milestone
        payload = {"call_id": cid, "api_name": api, "status": status, "result": result}
        self.log(kind="event", event_type="tool_result", payload=payload)
        self.in_q.put_nowait({"timestamp_ms": self.now, "event_type": "tool_result", "payload": payload})

    async def monitor(self):
        while True:
            action = await self.out_q.get()
            problems = self.validate_action(action)
            if problems:
                self.log(kind="protocol_error", problems=problems, raw=repr(action)[:500])
            if not isinstance(action, dict):
                continue
            name = action.get("action")
            payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
            if name == "tool_call":
                cid, api = payload.get("call_id"), payload.get("api_name")
                call_args = payload.get("args")
                self.log(kind="action", action=name, call_id=cid, api_name=api, args=deepcopy(call_args))
                if not isinstance(cid, str) or not cid or cid in self.operations:
                    self.log(kind="adapter_error", error="Missing or duplicate tool call_id")
                    continue
                index = self.counts[api]
                self.counts[api] += 1
                self.call_ids[(api, index)] = cid
                reply = next((r for r in self.case["replies"] if r["api_name"] == api and
                              (matches_args(call_args, r["match_args"]) if "match_args" in r
                               else r["call_index"] == index)), None)
                if reply is None:
                    reply = {"delay_ms": 1, "deliveries": [{"offset_ms": 0, "result": {
                        "status": "error", "error": "unconfigured_call", "detail": "No synthetic reply configured."}}]}
                op = {"call_id": cid, "api_name": api, "args": deepcopy(call_args),
                      "call_index": index, "reply": reply, "cancelled": False}
                self.operations[cid] = op
                for delivery_index, delivery in enumerate(reply.get("deliveries", [])):
                    when = self.now + reply.get("delay_ms", 0) + delivery.get("offset_ms", 0)
                    self.schedule(when, lambda op=op, d=delivery, i=delivery_index: self.deliver_result(op, d, i))
            elif name == "cancel_tool":
                self.log(kind="action", action=name, payload=deepcopy(payload))
                cid = payload.get("call_id")
                if cid in self.operations:
                    self.operations[cid]["cancelled"] = True
                    self.log(kind="tool_cancelled", call_id=cid)
                else:
                    self.log(kind="cancel_noop", call_id=cid)
            else:
                entry = {"kind": "action", "action": name, "payload": deepcopy(payload)}
                if "state_snapshot" in action:
                    entry["state_snapshot"] = deepcopy(action["state_snapshot"])
                self.log(**entry)

    async def settle(self):
        # Fixed scheduler turns, no production internals inspected or altered.
        # This covers nested create_task/wait/queue wakeups before advancing time.
        for _ in range(self.settle_turns):
            await asyncio.sleep(0)

    async def run(self):
        baseline = set(asyncio.all_tasks())
        agent = (self.cls(self.in_q, self.out_q, planner=self.planner) if self.injected
                 else self.cls(self.in_q, self.out_q))
        await agent.setup()
        self.planner = agent.planner
        self.started = time.monotonic()

        async def run_agent():
            try:
                await agent.run()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.log(kind="agent_crash", error=f"{type(exc).__name__}: {exc}")
            finally:
                self.log(kind="agent_exit", at_shutdown=self.stopping)

        agent_task = asyncio.create_task(run_agent())
        monitor_task = asyncio.create_task(self.monitor())
        self.log(kind="event", event_type="tool_manifest", payload={"tools": sorted(self.case["tools"])})
        self.in_q.put_nowait({"timestamp_ms": 0, "event_type": "tool_manifest",
                             "payload": {"schema_version": "1.0", "tools": deepcopy(self.case["tools"])}})
        for step in self.case["steps"]:
            self.schedule(step["at_ms"], lambda s=step: self.deliver_step(s))
        stop_at = max(s["at_ms"] for s in self.case["steps"]) + self.case.get("tail_ms", 6000)
        self.schedule(stop_at, lambda: None)
        try:
            await self.settle()
            while self.heap:
                if self.clock_mode == "real":
                    # A real planner can add an earlier reply while this loop
                    # waits for a later user event or the end of the tail.
                    self.schedule_changed.clear()
                    delay = max(0, self.heap[0][0] - self.now) / 1000
                    if delay:
                        try:
                            await asyncio.wait_for(self.schedule_changed.wait(), timeout=delay)
                        except TimeoutError:
                            pass
                        else:
                            continue
                else:
                    self.now = self.heap[0][0]
                if self.now > stop_at:
                    self.now = stop_at
                    break
                while self.heap and self.heap[0][0] <= self.now:
                    _, _, callback = heapq.heappop(self.heap)
                    callback()
                await self.settle()
                if self.now >= stop_at:
                    break
        finally:
            self.stopping = True
            agent_task.cancel()
            try:
                await asyncio.wait_for(agent_task, timeout=2)
            except asyncio.CancelledError:
                pass
            except TimeoutError:
                self.log(kind="adapter_error", error="Agent shutdown exceeded 2 real seconds")
            await self.settle()
            monitor_task.cancel()
            monitor_results = await asyncio.gather(monitor_task, return_exceptions=True)
            for result in monitor_results:
                if isinstance(result, Exception):
                    self.log(kind="adapter_error", error=f"Monitor failed: {type(result).__name__}: {result}")
            leaked = [task for task in asyncio.all_tasks() - baseline if not task.done()]
            closed = self.planner.closed if self.injected else getattr(self.planner, "client", "unobserved") is None
            self.log(kind="shutdown", pending_tasks=len(leaked), planner_closed=closed,
                     pending_task_names=[task.get_coro().__qualname__ for task in leaked])
            for task in leaked:
                task.cancel()
            if leaked:
                await asyncio.gather(*leaked, return_exceptions=True)
        return self.trace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--partition", choices=("development", "holdout"))
    parser.add_argument("--family", action="append")
    parser.add_argument("--case-mode", choices=("controller_injected", "e2e_text", "e2e_audio", "e2e_visual"))
    parser.add_argument("--first-per-family", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--settle-turns", type=int, default=40)
    parser.add_argument("--clock", choices=("virtual", "real", "auto"), default="virtual",
                        help="auto uses real time for configured lost outcomes, virtual time otherwise")
    parser.add_argument("--execution", choices=("controller", "real-provider"), default="controller")
    parser.add_argument("--provider-case-limit", type=int, default=20,
                        help="Explicit authorized batch bound, 1..60; default 20")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--block-family", action="append", default=[],
                        help="Retain a blocked row for an independently identified fixture validity issue")
    args = parser.parse_args()
    if args.settle_turns < 20:
        parser.error("at least 20 scheduler settle turns required")
    if not 1 <= args.provider_case_limit <= 60:
        parser.error("--provider-case-limit must be between 1 and 60")
    if args.execution == "real-provider" and (args.clock != "real" or args.case_mode != "e2e_text"):
        parser.error("bounded real-provider execution requires --clock real --case-mode e2e_text")
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file.resolve(), override=False)
    for field in ("candidate", "kit", "cases", "oracle"):
        setattr(args, field, getattr(args, field).resolve())
    args.out = args.out.resolve()
    if args.out.exists():
        parser.error("--out exists; preserve all attempts in a new directory")
    args.out.mkdir(parents=True)
    case_digest = hashlib.sha256(args.cases.read_bytes()).hexdigest()
    freeze_path = args.cases.parent / "FREEZE.json"
    if freeze_path.exists():
        freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
        expected = freeze.get("files", {}).get(args.cases.name, {}).get("sha256")
        if expected != case_digest:
            raise RuntimeError("Case bytes disagree with the challenge author's frozen manifest")
    candidate = args.candidate.resolve()
    before = fingerprint(candidate / "participant")
    sys.path.insert(0, str(candidate))
    sys.path.insert(1, str(args.kit.resolve()))
    from participant.agent import ParticipantAgent
    from harness.protocol import validate_action
    participant_path = Path(importlib.import_module("participant.agent").__file__).resolve()
    if not participant_path.is_relative_to(candidate):
        raise RuntimeError(f"Wrong candidate import: {participant_path}")
    spec = importlib.util.spec_from_file_location("independent_challenge_oracle", args.oracle.resolve())
    oracle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oracle)
    cases = [json.loads(line) for line in args.cases.read_text(encoding="utf-8").splitlines() if line.strip()]
    counts, selected_cases = Counter(), []
    for case in cases:
        if args.partition and case["partition"] != args.partition:
            continue
        if args.family and case["family"] not in args.family:
            continue
        if args.case_mode and case["mode"] != args.case_mode:
            continue
        if args.first_per_family and counts[case["family"]] >= args.first_per_family:
            continue
        counts[case["family"]] += 1
        selected_cases.append(case)
        if args.limit and len(selected_cases) >= args.limit:
            break
    if args.execution == "real-provider" and len(selected_cases) > args.provider_case_limit:
        raise ValueError(f"This bounded semantic execution permits at most {args.provider_case_limit} selected cases")
    clock_descriptions = {"virtual": "synthetic discrete event; production clocks unmodified",
                          "real": "real monotonic time, scale one; authored events/replies; planner mode recorded separately",
                          "auto": "real scale one for configured lost outcomes; virtual otherwise; per-row clock recorded"}
    manifest = {"argv": sys.argv, "clock": clock_descriptions[args.clock],
                "settle_turns": args.settle_turns,
                "provider_case_limit": args.provider_case_limit,
                "planner": ("injected scripted decisions; zero model calls" if args.execution == "controller"
                            else "actual ParticipantAgent and Planner; no injected decisions; authored tool environment"),
                "python": sys.executable,
                "environment": {key: os.environ.get(key) for key in ("PARTICIPANT_MODEL", "PARTICIPANT_THINKING_LEVEL",
                                "PARTICIPANT_TIMEOUT_SECONDS", "PARTICIPANT_IMAGE_EMBEDDING", "PARTICIPANT_PREWARM",
                                "THREAD_MODEL", "THREAD_PROVIDER")},
                "imports": {"participant.agent": str(participant_path), "oracle": str(args.oracle.resolve())},
                "source_sha256": before, "cases_sha256": case_digest,
                "freeze_sha256": hashlib.sha256(freeze_path.read_bytes()).hexdigest() if freeze_path.exists() else None,
                "acceptance_source_sha256": fingerprint(Path(__file__).resolve().parent),
                "oracle_sha256": hashlib.sha256(args.oracle.read_bytes()).hexdigest(),
                "selected": len(selected_cases), "authored_in_file": len(cases)}
    write_json(args.out / "manifest.json", manifest)
    summaries = []
    trace_context = None
    if args.execution == "real-provider":
        trace_context = importlib.import_module("participant.planner").planner_trace
        os.chdir(candidate)
    started = time.monotonic()
    consecutive_provider_failures, provider_stop_reason = 0, None
    with (args.out / "results.jsonl").open("w", encoding="utf-8") as logfile:
        for index, case in enumerate(selected_cases):
            row = {"id": case["id"], "family": case["family"], "mode": case["mode"], "partition": case["partition"]}
            expected_mode = "controller_injected" if args.execution == "controller" else "e2e_text"
            if provider_stop_reason is not None:
                row.update(status="blocked", reason=provider_stop_reason)
            elif case["family"] in args.block_family:
                row.update(status="blocked", reason="Pre-execution fixture-validity limitation; original oracle retained")
            elif case["mode"] != expected_mode or case.get("requirements"):
                row.update(status="blocked", reason="Requires non-injected mode or external asset preconditions",
                           requirements=case.get("requirements", []))
            else:
                case_clock = args.clock
                if case_clock == "auto":
                    case_clock = "real" if any(not r.get("deliveries") for r in case["replies"]) else "virtual"
                row["clock"] = case_clock
                driver = Driver(case, ParticipantAgent, validate_action, args.settle_turns, case_clock,
                                args.execution == "controller")
                model_evidence = []
                try:
                    with trace_context(model_evidence.append) if trace_context else nullcontext():
                        trace = asyncio.run(driver.run())
                except Exception as exc:
                    trace = driver.trace + [{"kind": "adapter_error", "t_ms": driver.now,
                                             "error": f"{type(exc).__name__}: {exc}"}]
                verdict = oracle.evaluate_case(case, trace)
                row.update(status="passed" if verdict["passed"] else "failed", trace=trace, verdict=verdict)
                if trace_context:
                    row["model_evidence"] = model_evidence
                    consecutive_provider_failures = (consecutive_provider_failures + 1
                                                     if provider_unavailable(model_evidence) else 0)
                    if consecutive_provider_failures >= 3:
                        provider_stop_reason = "Unexecuted after three consecutive cases with provider errors and no HTTP 200 decision response"
            logfile.write(json.dumps(row, ensure_ascii=False) + "\n")
            logfile.flush()
            summaries.append({k: v for k, v in row.items() if k != "trace"})
            if (index + 1) % 100 == 0:
                print(json.dumps({"completed": index + 1, "selected": len(selected_cases),
                                  "counts": dict(Counter(r["status"] for r in summaries))}), flush=True)
    manifest.update(elapsed_s=round(time.monotonic() - started, 3),
                    provider_stop_reason=provider_stop_reason,
                    sources_unchanged=before == fingerprint(candidate / "participant"),
                    cases_unchanged=case_digest == hashlib.sha256(args.cases.read_bytes()).hexdigest(),
                    oracle_unchanged=manifest["oracle_sha256"] == hashlib.sha256(args.oracle.read_bytes()).hexdigest(),
                    counts=dict(Counter(row["status"] for row in summaries)))
    write_json(args.out / "manifest.json", manifest)
    write_json(args.out / "summary.json", summaries)
    write_json(args.out / "evidence-sha256.json", {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted(args.out.iterdir()) if p.is_file() and p.name != "evidence-sha256.json"})
    print(json.dumps(manifest, indent=2))
    raise SystemExit(0 if all(row["status"] == "passed" for row in summaries)
                     and all(manifest[k] for k in ("sources_unchanged", "cases_unchanged", "oracle_unchanged")) else 1)


if __name__ == "__main__":
    main()
