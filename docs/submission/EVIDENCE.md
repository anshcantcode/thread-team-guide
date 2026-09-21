# Participant evidence summary

Updated 22 September 2026. The results below describe recorded development
checks, not a final competition score. The complete original run records and
candidate archives are retained locally; this document is a summary.

## Recorded source identity

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
The runtime source is unchanged by this documentation update, but rebuilding
with updated documentation creates a different archive and manifest. The old
archive's admission result must not be presented as a test of that new archive.

## Results and their limits

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

## Unresolved observations

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
