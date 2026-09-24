# Visual read deadline

Scope: frozen package `c2504bc` (the relevant planner, controller, and official kit files are unchanged on this task HEAD). Read-only inspection only; no provider call.

## Evidence

- The official visual scenario sends a frame at 100 ms and the question at 600 ms. The harness leaves a 6,000 ms tail after `scenario_end`; `lookup_manual` is declared read-only with a 1,200–2,500 ms delay (`theme5_kit/participant-kit/participant-kit/scenarios/pub_07_visual_port_lookup.json`, `harness/runner.py`, `docs/TOOLS.md`).
- In the frozen trace, attempt 2 emitted its lookup at 4,359 ms; it completed and answered at 6,453 ms. Attempt 3 emitted at 4,516 ms and completed at 6,610 ms, exactly at the tail boundary after its 610 ms `scenario_end`, leaving no time to speak. Both tool calls took 2,094 ms. Attempt 1 made no lookup and clarified at 5,141 ms, consistent with a planner timeout; that is a planning/reliability miss, not a reason to loosen visual validation. The first filler already satisfies the scenario's spoken-latency checkpoint, so earlier dispatch is aimed at completion before tail, not that score.
- `Planner._generate` starts image embedding concurrently with planning and attaches it only if already ready; it does not await it. `_decide` instead waits for the full non-streaming `generateContent` response, parses the whole JSON, and validates it before returning. `ParticipantAgent.run` applies and dispatches only after the planning task completes. This full-response barrier is the narrowest evidenced source of avoidable delay (`participant/planner.py:1119,1205,1515,1610`; `participant/agent.py:65,284,315`).

## Proposed seam

Stream only the planning response in `_decide`, and add a one-shot early-read mailbox from the planner to `ParticipantAgent.run`. Admit one completed root call early only after the current frame observation and target evidence are complete, the `tool_calls` array is closed with exactly one terminal step, `clarification` is null, the existing visual checks and tool argument validation pass, and the current manifest marks the tool `read_only`. Require no authorization or `after_result`; bind admission to the current revision and frame. Register and dispatch through the existing operation ledger so interruptions still invalidate/cancel the call. Keep writes, chains, multiple calls, unclear/stale frames, and malformed streams on the existing full-plan path. Attach an image embedding only if it is ready at admission; it remains optional and must not hold the lookup.

## Risks and focused test

A truncated or contradictory stream could otherwise trigger a speculative read, and a misdeclared `read_only` tool could have effects. Wait for the complete call object, closed single-call array, explicit null clarification, schema validation, and current-frame evidence; never admit based on a partial JSON fragment or provider text alone. Preserve revision checks and existing cancellation. Earlier dispatch may also beat embedding completion and lose the optional hybrid-search bonus.

Add a provider-free unit test with fake stream chunks: hold the stream open after one valid current-frame terminal read-only call and assert exactly one dispatch before the final response field arrives. Assert no dispatch for an uncertain/mismatched or stale label, missing args, non-null clarification, multiple calls, write/continuation, malformed/truncated stream, or a revision change.
