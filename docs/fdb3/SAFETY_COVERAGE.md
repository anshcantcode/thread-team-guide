# Required safety coverage: current evidence and gaps

The latest full Python run passed 1,381 tests in164.453 seconds with source hashes
unchanged during execution (engineering-20260925T154542). The separate pinned-SDK
suite passed76 controls in43.376 seconds after updating two interface fixtures and
adding durable judge-probe controls;
its earlier70-test run retained two fixture errors. Later accounting/probe tests
are recorded separately.
These counts do not establish all required FDB integration families; subsequent
authorization repairs require fresh validation. The table distinguishes
controller/protocol evidence from a real audio test of the migrated path.

| Required family | Current evidence | Remaining FDB evidence |
|---|---|---|
| Mid-sentence correction | Existing controller state freshness; explicit revision replacement | Independently authored audio through current adapter |
| Repeated correction | Controller freshness and revision actor race | Latest-source audio with several corrections |
| Partial transcript replacement | 20-test revision/claim suite; stable indices and provisional no-authority | Native Whisper is final-only; no interim transport proof |
| Long hesitation | Controller requires final authority | Real endpointing test before irreversible dispatch |
| False start / incomplete entity | Schema and authority controls | Actual audio timing permutations |
| Backchannel / ambient speech | No complete new-route proof | Current speech-start invalidation is broad; handling remains open |
| Barge-in during TTS | Fresh live-controls003 passed actual RTC/Whisper/SAPI control with unchanged1.5s cutoff;001/002 failures retained with measurement diagnoses | Broader timing permutations; exact interrupted prefix remains unknown |
| Late read completion | Actual scripted live-controls002 pending_read passed on current provenance adapter; one admitted read retained with fresh consumer | Broader race timings |
| Successful empty STT | live-empty-stt002 passed explicit fault after real second decode: old waiter retired, outcome retained, clarification captured, third utterance works | Natural empty-recognition perception and broader timing cases; fault control is not a natural perception pass |
| Correction before dispatch | Saturated-executor red/green regression; zero stale backend calls | Real audio dispatch boundary |
| Correction after dispatch | Bridge retains late outcome and suppresses obsolete speech | Real audio with delayed backend |
| Duplicate proposal / retry | Existing authority/ledger tests; reviewed grant-release regression | Full required live permutations |
| Unknown outcome | Bridge unknown write no retry; native durable journal | Actual reconnect and lost-receipt audio scenario |
| Multi-step chain | Existing controller dependent binding tests | Complete judged audio chains after repair |
| Unrelated tasks | Same-turn multiple-result speech regression;34 retained-read controls; one actual scripted pending-read control | Full task scoping and model-driven live cases remain unverified |
| Stale selection / reference | Existing binding/provenance controller tests | Independent migrated-path audio case |
| Cancellation plus replacement |14 new generic actor controls plus26 prior correction controls; independent review; literal single-string bounded scope only | Real audio attempts004/007 failed model proposals; no write admitted |
| Disconnect / reconnect | No complete new-route proof | Required integration work |
| Fresh conversation | New registry/controller/session per recording; bridge fresh-state test | OS-enforced gold isolation and adversarial environment test |
| Long conversation | Planner view retains active constraints and complete outcome ledger while dropping older transcript from prompt | Actual long audio, unbounded ledger limits, and held-out validation |
| Malformed / untrusted tool content | Controller validation, bridge malformed-result unknown, strict JSON controls | Broader actual transport adversarial evidence |

Independent review reproduced and then verified fixes for executor admission,
judge fallback, invalid qualification artifacts, false clarification completion,
lost second-tool speech, duplicate authority release and deferred correction
loss. These results are local fixtures and code review. They are not a claim that
no bug remains. G1 and G2 stay incomplete until their entire required scope runs.

The synthetic development recordings under `.thread-run/raw/developer-audio` are
explicitly authored development data. They are not consented human validation or
held-out data. No benchmark answer text was copied into these fixtures.
