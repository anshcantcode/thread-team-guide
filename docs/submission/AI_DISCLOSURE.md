# AI assistance disclosure

THREAD was built with AI coding assistants used as engineering aids: implementation patches, code review, regression tests, local experiment execution, failure analysis, documentation, presentation copy and media production. Architecture, product decisions, acceptance criteria, source integration, final claims and submission approval stayed with the team. AI output was treated as a proposal and reviewed, modified and tested before adoption.

**Signed organizer form.** The team's AI usage disclosure form, reviewed and signed by the team representative (Nargis Sultana, dated 4 October 2026), accompanies the entry. It names the AI tools and platforms, gives representative prompts and outputs, and records how the team modified and verified each output.

| Feature / work | Origin | How AI assistance was used | Team modification and verification |
|---|---|---|---|
| Interruptible voice controller | Both | Review for stale-intent races, correction handling, authorization and cancellation; candidate fixes and regressions | Defects reproduced before repair; unsafe or over-broad changes rejected; accepted fixes validated against regression suites; failed attempts retained |
| FDB-v3 benchmark, reproduction and evidence | Both | Runner and reproduction scripts, pins, evidence manifests, per-case failure analysis, the 3–4 October final-source run and the typed-value repair | Source/config identities and hashes checked; local judging kept separate from organizer scoring; the team chose the 4B planner and decided not to send the undeclared `pets_allowed` argument |
| Kitchen browser + Android extension | Both | Host/client adapters, persistence boundary, test scaffolds | Real checklist writes and read-back exercised; receipts, duplicate protection, playback accounting and persistence checked |
| Companion orb, Watches, Android app actions and floating bubble | Both | Web and Android UI, Watch and app-action endpoints, tests | Features chosen by the team; CPU suites pass; installed on a team member's Galaxy S24, where a floating-bubble crash was found and fixed |
| UI/UX, documentation and media | Both | UI critique, documentation and deck drafts, motion and generated assets, synthetic/re-voiced speech in the launch film | Final narrative, visuals and claims reviewed by the team; synthetic and re-voiced media labelled |

Local runtime models are Qwen3.5-4B Q4_K_M for planning and local diagnostic judging, and faster-whisper small.en for recognition. Speech on the development Windows host uses SAPI; Linux uses an explicitly configured local synthesizer. An upstream model alias does not establish the actual model identity; manifests are authoritative.

Historical fixtures were independently AI-authored and synthetic speech was explicitly labeled. Held-out-015 was later inspected during repairs and is no longer unseen. Authorship separation of held-out-016 is a historical experimental claim with an aggregate-exposure caveat, not proof of absolute blindness or a safety guarantee.

Benchmark results, code changes and client tests are separated in [submission results](RESULTS.md). No paid inference, speech or LiveKit calls were used. No official score, universal safety claim or competitor comparison is asserted.

## Registered team

ReflexAi, SRM Institute of Science and Technology Kattankulathur. Members: Nidhee Kunal Chandan, Ansh Golcha, Raiyan Kamal and Nargis Sultana.

The launch film includes AI-assisted motion production, generated assets and synthetic/re-voiced speech. Replies in the animated film were re-voiced for presentation, while the separately labelled recorded demo retains original received audio. See the [media provenance](media/README.md).
