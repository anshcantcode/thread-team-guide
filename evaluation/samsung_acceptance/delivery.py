"""Optional read-only delivery boundaries from the existing profile fanout.

No trace extension, patches, stream reads or requests. Times include observer
overhead, not server processing alone. Unknown task/response links stay unknown.
"""
from __future__ import annotations

import asyncio
import dis
import sys
import time
import weakref


PHASES = frozenset({"connection.connect_tcp", "connection.connect_unix_socket",
    "connection.start_tls", "connection.close", "proxy.start_tls",
    "http2.send_connection_init", *(f"{protocol}.{phase}" for protocol in ("http11", "http2")
        for phase in ("send_request_headers", "send_request_body", "receive_response_headers",
                      "receive_response_body", "response_closed"))})


def validate_runtime():
    import httpx
    import httpcore
    if (sys.implementation.name != "cpython" or sys.version_info[:2] != (3, 11)
            or httpx.__version__ != "0.28.1" or httpcore.__version__ != "1.0.9"):
        raise RuntimeError("Delivery evidence requires CPython 3.11, httpx 0.28.1 and httpcore 1.0.9")
    return {"python": "CPython 3.11", "httpx": "0.28.1", "httpcore": "1.0.9"}


class DeliveryObserver:
    """Call capture after TransportObserver.capture so quota admission stays first.

    Dispatch frames identify tasks until headers return. Exact returned Response
    objects bind later aread/aclose scopes, including consumption in another task.
    Other streaming consumers/child tasks are not guessed from a task's last send.
    """
    def __init__(self, transport):
        validate_runtime()
        import httpx
        import httpcore
        from httpcore._trace import Trace
        self.transport = transport
        self.send = httpx.AsyncClient._send_single_request.__code__
        self.response_scopes = {httpx.Response.aread.__code__, httpx.Response.aclose.__code__}
        self.enter, self.exit = Trace.__aenter__.__code__, Trace.__aexit__.__code__
        self.codes = {self.send, self.enter, self.exit, *self.response_scopes}
        self.response_type = httpx.Response
        self.failures = {getattr(httpcore, name): name for name in (
            "ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout", "ConnectError",
            "ReadError", "WriteError", "RemoteProtocolError", "LocalProtocolError", "ProxyError",
            "UnsupportedProtocol")}
        self.failures.update({asyncio.CancelledError: "CancelledError", TimeoutError: "TimeoutError",
                              OSError: "OSError"})
        self.rows, self.errors = [], []
        self.tasks, self.responses = weakref.WeakKeyDictionary(), weakref.WeakKeyDictionary()
        self.contexts, self.stages = {}, {}
        self.dispatch_count = self.stage_count = self.task_count = self.ignored = 0

    def take(self):
        """Drain a segment without losing associations spanning its boundary."""
        value = {"events": self.rows[:],
                 "httpcore_stages": "observed" if any(r["event"] in {"stage_start", "stage_end"} for r in self.rows) else "absent",
                 "open_dispatches": sorted({c[1]["dispatch_id"] for f, c in self.contexts.items()
                                            if f.f_code is self.send}),
                 "open_stages": sorted(s["stage_id"] for s in self.stages.values()),
                 "ignored_phase_boundaries": self.ignored}
        self.rows.clear()
        self.ignored = 0
        return value

    def capture(self, frame, event, result):
        code = frame.f_code
        if code not in self.codes or event not in {"call", "return"}:
            return
        if event == "return" and frame.f_lasti >= 0 and dis.opname[code.co_code[frame.f_lasti]] in {"YIELD_VALUE", "YIELD_FROM"}:
            return
        try:
            now = time.monotonic_ns()
            task = asyncio.current_task()
            if task is not None and task not in self.tasks:
                self.task_count += 1
                self.tasks[task] = self.task_count
            task_id = self.tasks.get(task) if task is not None else None
            if code is self.send or code in self.response_scopes:
                if event == "call" and frame not in self.contexts:
                    if code is self.send:
                        self.dispatch_count += 1
                        metadata = self.transport.seen.get(frame.f_locals["request"], {})
                        dispatch = {"dispatch_id": self.dispatch_count, "trace_starts": 0}
                        self.rows.append({"event": "dispatch_start", "dispatch_id": self.dispatch_count,
                            "task_id": task_id, "at_monotonic_ns": now,
                            **{k: metadata.get(k) for k in ("body_bytes", "body_sha256")}})
                    else:
                        dispatch = self.responses.get(frame.f_locals["self"])
                    self.contexts[frame] = (task, dispatch)
                elif event == "return":
                    _, dispatch = self.contexts.pop(frame, (None, None))
                    if code is self.send and dispatch is not None:
                        returned = isinstance(result, self.response_type)
                        if returned:
                            # A reused Response cannot reliably identify two sends.
                            old = self.responses.get(result, dispatch)
                            self.responses[result] = dispatch if old is dispatch else None
                        self.rows.append({"event": "dispatch_end", "dispatch_id": dispatch["dispatch_id"],
                            "task_id": task_id, "at_monotonic_ns": now,
                            "response": "headers_returned" if returned else "no_response_observed",
                            "httpcore_stage_starts": dispatch["trace_starts"]})
                return
            # Only final coroutine returns are boundaries; resumes/yields add none.
            if event != "return":
                return
            trace = frame.f_locals["self"]
            phase = (trace.prefix, trace.name)
            if (not all(type(v) is str for v in phase) or ".".join(phase) not in PHASES):
                self.ignored += 1
                return
            phase = ".".join(phase)
            if code is self.enter:
                if result is not trace:
                    return
                scope, dispatch = next(((f, d) for f, (t, d) in reversed(tuple(self.contexts.items()))
                                        if task is not None and t is task), (None, None))
                # An older untracked stream can be consumed inside a newer send.
                # Body/close attribution needs its own exact Response scope.
                if trace.name in {"receive_response_body", "response_closed"} and (
                        scope is None or scope.f_code not in self.response_scopes):
                    dispatch = None
                self.stage_count += 1
                row = {"stage_id": self.stage_count, "phase": phase,
                       "dispatch_id": dispatch["dispatch_id"] if dispatch is not None else None}
                if dispatch is not None:
                    dispatch["trace_starts"] += 1
                self.stages[trace] = row
                self.rows.append({**row, "event": "stage_start", "task_id": task_id,
                                  "at_monotonic_ns": now,
                                  "association": "matched" if dispatch is not None else "unmatched"})
            else:
                row = self.stages.pop(trace, {"stage_id": None, "phase": phase, "dispatch_id": None})
                failure = frame.f_locals.get("exc_type")
                self.rows.append({**row, "event": "stage_end", "task_id": task_id,
                    "at_monotonic_ns": now, "association": "matched" if row["dispatch_id"] is not None else "unmatched",
                    "outcome": "complete" if failure is None else "failed",
                    "failure_type": None if failure is None else self.failures.get(failure, "other")})
        except Exception:
            if not self.errors:
                self.errors.append("capture_error")
