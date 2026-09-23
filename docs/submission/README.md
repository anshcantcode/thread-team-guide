# Samsung participant package

Start with [the judge quickstart](GEMINI_QUICKSTART.md). It installs the pinned
runtime, configures a judge's Gemini key and checks the queue contract offline.
The entry point is `participant.agent:ParticipantAgent`; no app server is needed.

This is an **unqualified submission candidate**. Passing installation, the doctor,
or the offline verifier does not establish live task correctness. The last complete
historical candidate-009 batch scored 62.6 weighted, with 6/27 mandatory and 4/27
full passes. Historical evidence remains in the source repository's
`docs/submission/EVIDENCE.md`; it is not a result for a newly built archive.
The team value remains `LOCAL_DRAFT_TEAM_METADATA_REQUIRED` until the registered
identity is provided. No institution or registration has been inferred.

## Build from the unchanged official kit

Use Python 3.11. Install `requirements-submission.txt` in the external environment
described in the quickstart; the same ten exact pins appear in `submission.yaml`.
From the source checkout, with an absolute path to the separately retained kit:

```powershell
$python = '../thread-judge-local/venv/Scripts/python.exe'
$kit = 'C:/absolute/path/to/unchanged/participant-kit'
& $python -B scripts/package_samsung_submission.py --kit $kit --source . --output ../thread-candidate-001
& $python -B scripts/verify_samsung_submission.py --kit $kit --submission ../thread-candidate-001 --out ../thread-judge-local/candidate-001-offline.json
```

On Linux use `../thread-judge-local/venv/bin/python -B` and an absolute kit path.
Use new candidate and receipt names for every changed identity. Keep environments,
key files and receipts outside both the retained kit and frozen candidate.

The builder selects explicit files: seven runtime Python modules, the submission
configuration, dependency pins, packaging/doctor/verifier scripts, onboarding
documents, the reviewed blank environment template and the original kit's 34 files.
The kit's sample `submission.yaml` is replaced; its original SHA-256 is retained.
The other 33 official files, including scorer, harness, scenarios and encoded
MP3/PNG assets, are copied byte-for-byte. Evaluation annotations are inputs to the
unchanged harness and must never be read by the participant.

`PACKAGE_MANIFEST.json` records actual file hashes, original kit hashes and Git
revision. Uncommitted bytes are identified by their file hashes. The sibling ZIP
uses fixed ordering, timestamps and permissions; identical inputs produce the
same ZIP with the same Python/zlib version. Packaging checks CRCs, byte round trips
and unchanged upstream hashes. Private files, new tests, challenge corpora,
app code, local models and historical reports are outside the explicit allowlist.
The verifier rejects missing, changed or extra candidate files, apart from Python
bytecode caches; use `-B` to avoid creating those caches at all.

## Configuration and verification

The supported setup profile is spelled out in the quickstart and `.env.example`.
The doctor checks key presence, alias precedence, provider/model, thinking,
deadline, prewarm, embedding and media-root settings without displaying values or
importing the planner. It is deliberately stricter than runtime override support:
an alternative profile is a different experiment and fails this setup check.

The verifier isolates the caller's environment, blocks external network access,
checks exact installed dependencies and official admission gates, then exercises
in-memory transport and queue exchanges. It also compares runtime defaults,
key-only setup, explicit-file setup, example and quickstart. There is no hidden
prewarm override and no setup generation request. Synthetic provider responses
prove wiring only; they do not prove model quality, access, quota or latency.

For relative media references, run live evaluation from the extracted package
root containing `audio/` and `frames/`, or explicitly set `PARTICIPANT_MEDIA_ROOT`
to the retained kit. The original setup cap (300 seconds), scenario cap
(120 seconds), tail (6000 ms) and per-event deadlines stay unchanged.

After acceptance has allocated free provider capacity, the official command from
the extracted candidate root is:

```powershell
& ../thread-judge-local/venv/Scripts/python.exe -B eval_submission.py . --reps 3 --time-scale 1 --out ../thread-judge-local/candidate-001-official.json
```

Keep every failed, blocked and unrun attempt visible. Final public qualification
requires all nine unchanged cases across three repetitions for the exact frozen
package/configuration, plus factual review. Linux/live evidence is recorded by
independent acceptance. No new live qualification or Linux success is asserted
by these instructions.

## Optional container rehearsal

The Dockerfile installs only submission dependencies and copies the runtime and
required onboarding/verifier files. Mount the separate unchanged kit read-only:

```sh
docker build -f Dockerfile.submission -t samsung-participant:local .
docker run --rm --network none --mount type=bind,src=/absolute/kit,dst=/kit,readonly samsung-participant:local
```

These are runnable instructions, not a claim that Docker was tested on this host.
The default command is offline. Actual model calls, full qualification, registered
team metadata and the final administrative submission remain separate gates.
