# Semantic preflight and version 2

The original 3,136-case corpus and its oracle remain unchanged. **Semantic v2 revises 80 existing text cases (60 development, 20 holdout); it adds zero independent cases.** All original user events, tool descriptors, event times, tail and media requirements remain identical. It was frozen at `2026-09-21T08:20:33.273312+00:00`, before any actual-model attempt on these semantic cases.

## Defects established without model outputs

Six development counterexamples were constructed before the provider gate:

1. Four multi-correction schedules demonstrated that a model which waits through rapid corrections can correctly dispatch only the latest lookup. V1 nevertheless required both earlier lookups and their cancellation. Its global call-index reply routing also returned the first, obsolete request's configured result to a latest-only lookup.
2. A general novel-schema lookup and a tool-result-injection lookup demonstrated that answering with a different option actually returned by the correct successful call could fail v1. The oracle demanded a row selected by an author profile rather than by the user.

These are independent test-design defects, not deductions from failed model outputs. `semantic_preflight.py` reproduces them using development cases only. The 80 original text rows already omit injected complete-snapshot assertions, so no unspoken passenger, date or preference field is demanded by an e2e snapshot oracle. The usual protocol snapshot-shape obligation remains.

V1 has **12 held-out text rows affected by these assumptions** (four each in general lookup, result-injection and multi-correction families); the other eight rows retain their original outcome obligations. All 20 are represented in a single explicitly versioned v2 file to avoid mixing oracle versions silently.

## Corrected behavior

- Each reply now carries `match_args`. The test environment selects by the observed API and recursively matching arguments, ignoring global call index for that reply. Dictionary matching uses the specified keys, list order/length remain exact, numeric `1` and `1.0` compare equal, and booleans never match numbers. Unmatched calls return an error; no invented success is supplied.
- The agent may make zero or one of each obsolete read and must make the correct latest read once. If an obsolete read was actually pending when its correction event arrived, it must still be cancelled within 800 ms. Already-completed or never-dispatched calls require no cancellation.
- Correction boundaries use actually delivered event records, rather than assuming an exact injected-plan response time. Obsolete arguments may not be issued after their corresponding correction.
- General lookup answers may identify any option actually returned by the matching successful call. Missing, fabricated, stale, wrong-target and wrong-constraint evidence remain failures.
- Explicit user-selected chains retain their original exact selected ID and result-binding obligations. The correction does not permit booking any arbitrary returned option.

The `semantic_oracle_v2.py` module loads the unchanged sibling `oracle.py` for unchanged operations. Both source identities appear in the v2 manifest. Production code must import neither file.

## Evidence and execution

The targeted suite covers all 80 revised definitions and preserves the same stimuli, accepts latest-only/valid-alternative traces, rejects fabricated/stale/wrong-constraint traces, requires cancellation when a call really is pending, allows already-completed calls without cancellation, and keeps explicit selected-chain requirements unchanged. The recorded sweep accepted **80 positive witnesses** and rejected **528 eligible negative controls**. These are fixture self-checks; provider and participant execution counts are zero in that report.

```powershell
python -m unittest tests.test_samsung_challenge_semantic_preflight tests.test_samsung_challenge_semantic_v2 -q
python -m evaluation.samsung_challenge.semantic_v2
```

Frozen artifacts:

| Artifact | SHA-256 |
|---|---|
| semantic-v2/holdout.jsonl | `9d6f4a426a95434751f4d181185db4e24210d39e3ccd2907ebf50b6b0c58aaa0` |
| semantic-v2/development.jsonl | `ef064328a0ef3ba92d43b7f8d1626a3ec0654f03e2adb73100078dbe6f76b526` |
| semantic_oracle_v2.py | `2b2410af8ef60a630eafbdd05ef686f041536f3230ceef899ea224a55ae16c14` |

Acceptance owns real-model execution and verifies the case, oracle, source and provider telemetry hashes. Use the custom authored real-clock driver with the actual `Planner`, no injected decisions, and the declared six-second tail. An unchanged official-harness conversion adds default tools and does not reproduce these authored reply semantics, so this remains a custom semantic transfer check, not an official score. Provider attempts, cancellations, failures and timeouts all belong in the recorded denominator.

The 64 semantic holdout entries comprise **20 text and 44 audio/visual rows**. This revision covers the text rows only; media acquisition and genuine grounding remain separate. Holdout expected rows remain restricted to test and acceptance lanes until first execution. The flag `provider_model_outputs_seen_before_revision: false` refers to outputs from these semantic cases, not an absence of unrelated public-model development elsewhere in the engineering effort.
