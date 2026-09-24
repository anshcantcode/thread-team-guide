# Aura Samsung: Theme 5 confirmation and cancellation audit

Checked 2026-09-24 against the latest public `main` ref at the time of the audit.

## Source and scope

- Repository: [`xan-antx/aura-samsung`](https://github.com/xan-antx/aura-samsung)
- Pinned commit: [`6b277a2e2e63f43459d4b264b4597012d701b162`](https://github.com/xan-antx/aura-samsung/commit/6b277a2e2e63f43459d4b264b4597012d701b162), `live chat, Groq support, provider hardening` (2026-09-24).
- THREAD baseline: clean worktree branch `codex/aura-confirmation-peer-audit`, fast-forwarded from `6278183` to `origin/codex/provider-route-benchmark` at `09f91640dd833cab7efaa387cd52847260802c35` before this report was added.
- Tested the current `demo_llm_answers.py` mock-mode conversation flows plus the README-documented `harness.py --selfcheck` and `harness.py -q` checks. The peer source lived in a separate temporary clone. No dependencies were installed, no live-provider mode was run, and no THREAD API credentials were present or used.

## Commands

PowerShell, from the THREAD worktree. The initial checkout was clean and detached at `6278183`:

```powershell
git switch -c codex/aura-confirmation-peer-audit
git merge --ff-only origin/codex/provider-route-benchmark
```

The merge fast-forwarded to `09f91640dd833cab7efaa387cd52847260802c35`.

Then, still from the THREAD worktree, pin the isolated peer checkout:

```powershell
$peerDir = Join-Path $env:TEMP 'aura-samsung-peer-audit-2026-09-24'
$removed = Get-ChildItem Env: | Where-Object { $_.Name -match '(?i)thread.*(api|key|token|secret)|(api|key|token|secret).*thread' } | Select-Object -ExpandProperty Name
git ls-remote https://github.com/xan-antx/aura-samsung.git HEAD refs/heads/main
git clone https://github.com/xan-antx/aura-samsung.git $peerDir
git -C $peerDir checkout --detach 6b277a2e2e63f43459d4b264b4597012d701b162
git -C $peerDir rev-parse HEAD
```

The credential-name scan printed `THREAD_CREDENTIAL_ENV_NAMES=none`. From the isolated peer checkout, the documented checks were run with the installed supported Python 3.11 runtime after clearing provider-related environment variables:

```powershell
$names = @('THREAD_API_KEY','THREAD_API_TOKEN','THREAD_API_SECRET','OPENAI_API_KEY','GEMINI_API_KEY','AURA_LLM_URL','AURA_VLM_URL')
foreach ($name in $names) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue }
py -3.11 --version
py -3.11 demo_llm_answers.py
py -3.11 harness.py --selfcheck
py -3.11 harness.py -q
```

The `git ls-remote` result was `6b277a2e2e63f43459d4b264b4597012d701b162` for both `HEAD` and `refs/heads/main`; the detached checkout resolved to the same SHA.

## Results

- Python: `3.11.9` (within the README's stated Python 3.10–3.12 range).
- `demo_llm_answers.py`: exit 0. All five conversation flows passed in mock-LLM and deterministic modes with byte-identical traces. The nine affirmative and four negative wording cases also passed. In particular, confirming a slot booked the confirmed Pune flight; accepting the cancellation offer issued `cancel_booking` for `PNR5797`; saying “book it” during that offer did not cancel.
- `harness.py --selfcheck`: exit 0, `selfcheck ok`.
- `harness.py -q`: exit 0. All 16 scenarios scored `100.0`; “yes to a slot confirmation unblocks the booking” and “yes to the cancel offer cancels the superseded booking once” each scored `100.0`. Mean: `100.0 / 100` over 16 scenarios.

## Scorer provenance and limits

Aura uses its own scorer. The pinned [`harness.py`](https://github.com/xan-antx/aura-samsung/blob/6b277a2e2e63f43459d4b264b4597012d701b162/harness.py#L419-L421) defines `score(scn, run)` locally, and the pinned [README](https://github.com/xan-antx/aura-samsung/blob/6b277a2e2e63f43459d4b264b4597012d701b162/README.md#stubbed-deliberately) explicitly says the scorer is not the real scorer. Its [organisers' kit section](https://github.com/xan-antx/aura-samsung/blob/6b277a2e2e63f43459d4b264b4597012d701b162/README.md#swapping-in-the-organisers-kit) says to replace the local manifest, tool runner, and scenarios with the kit's and remove the local scorer. The reported 100 is therefore Aura's own simulation score, not a result from the supplied Samsung evaluator.

The answer-flow script ran only its documented local mock mode. No real model/provider comparison or Samsung-kit evaluation was performed. The checks cover the published deterministic conversation behavior at this commit; they do not establish live-model extraction quality or comparable official qualification.
