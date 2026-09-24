# AccessFlow official-kit smoke audit

Date: 2026-09-24

## Target identity

- Public repository: [MridulNegi2005/AccessFlow](https://github.com/MridulNegi2005/AccessFlow)
- Clone origin: `https://github.com/MridulNegi2005/AccessFlow.git`
- Pinned commit: `749fe23aac10e5d79b74f75fdb257500702fee65`
- Commit subject: `Preserve raw audit evidence line-ending conventions`
- Author/date: Mridul Negi, `2026-09-24T13:51:23+05:30`
- The clone was detached at the requested commit under ignored `.runtime/`; its Git worktree was clean. No competitor source or Samsung kit files were edited.

## Published score claim

The latest candidate-package evidence in `docs/evidence/package-profile-2026-09-24/verification.json` records one `pub_03_text_chained_booking` attempt with score `100.0`, one `flight_search`, one `book_flight`, and a final response at `6375 ms`. The trace’s official latency score comes from a filler at `22 ms`; it does not mean the final response arrived in 22 ms. This is one exposed public text case, not a nine-case aggregate or repeated median.

I verified all 11 byte counts and SHA-256 values listed in that evidence directory’s `manifest.json`. I then rescored the preserved trace against the kit’s `pub_03_text_chained_booking.json` using the THREAD kit scorer; it returned `100.0`, matching the published value. The verified `verification.json` SHA-256 is `a66ee8fb39a2e679c26ee32c00695f91c922d986e68df5309868a54eb4c909c8`.

The score bundle’s package manifest identifies base commit `89f5407eabffa603c194ff1c702732dbad579815` and `source_dirty: true`, so I did not treat it by itself as a clean run at the requested commit. I rebuilt the candidate package from the pinned commit and the THREAD kit using the documented `AccessFlow`, `qwen/qwen3.8-27b`, `compact-v2` / `evidence` profile. Seventy-seven of its 78 package-input hashes match the published package manifest; the only mismatch is the copied build input `build_inputs/uv.lock`. The requirements pins, packaged implementation, entry wrapper, and kit files match. This supports the score record’s source correspondence, but does not turn that one prior attempt into a fresh score at the pinned commit.

## Official Samsung package and contract smoke

Environment: Windows, Python `3.11.9` (the package declares Python 3.11), isolated venv, and the candidate’s 21 exact public-PyPI pins. The published verification reports Python `3.11.15`; this smoke used the installed `3.11.9`. `uv` and Docker were unavailable, so I called the repository’s `assemble()` helper directly with the published exact pins and the THREAD kit at `theme5_kit/participant-kit/participant-kit`. The generated package and venv stayed in ignored runtime/artifact directories.

The evaluator was the untouched THREAD copy of `eval_submission.py`, SHA-256 `37c1b3ec9bfdeb5525d2625ee3b2131ef9a41acf3d8844ed2a208ec99dcc3504` (Git blob `8c60fe197e9e341945ce231bb64c88d58090fb31`). The package copy matched it byte for byte.

Commands and evaluator calls:

```powershell
git clone --no-checkout https://github.com/MridulNegi2005/AccessFlow.git .runtime/accessflow-749fe23
git -C .runtime/accessflow-749fe23 checkout --detach 749fe23aac10e5d79b74f75fdb257500702fee65
git check-ignore -v .runtime/accessflow-749fe23/README.md

py -3.11 -m venv .runtime/accessflow-package-env
.runtime/accessflow-package-env/Scripts/python.exe -m pip install --index-url https://pypi.org/simple -r .runtime/accessflow-749fe23/artifacts/peer-audit-official-smoke/requirements.txt
```

Package assembly used `scripts.build_samsung_package.assemble()` with these values: repository `.runtime/accessflow-749fe23`, kit `theme5_kit/participant-kit/participant-kit`, output `.runtime/accessflow-749fe23/artifacts/peer-audit-official-smoke`, `team="AccessFlow"`, `model="qwen/qwen3.8-27b"`, requirements read from `docs/evidence/package-profile-2026-09-24/requirements.txt`, `prompt_profile="compact-v2"`, and `read_answer_mode="evidence"`.

I called the untouched evaluator’s `validate_submission(package_dir)` and, if validation succeeded, `contract_smoke_test(agent_class, 300.0)` from that venv with isolated Python (`-I`). Results:

- Package/YAML/entry-point validation: **passed**, no errors; entry point was `agent.agent:ParticipantAgent`.
- Contract smoke: **stopped in `setup()`** with `ValueError: Supply SECRET_GROQ_API_KEY; no credential is included in the package`.
- Neither `SECRET_GROQ_API_KEY` nor `ACCESSFLOW_GROQ_API_KEY` was present. Setup failed before hosted model warm-up; no provider request was made.
- No representative public scenario was run because this candidate requires that key and hosted warm-up to initialize. The smoke failure is a credential blocker, not a scenario score.

The repository’s README and status documents describe other historical test counts and isolated results. They were not rerun here and are not presented as current verification. This audit does not claim a complete official evaluation, multimodal readiness, or a new score.
