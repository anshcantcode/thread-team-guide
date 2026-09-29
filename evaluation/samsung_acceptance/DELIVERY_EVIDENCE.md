# Optional delivery-stage evidence

`record.py --delivery-evidence` adds read-only HTTP timing evidence to the existing
profile fanout. It requires real-provider mode, explicit generation/embedding caps,
CPython 3.11, HTTPX 0.28.1 and HTTPCore 1.0.9. Unsupported versions are rejected before
creating evidence output or loading an environment file. The default recorder
does not activate or emit delivery evidence. This flag does not authorize a run.

For an already reviewed invocation, append **`--delivery-evidence`** to the recorder
arguments (after the supervisor's `--` separator when using `run.py`). Keep the
approved candidate, original kit, scenario selection, caps and clocks. Use a fresh
output directory and separately freeze the changed evaluation code. Existing
POST-only admission and first-429 stop remain active; this does not enable prewarm.
The first delivery-capture failure stops the batch immediately with exit 77 and
`delivery_observer_error`. The current partial attempt and remaining UNRUN entries
are retained through the existing cleanup path. This is a diagnostic failure,
not quota exhaustion or a provider error.

Each attempt gains `delivery_evidence`; the manifest retains prescenario and
unassociated segments. A segment contains events, open dispatch/stage IDs, an
explicit observed/absent trace state, and a count of ignored phase boundaries.
Dispatch IDs distinguish resends even when request hashes match. Task IDs are
anonymous ordinals. `dispatch_start` reuses the guarded transport observer's
buffered body hash/size; `dispatch_end` records headers returned or no response.
It is not the end of response-body consumption.

Allowlisted HTTPCore Trace enter/exit events record monotonic nanoseconds, phase,
dispatch/task/stage IDs, and fixed outcome/failure labels. No trace callback is
installed, no request extension or runtime object is modified, and no stream is
read. Trace kwargs/info, URLs, headers, body contents, task names and exception
messages are never retained by this observer. Unknown exception classes become
`other`, not their potentially sensitive names.

Live dispatch frames associate stages with the current asyncio task. The exact
returned HTTPX Response object supplies later `aread`/`aclose` associations,
including consumption in another task. Child tasks, ambiguous reused responses,
and streaming consumers outside those response scopes remain unmatched; there
is no last-request guess. Body/response-close phases require an exact Response
scope even while another dispatch is active in that task. Coroutine suspension
and resumption create no extra request or stage boundary. Open IDs at a segment boundary remain explicit rather
than acquiring a fabricated completion.

These are client code boundaries and include profiling/logging/callback overhead,
not independent wire captures or server-only latency. Missing stages do not prove
that no bytes were sent. TLS is covered by a constructed Trace control; live
loopback controls exercise HTTP/1.1 connect, headers, body and close. HTTP/2 phase
names are allowlisted but no HTTP/2 transport qualification is claimed.

Run the focused offline controls from the repository root, with a new output path:

```text
python -B -m evaluation.samsung_acceptance.delivery_selfcheck --out <new-private-output>
```

The controls use only MockTransport and loopback HTTP. They compare actual request
bodies and native decision evidence with the option disabled/enabled, and check
concurrency, cancellation, resend/response identity, privacy, runtime pins and
the existing stop before dispatch. An injected observer-bookkeeping failure also
checks immediate stop, partial/UNRUN evidence and process/client cleanup. They do
not exercise an official scenario.

The event vocabulary follows the pinned library's implementation and the
[HTTPX trace documentation](https://www.python-httpx.org/advanced/extensions/#trace)
and [HTTPCore trace documentation](https://www.encode.io/httpcore/extensions/#trace).
