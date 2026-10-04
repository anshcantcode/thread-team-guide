# Historical 28 September requirements and proof mapping

**Superseded status snapshot.** Use [the current submission requirements](../submission/REQUIREMENTS.md). The owner now reports **4 October 2026**; exact cutoff/form remain unconfirmed. Source, score, configuration and incomplete gates below retain their 28 September meaning, not the final catchup source.

Authority: [updated Theme 05 guide](https://docs.google.com/document/d/12RPdEbggSayVHNoFk1zPNqKOdVRQ_vio/edit),
read through Drive again on 28 September (India time), modified 24 September.
The [general brochure](https://drive.google.com/file/d/1SVFfMhULQUf6BX9NS1lAyjqsnCGOOPtm/view)
adds final-tag and naming requirements. The newer theme guide controls FDB-v3
scoring and the eight-slide limit. Legacy queue-kit scores are historical.

| Requirement | Implementation / evidence | Remaining gap |
|---|---|---|
| FDB-v3 LiveKit voice agent | fdb3_agent.py and shared AgentSession; actual local WebRTC input and received speech | AgentServer dispatch/official deployment not validated |
| Exact 12 tool contracts | AST reads pinned template; unchanged mock_apis and latency_injector | Broader chain contract tests |
| Real audio-to-tool-to-speech | Frozen 088cf6f room diagnostic: 100 valid evaluations, 50 strict/50 window passes, 0 infrastructure | Current-source repair measurements |
| 100 recordings | All 100 audio hashes and 1,400 archived files verified; 42/100 judge-free on saved traces | Fresh complete repeat, not a rescore |
| State, corrections, authorization, outcomes | Existing participant controller plus bridge race checks | Full independent interruption family coverage |
| LLM judge | Unchanged official evaluator against explicitly declared local Qwen backend | Organizer judge snapshot unknown; hosted lane unauthorized |
| Three preregistered 100/100 runs | Frozen-run orchestrator and fail-closed series verifier | Zero qualifying runs |
| One-command reproduction and Docker/requirements | Isolated Ubuntu preparation and 88 SDK tests on named snapshot; current nine Linux guards and six judge controls; FDB CPU image built with real speech smoke and pinned Python lock | Complete clean GPU/100-recording proof; container AgentServer dispatch |
| Current competitor cohort | All available seed refs and expanded discovery; source inspection | No comparable live results; newly provisioned WSL has not run competitor code |
| Real extension, 3–5 minute video, ≤8 slides | Fresh015 correction: one spinach write, visible native receipt and restart persistence; edited 4:10 real-evidence video; editable 8-slide official-template draft | Human full listening, tested public video link, team details and final reviewed assets; no physical-device proof |
| Tagged final release with all referenced assets | Exact tag PRISM_GENAI_HACKATHON_Y2026 documented | Final tested commit, approved tag, assets/references and Google Form submission |
| AI disclosure | Original-form unsigned draft and detailed AI-use notes | Human review and representative signature |

Round 1 is 60% organizer benchmark rerun, 20% working extension, 20% documentation,
architecture and video. Only the organizers' rerun counts. Three fresh 100/100
runs are an internal objective; the guide does not require perfection to submit.

The owner reports an email extending the deadline to **30 September**. This is
recorded as owner-reported; the email was not independently read because Gmail
is unconnected. Cutoff time/timezone and the final form URL remain placeholders,
as did the then-unknown team details. This is the historical deadline report; the 3 October update above supersedes it.

Unknown organizer details: selected benchmark commit, judge snapshot,
normalization formula and credit funding. Upstream remains provisionally pinned
to 3e799c45a045256f47d5f1c9cda90157e2d2ec9e. No official score or ranking is inferred.
