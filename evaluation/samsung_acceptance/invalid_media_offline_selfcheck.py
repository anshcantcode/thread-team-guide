"""Small runner controls; zero authored-case, participant, or provider executions.

python -B -m evaluation.samsung_acceptance.invalid_media_offline_selfcheck
  --cases original/development.jsonl --cases original/holdout.jsonl --out NEW_REPORT.json
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from copy import deepcopy
import json
import os
from pathlib import Path
import socket
import tempfile

import httpx

from .invalid_media_offline import (assess, digest, frozen_cases, offline_environment,
                                    rejecting_transport, write_new)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("--out exists; preserve the first control result")
    checks, details, network_attempts, requests = {}, {}, [], []
    previous = dict(os.environ)

    async def loop_and_transport():
        await asyncio.sleep(0)
        checks["event_loop_and_worker_socketpair_compatible"] = await asyncio.to_thread(lambda: True)
        async with httpx.AsyncClient(transport=rejecting_transport(requests)) as client:
            try:
                await client.get("https://offline.invalid/control")
            except httpx.ConnectError:
                checks["every_mock_http_request_raises_and_is_recorded"] = len(requests) == 1
            else:
                checks["every_mock_http_request_raises_and_is_recorded"] = False

    with offline_environment(network_attempts):
        asyncio.run(loop_and_transport())
        checks["event_loop_and_mock_transport_make_no_socket_attempt"] = not network_attempts
        for label, address in (("external_connect_denied", ("203.0.113.10", 443)),
                               ("arbitrary_loopback_denied", ("127.0.0.1", 9))):
            before = len(network_attempts)
            with socket.socket() as probe:
                try:
                    probe.connect(address)
                except RuntimeError:
                    checks[label] = len(network_attempts) == before + 1
                else:
                    checks[label] = False
        before = len(network_attempts)
        try:
            socket.getaddrinfo("offline.invalid", 443)
        except RuntimeError:
            checks["dns_denied_before_resolution"] = len(network_attempts) == before + 1
        else:
            checks["dns_denied_before_resolution"] = False
    checks["environment_restored"] = previous == dict(os.environ)
    with tempfile.TemporaryDirectory(prefix="invalid-media-runner-control-") as directory:
        root = Path(directory)
        record = {"assets": [{"original_ref": "absent.mp3", "state": "expected_absent",
                              "source": str(root / "source.mp3"), "staged": str(root / "staged.mp3"),
                              "sha256": None, "bytes": 0}]}
        refusal = [{"kind": "action", "action": "clarification_request", "t_ms": 100,
                    "payload": {"text": "I could not handle that media."}},
                   {"kind": "agent_exit", "t_ms": 200, "at_shutdown": True},
                   {"kind": "shutdown", "t_ms": 200, "pending_tasks": 0, "planner_closed": True}]
        # Deliberately grant the synthetic oracle verdict: the independent read gate
        # must still reject a generic refusal. This is not an original fixture run.
        generic = assess(record, refusal, {"passed": True}, [], [], 1)
        checks["generic_refusal_without_media_attempt_rejected"] = (generic["status"] == "failed"
            and not generic["checks"]["invalid_media_attempts"]
            and not generic["checks"]["every_original_ref_has_read_error"])
        positive = [{"kind": "media_access", "t_ms": 50, "media_ref": "absent.mp3", "status": "read_error"}, *refusal]
        checks["synthetic_read_error_control_accepted"] = assess(record, positive, {"passed": True}, [], [], 1)["status"] == "passed"
        read_success = deepcopy(positive)
        read_success[0]["status"] = "read"
        checks["successful_read_is_not_invalid_media_error_proof"] = assess(record, read_success, {"passed": True}, [], [], 1)["status"] == "failed"
        checks["denied_http_attempt_cannot_pass_case"] = assess(record, positive, {"passed": True}, requests, [], 1)["status"] == "failed"
        checks["denied_socket_attempt_cannot_pass_case"] = assess(record, positive, {"passed": True}, [], network_attempts, 1)["status"] == "failed"
        details["generic_refusal"] = generic
    ids = {}
    for mode in ("e2e_audio", "e2e_visual"):
        selected, inputs, oracle = frozen_cases([path.resolve() for path in args.cases], mode)
        ids[mode] = [case["id"] for case, *_ in selected]
        partitions = dict(Counter(case["partition"] for case, *_ in selected))
        expected = {"development": 16} if mode == "e2e_audio" else {"development": 8, "holdout": 8}
        checks[mode + "_selects_exact_original_16"] = len(selected) == 16 and partitions == expected
        details[mode] = {"ids": ids[mode], "partitions": partitions, "input_sha256": inputs,
                         "oracle": str(oracle), "oracle_sha256": digest(oracle)}
    checks["mode_denominators_do_not_overlap"] = not set(ids["e2e_audio"]) & set(ids["e2e_visual"])
    report = {"scope": "Synthetic runner boundary controls and read-only fixture selection",
              "authored_original_executions": 0, "participant_executions": 0, "provider_generations": 0,
              "checks": checks, "details": details, "intentional_denied_http_requests": requests,
              "intentional_denied_socket_attempts": network_attempts,
              "source_sha256": {name: digest(Path(__file__).with_name(name)) for name in
                                ("invalid_media_offline.py", "invalid_media_offline_selfcheck.py")}}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_new(args.out, report)
    print(json.dumps({"passed": sum(checks.values()), "controls": len(checks), "out": str(args.out)}))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
