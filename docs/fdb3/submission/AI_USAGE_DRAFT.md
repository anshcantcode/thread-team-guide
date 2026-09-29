# AI assistance disclosure draft

**Unsigned. Human factual review and signature are required before submission.**

The project used OpenAI Codex and Anthropic Claude Code for code development, repository review, regression authoring, local experiment execution, analysis and documentation. Exact model/version records are incomplete and must be confirmed by the team rather than guessed. Assistance is disclosed here because the organizer form explicitly asks for the tools/platforms used.

| Feature / work | Prompt summary (not a verbatim transcript) | Output | Human/project modification and verification |
|---|---|---|---|
| Interruptible voice controller | Implement and review revision-aware correction, authorization and cancellation | Python implementation and proposed fixes | Independent counterexamples, schema checks and regression review exposed defects; fixes and failed attempts retained |
| Benchmark and reproduction | Run the released kit with complete evidence and no paid calls | Local runners, model pins, evidence and result analysis | Source/configuration identities checked; local judging clearly separated from organizer scoring |
| Browser/Android extension | Apply current controller to real client-owned checklist actions | Host adapter, client storage boundary, native/browser tests | Device receipts, idempotency, stale-input checks, playback accounting and build/source verification |
| Submission material | Explain the architecture and reconcile claims with evidence | Draft README, walkthrough, documentation and media/deck drafts | Unsupported official-score predictions removed; human team fields, asset review and signature still outstanding |

Local runtime models are Qwen3.5-4B Q4_K_M for planning and local diagnostic judging, and faster-whisper small.en for recognition. Speech on the development Windows host uses SAPI; Linux uses an explicitly configured local synthesizer. An upstream model alias does not establish the actual model identity; manifests are authoritative.

Historical fixtures were independently AI-authored and synthetic speech was explicitly labeled. Held-out-015 was later inspected during repairs and is no longer unseen. Authorship separation of held-out-016 is a historical experimental claim with an aggregate-exposure caveat, not proof of absolute blindness or a safety guarantee. Formatting cleanup of published provenance must not silently retain an original-file hash.

Current benchmark results, later code changes and client tests are separated in [verification](../../checkpoint/VERIFICATION.md). No paid inference/speech/LiveKit calls were authorized for this checkpoint. No official score, universal safety claim or comparable competitor victory is asserted.

The organizer's original form remains `CollegeName_TeamName_AI_Disclosure_DRAFT.docx`. It contains required tool names; they are factual disclosure, not product watermarks. The team must review feature-origin classifications, prompt/output examples, exact model records, ethics declarations, representative details, rendered pages and signature. No signature or submission has been made on the owner's behalf.
