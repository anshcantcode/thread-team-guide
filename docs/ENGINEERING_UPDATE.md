# Engineering update — historical checkpoint

This page preserves the **22 September** checkpoint. For the current work,
results and next steps, read the [23 September team update](submission-2026-09-23/ENGINEERING_UPDATE.md).
The pending repairs and blockers below describe that earlier source.

Updated 22 September 2026. This is a development branch for team review.

We have connected the existing Android and browser project to the official
Samsung participant interface, added stronger checks around interrupted tasks,
and made Gemini setup easier. Reliable completion of the full public kit is
still the main unfinished work.

## What changed since the previous team repository commit

The comparison starts at `62781833b175ef7c614fb188f7a1bf3af024d7fa`.

- **Official evaluation entry point:** `participant.agent:ParticipantAgent` now
  accepts the kit's input events and returns actions through its queues. It
  handles setup, shutdown and tool results that arrive after user input ends.
- **Corrections and interruption:** decisions belong to the current request.
  Corrections cancel obsolete work; an older result cannot take over a newer task.
- **Tool actions:** the participant reads the tools supplied at runtime, checks
  argument types and uses actual returned values for follow-up actions. Actions
  that change something need current user permission, and duplicate proposals
  cannot repeat an already submitted effect.
- **Audio and images:** the participant reads actual media bytes. Malformed MP3
  inputs are rejected before a provider request. Disagreement between a planning
  result and its speech transcript leads to clarification. These checks do not
  establish that recognition is always correct.
- **Answers and citations:** manual references must match returned evidence.
  Unicode citation handling is integrated. A further answer-preservation repair
  is saved in [the pending proposal](../proposals/manual-receipt/README.md).
- **Setup:** [Gemini setup](GEMINI_SETUP.md), the offline configuration check and
  [the evaluation quickstart](submission/GEMINI_QUICKSTART.md) explain API keys,
  model settings and troubleshooting. Configuration checks do not test quota or
  response speed.
- **Packaging:** dedicated requirements, a Docker recipe, an allowlisted archive
  builder and file hashes make a candidate reproducible and inspectable.
- **Tests:** 3,136 authored challenge cases cover corrections, cancellation,
  permission, unfamiliar tools, result handling and media. They are our test
  inputs; their count is not a count of successful model conversations.

Existing Android, browser, backend and film sources remain part of the project.
Gemini is the delivery path; local-model experiments are not required to run it.

## Current results

| Check | Last recorded result | What it establishes |
|---|---|---|
| Integrated Python suite | 792 test methods passed | Regression checks on the integrated source; includes inherited methods. |
| Last complete public batch, candidate 009 | 62.6 weighted points; 6/27 mandatory completions; 4/27 full checks | Nine public scenarios repeated three times. The full kit is not passing. |
| Candidate 010 packaging | Reproducible archive; clean Python admission passed | Packaging and interface admission for that exact historical archive. |
| Candidate 010 public text check | One unchanged official text case scored 100 and passed all task checks | A narrow local text path; this is not a new full public batch. |
| Malformed-media checks | 32/32 cases passed on the frozen repair | Invalid inputs were contained without provider calls. |
| Pending answer-preservation repair | 82 scoped checks passed | Separate proposal; it has not been integrated into the main participant. |

These results were recorded before this documentation cleanup. No fresh provider
run or full public batch was performed for this update. Original experiment
records and candidate archives are retained locally with their original bytes.
The public branch carries active source, fixtures and this results summary.

## What still blocks submission

- Audio planning has timed out before a useful response. The cause has not been
  isolated. A successful configuration check does not resolve it.
- A faster image experiment completed its tool-and-citation flow but still made
  an unsupported output claim. Correct tool use alone did not make the answer pass.
- Candidate 010 has no complete public batch or Linux qualification. Candidate
  009's earlier Linux result cannot be transferred to it.
- The pending controller repair needs integration, followed by fresh checks.
- The final package, demonstration and submission materials need team review.

## Next steps

1. Review the pending repair and integrate it only after checking its baseline.
2. Qualify one Gemini configuration for actual audio, image and unfamiliar-text
   requests within the evaluator's deadlines.
3. Build a new package and verify it in a clean Python environment and on Linux.
4. Run two complete unchanged public batches on that exact package. Check task
   completion, tool receipts, answer correctness and timing alongside the score.
5. Test unfamiliar recordings and images, then rehearse the final demonstration.

See [the evidence summary](submission/EVIDENCE.md) for source identity and limits.
