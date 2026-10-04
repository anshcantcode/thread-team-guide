# Participant evidence summary

**Historical legacy queue-kit evidence, not FDB-v3 or the 3 October candidate.** “Current” below is relative to the dated 23 September snapshot. Use [the current submission index](README.md) and [source-labelled FDB-v3 results](RESULTS.md).

Updated 23 September 2026. **The participant is not yet qualified for submission.**
The current source and the latest live-tested package are different:

Source IDs below identify saved local development snapshots. The team checkpoint
contains the combined current files; those earlier commits are not all published.

| Evidence | Result and scope |
|---|---|
| Current runtime, `8ee289e` | 352 offline participant methods pass. Old intent/slots remain hidden while a changed request is unresolved. Confirmed stale writes are recorded without producing stale speech; the original seven supplemental probes pass unchanged. No live result for this combined source. |
| Latest live diagnostic, `e5b97d3` | All nine original cases ran once: 4 PASS / 5 FAIL, 71.5 weighted / 73.8 plain. All six generation requests ended without a response; one embedding succeeded but was unused. Experimental `single_call_reads`, temperature 1.0. |
| Preceding diagnostic, `d394a46` | 5/9 pass, 76.4 weighted / 79.6 plain, same optional audio profile before the temperature change. Neither run establishes reliable delivery or a temperature effect. |
| Earlier successful snapshot, `0bf30ee` | 9/9 pass at 100/100 once with default independent audio. Its unchanged repeated batch later returned 13 PASS / 4 FAIL, stopped on quota during the next attempt, and left nine unrun. No complete passing repeated batch. |
| Setup | The current review archive from `1a18c97`, with the tested `8ee289e` runtime, passes fresh-extraction Windows/Linux offline admission using existing pinned environments and default independent audio. It has 52 verified members and no live result. Earlier measured packages also pass offline admission. The earlier `0bf30ee` archive also installed in new empty virtual environments using the same pinned dependencies and existing Python 3.11.9. |
| Fresh service health comparison | One tiny Gemini 3.5 request on Linux and one on native Windows both timed out without headers or a body within 15 seconds. Same body/model/project, two generation starts, normal worker cleanup; this is diagnostic evidence, not a kit result or an identified cause. |
| Independent stories | 18 prepared stories remain unrun against the participant; thousands of scripted controller checks are a different kind of evidence. |

The current offline-checked review archive has SHA-256
`3714ea142cdd3fb8c77ed48d5c085ed056c572f22733e4009653079eb049c1e8`. It is explicitly unqualified.

The latest live archive's SHA-256 is
`9f13d55788a4465767bb1c1a8ae0ee228e8c03ed40849c714d1b06fb7898926e`.
Its independent factual and delivery review is sealed. Review receipt SHA-256:
`042efb322d31e5f0078a4759cfff4d8995ebb78dc8947da8be0caa9261627f8d`.
Original failed and partial runs remain retained locally. See the
[current team update](../submission-2026-09-23/ENGINEERING_UPDATE.md) for details,
limitations and the next steps. These results are neither a competition ranking
nor a hidden-test pass rate.

## Historical checkpoint — 22 September

The remainder preserves the earlier checkpoint. Its source identities, pending
proposal and unresolved observations refer to that date, rather than the current
participant. The results below describe recorded development
checks, not a final competition score. The complete original run records and
candidate archives are retained locally; this document is a summary.

## Historical source identity

The integrated participant had these SHA-256 values when the 792-method suite
passed:

| File | SHA-256 |
|---|---|
| `participant/agent.py` | `3f1dcd4a318f5acf91e900e082ec89972720713d2611ca22061147be4b55f7c2` |
| `participant/planner.py` | `b9e5199bef7bb17da86c8a646e0941f82d876479654f91960261695bde6ffef5` |

Candidate 010's historical ZIP SHA-256 is
`682f9378206c62aa10f6f7436ea254e54a71396386093cd42b0f068015543f67`.
It contained 53 files and preserved all 33 selected official kit files. It is
retained locally and is not included as a release archive in this branch.
At that checkpoint the runtime source was unchanged by the documentation update, but rebuilding
with updated documentation creates a different archive and manifest. The old
archive's admission result must not be presented as a test of that new archive.

## Historical results and their limits

- **Integrated regression suite:** 792 Python test methods passed. This includes
  inherited test methods; it does not mean 792 independent conversations. A
  nonfatal Windows asyncio callback warning was recorded in the original run.
- **Last complete official public batch:** candidate 009 scored 62.6 weighted
  points, with 6/27 mandatory task completions and 4/27 full acceptance checks.
  This was nine scenarios repeated three times. It remains a failed full gate.
- **Candidate 010 admission:** clean Python import and interface checks passed;
  repeated builds produced the same archive bytes for those original inputs.
- **Candidate 010 text check:** one unchanged official text case scored 100 and
  met all task checks through a narrow local path, without a generation request.
  No complete public batch or Linux run exists for candidate 010.
- **Media validation:** a frozen integrated repair passed 32 malformed-input
  checks with zero network attempts. That proves the checked rejection paths,
  not speech recognition or visual understanding.
- **Authored challenge coverage:** 3,136 cases are frozen: 2,880 controller,
  80 text, 80 audio and 96 visual cases. Authored, executed, blocked and passed
  counts must remain separate. Many semantic cases still need real media.
- **Separate controller proposal:** the answer-preservation repair passed 82
  scoped checks on its own source. It is not integrated into `participant/`.

## Observations at that checkpoint

Speech attempts have timed out without response headers; the reason is not yet
established. The API project uses the free tier. This observation alone does not
prove quota is the cause. One faster image experiment reached tool results and
citations within its deadline, but its final answer still made an unsupported
claim. These attempts are failures, not evidence that media delivery is ready.

The historical internal scores and pre-kit replay results are not official-kit
acceptance results. No hidden-test pass rate or chance of winning is established.

## Reproduce current checks

From the repository root with the documented Python dependencies installed:

```sh
python -m unittest discover -s tests -q
python scripts/check_gemini_config.py --profile participant
```

The configuration check is offline. Follow `GEMINI_QUICKSTART.md` in this folder
for packaging and the actual official evaluator. Preserve the supplied kit and
record new output directories for every attempt. Run the completed package on
Linux and repeat the full public batch before claiming submission readiness.
