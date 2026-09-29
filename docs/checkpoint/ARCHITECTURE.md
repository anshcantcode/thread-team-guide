# Architecture

```mermaid
flowchart LR
  U[Speech or typed request] --> I[Input identity and speech onset]
  I --> S[Local recognition / current request]
  S --> P[Local Qwen proposal]
  P --> C[THREAD controller]
  C --> A[Revision and clause authorization]
  A --> T[Tool admission boundary]
  T --> D[Client checklist or official mock tool]
  D --> R[Actual result / durable receipt]
  R --> C
  C --> V[Local speech output]
  V --> K[Playback acknowledgement]
  K --> C
```

The planner proposes; the controller authorizes. Public schemas determine required arguments. An omitted required search filter causes clarification rather than an invented value or `None` injected into a required numeric argument.

## State and correction

`ParticipantAgent` owns request state and revisions. Clauses retain identity so a value in an unrelated or retracted clause cannot authorize a write. Speech onset fences old work immediately, before recognition finishes. The LiveKit adapter tracks recognition segments and rejects stale transcript authority.

## Cancellation and outcomes

`ControllerBridge` separates dispatch intent from admission to execution. Work rejected before submission has no effect. Admitted work is accounted for until success, error or an unknown outcome. Unknown writes are not blindly retried. Late matching receipts update the original operation and retire its continuation; they do not start a new action.

## Browser and Android boundary

`fdb3_client.py` exposes a local-only host. Kitchen implements `read_checklist`, `add_checklist_item`, and `set_checklist_item`. The client owns storage, validates session/input/request identities, and persists an effect with its idempotent receipt. Browser data stays in its browser profile; Android data stays in private app storage. The network route does not expose test-reset, authority-setting or debug commands.

The host serializes conversations because its planner cache has one scenario owner. It rejects remote web origins and binds loopback. Android reaches it through explicit ADB reverse. This is a tethered extension, not an autonomous on-device model or an internet service.

## Speech evidence

Input is PCM16 mono at 16 kHz; output is PCM16 mono at 24 kHz. Only terminal playback events settle an SDK segment. Duplicate flushes and intermediate statuses cannot turn unheard audio into successful playback. Interrupted text is not proof that the user heard the unsaid suffix.

A playback receipt is a software estimate, not proof of human hearing. Benchmark transport is LiveKit WebRTC. Kitchen uses WebSocket PCM with a LiveKit AgentSession, so its latency is a separate measurement.

## Evaluation separation

The runtime reads the public tool contract. Evaluators read recordings, expected answers and grading code separately. This is process/input separation, not an OS-enforced sandbox; the stronger isolation gate remains unqualified. Official tools and evaluator semantics stay unchanged. Authored fixtures and local judgments are distinct from organizer results.
