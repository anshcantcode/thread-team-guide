# Samsung PRISM Theme 05 requirements

Organizer material was checked on 30 September 2026; deadline wording below incorporates the owner's 3 October update. The newer Theme 05 FDB-v3 guide takes precedence over the earlier queue-kit scoring. The selected final catchup source, new results and continuous video are pending. The human form has not been submitted.

Primary sources: [updated Theme 05 guide](https://drive.google.com/file/d/12RPdEbggSayVHNoFk1zPNqKOdVRQ_vio/view), [general submission brochure](https://drive.google.com/file/d/1SVFfMhULQUf6BX9NS1lAyjqsnCGOOPtm/view), [required AI disclosure form](https://drive.google.com/file/d/1e-RF-mUT2xbyAxUMccfnlRLOQ33MUXMl/view).

| Requirement | Release status / evidence |
|---|---|
| FDB-v3 LiveKit voice agent | Implemented. Historical complete WebRTC runs use the pinned upstream contract and released human recordings. |
| Evaluate 100 recordings / 79 scenarios / 12 speakers / 12 mock tools | Three newer complete historical runs audited; 100/100 coverage each. Current changed source needs a fresh full qualification. |
| Organizer rerun determines benchmark score | Explicit throughout current README/evidence. Local Qwen results are diagnostic only. |
| 60% benchmark, 20% extension, 20% architecture/docs/video | The tour distinguishes the benchmark and the real checklist extension; no invented normalized total. |
| Real extension beyond mock domains | Browser and Android Kitchen perform actual client-owned checklist actions through the current controller. Tethered local host required. |
| README setup, architecture, extension, one-command install/configure/evaluate | Current docs and `scripts/reproduce_fdb3_linux.sh` supplied. Full independent Linux/GPU rerun remains unqualified. |
| Declare model, dependencies, seeds, config and results/logs | Pins live in `config/` and locks; archived source identities retained. Historical runs used temperature 0 and no explicit seed. The release declares seed 42 for future runs; those historical measurements do not transfer. |
| No benchmark memorization, test-item tuning or cross-scenario cache reuse | No gold-answer lookup is part of the runtime. Repaired general mechanisms have independent regressions. Cache ownership is scenario-scoped. This is not proof of an OS sandbox. |
| Standard NVIDIA 48 GB / CUDA 12.x or 13.x environment, or declared hosted API | Local route provided; organizer hardware has not been exercised here. Hosted spending remains unauthorized. |
| 3–5 minute real demonstration; unedited preferred | Historical edited/animated media are retained. The new continuous final-source take is pending; use DEMO_RUNBOOK.md. No new active-speech barge-in pass is claimed. |
| Up to eight slides | Final eight-slide [THREAD_Theme05_Deck_20261004.pptx](THREAD_Theme05_Deck_20261004.pptx), also the team's shared deck, carries the measured results. Original deck untouched and historical. |
| Public or shared repository | Owner authorized public visibility on 30 September. Verify unauthenticated repository and release access after publication. |
| Final tag `PRISM_GENAI_HACKATHON_Y2026` and all referenced assets | Existing tag/release is an earlier reference. Verify or update through the owner-approved release workflow after final selection; no tag/publication change in S3. |
| College/team filenames, forms and links | College and four members supplied by the team deck. Human representative, final form and exact cutoff time still require confirmation; owner reports 4 October 2026. |
| AI tool/platform, prompts, outputs, modifications and human signature | [Disclosure](AI_DISCLOSURE.md) retained truthfully. Human review, classification and signature remain outstanding. |

The guide describes a pinned LLM judge but the material supplied here does not establish a complete organizer judge snapshot or normalization formula. A different-model re-judge is not a forecast of the official score. The six locally observed expected-answer/public-schema conflicts require organizer adjudication; they do not prove every entrant is unable to pass.

The older brochure gives 25 September as its cutoff. The owner now reports **4 October 2026** (3 October task update), superseding the earlier owner-reported 30 September extension. The exact cutoff time, timezone and final form must still be confirmed from organizer communication; no independent deadline verification is claimed here.

Three fresh, preregistered 100/100 runs are an internal engineering target, not an extra requirement invented on behalf of Samsung. They have not been achieved.

## Before final submission

1. Run the selected frozen source through the full official pipeline on a clean compatible host. Retain every failure, extra call and infrastructure error.
2. Review the actual current recording and at most eight slides; align every claim with its source revision and evidence.
3. Fill team fields, classify assistance accurately, inspect the organizer's form, and obtain the human signature.
4. Verify judge repository/media access, the deadline and the actual form link.
5. Tag the selected final commit exactly as required and submit its links. The repository release does not submit the organizer form.
