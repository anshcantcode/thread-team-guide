# pub_04 no-tool outlier: evidence gap

The official `pub_04_text_no_tool` scenario contains one text request at 100 ms. It requires no tool calls, a helpful final response, and first substantive speech within 600 ms for full latency credit (zero at 1,500 ms). The checked-in three-run report records totals of 100, 100, and 76.9, but no per-run action timestamps or latency breakdown.

At the requested source commit, the controller emits substantive `filler_speech` while handling the completed text turn, before it schedules planning. A no-tool decision with nonempty `response` is finalized through `_final`. The exact scenario prompt also matches the local capability planner rule with the official mock manifest; none of the local flight rules match.

Offline checks passed: the focused controller and planner tests; an exact-scenario harness replay with a scripted planner delayed 1.8 seconds, which emitted its first substantive action 0.4 ms after the request and made zero tool calls; and a direct check that the exact prompt selects the local capability response. These checks do not reproduce the 76.9 result.

No controller change is justified from the available evidence. The third attempt's event timestamp, first substantive action type and timestamp, and planning duration are needed to distinguish a missed latency window from run-to-run scheduling variation.
