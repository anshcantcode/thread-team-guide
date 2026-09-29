# Team handoff — 23 September 2026

**We have a working submission foundation, but reliable completion is still a
blocker. We cannot currently claim that the latest project passes every kit test.**

The latest complete public-kit run passed **4 of 9 cases**, scoring **71.5/100
weighted**. An older saved package passed **9 of 9 once**, then failed to repeat
that result reliably. These are results from different saved versions; the good
older run does not qualify the current build.

## What improved since the last published checkpoint

- Interruptions cancel old work, and unresolved new requests no longer display
  the old destination as if it were newly understood.
- Actions carry their authorization and outcome forward. Repeated messages and
  late notifications cannot silently cause another booking or write. Confirmed
  stale outcomes stay recorded without producing an obsolete spoken answer; all
  seven original supplemental late-result checks now pass unchanged.
- Answers preserve the actual returned results and their limitations. Manual
  references are distinguished from ordinary background knowledge.
- Audio handling checks the real recordings and treats uncertain speech
  cautiously. An optional mode reduces calls for eligible lookups without
  granting permission to perform an action.
- A judge can supply a Gemini key and check configuration without spending a
  model request. Packages use an explicit file list to keep private files out.
- Evaluation records the exact build, failed attempts and unfinished cases.
  We have a local demonstration film and a dated comparison of public competitor
  repositories, with the limits of both clearly stated.

The [engineering update](ENGINEERING_UPDATE.md) gives the detailed change list
and the evidence behind each result. The [readiness report](READINESS_REPORT.md)
gives a plain-English assessment, and the [next round plan](NEXT_ROUND_PLAN.md)
assigns the remaining work and defines when each part is complete.

## What is still blocking submission confidence

| Area | What we know |
| --- | --- |
| Model response speed | No native generation response arrived before timeout or cancellation in the latest kit run. Separate full text and audio requests to Gemini 3.5 also received no response within 15 seconds. A tiny health request also timed out, followed by fresh 15-second timeouts on both Linux and native Windows. |
| Alternative model | The same full requests on Gemini 3.1 produced one service error and one audio response after 8.23 seconds. The audio plan was also not fully instruction-compliant. This does not justify switching the default. |
| Repeatability | The older successful package did not finish a passing repeated batch. That batch also encountered the free API's request limit. |
| Unseen cases | Eighteen independent stories are prepared, but none has run against the participant yet. Thousands of scripted checks are not thousands of real model conversations. |
| Current package | The runtime passes 352 offline participant tests. Its fresh review archive passes Windows/Linux offline setup checks; live qualification for this combined source remains unrun. |

The service observations do not identify a single cause for the delay. They do
show why another identical full batch would be a poor use of requests right now.
The free API remains the agreed constraint. No billing change is part of this
checkpoint.

## The next useful round

1. When service conditions support another bounded attempt, measure response
   speed before committing to a full qualification batch. Do not reuse a saved
   answer or extend the official deadlines to make a test pass.
2. Use the saved review archive with a recorded configuration, or freeze a new
   package if the code changes. Run the original public kit, then repeat the
   same package through the full 27-attempt batch and a second passing 27-attempt
   batch, then run the eighteen independent stories. Keep every failure and
   unfinished attempt visible.
3. Update the film and report to the exact qualified package before submission.
   The existing film shows selected successful examples from the older build.

The saved review archive contains the exact tested runtime and is explicitly
marked as unqualified. It still carries draft team metadata for later review.

Start setup with the [judge quickstart](../submission/GEMINI_QUICKSTART.md).
Use the [evidence ledger](../submission/EVIDENCE.md) for measured results and the
[competitor comparison](COMPETITOR_COMPARISON.md) for dated public observations.

There is no defensible probability of winning or verified ranking against other
teams. The next confidence increase must come from repeated complete tasks with
real audio and images, within the original deadlines.
