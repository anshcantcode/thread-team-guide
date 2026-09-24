# AccessFlow pending-frame peer audit

Audited 24 September 2026 in a temporary checkout of the public
[AccessFlow repository](https://github.com/MridulNegi2005/AccessFlow) at exact
HEAD `749fe23aac10e5d79b74f75fdb257500702fee65`. Its
[docs/STATUS.md](https://github.com/MridulNegi2005/AccessFlow/blob/749fe23aac10e5d79b74f75fdb257500702fee65/docs/STATUS.md)
describes four gated pending-frame controller failures. The retained
[audit README](https://github.com/MridulNegi2005/AccessFlow/blob/749fe23aac10e5d79b74f75fdb257500702fee65/docs/evidence/merge-readiness-2026-09-24/README.md)
supplies the reproduction procedure and explicitly separates these failures
from the passing standard suite.

The peer checkout was clean and detached at the requested commit. The retained
probe fixture SHA-256 was
`45735f5920eee8de1062b632e5148f898957e3ca1ccfadcdade3be166dceb5c8`, matching
the peer's `manifest.json`. The peer README identifies reviewed application
commit `e7c95f576c5ba4713d27df9976301e0f451d0b07`; it says the unfinished repair
was not applied to that source.

## Commands

The THREAD report branch was created at the existing benchmark tip before this
file was added:

```powershell
git switch -c codex/accessflow-pending-frames-audit origin/codex/provider-route-benchmark
```

The command reported the branch tracking `origin/codex/provider-route-benchmark`
at `09f91640dd833cab7efaa387cd52847260802c35`. The benchmark tip is a descendant
of the saved project `main` branch.

Peer checkout and revision verification (PowerShell):

```powershell
$peer = Join-Path $env:TEMP 'accessflow-pending-frames-749fe23'
git -c credential.helper= -c core.askPass= clone --no-tags --no-checkout https://github.com/MridulNegi2005/AccessFlow.git $peer
git -C $peer -c credential.helper= -c core.askPass= checkout --detach 749fe23aac10e5d79b74f75fdb257500702fee65
git -C $peer rev-parse HEAD
git -C $peer status --short --branch
```

Offline probe setup and documented reproduction, from the peer checkout root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
New-Item -ItemType Directory artifacts/peer-audit-accessflow-749fe23
Copy-Item docs/evidence/merge-readiness-2026-09-24/pending_frame_probe.py.txt artifacts/peer-audit-accessflow-749fe23/pending_frame_probe.py
.\.venv\Scripts\python.exe -m pytest artifacts/peer-audit-accessflow-749fe23/pending_frame_probe.py -q -o "pythonpath=. tests/engine"
```

The first two commands prepared Python 3.11.9 and installed the declared test
extras in that temporary checkout; `pytest` was 8.4.2 with `pytest-asyncio`
0.26.0. The probe used its own gated fake perception and mock tools. No THREAD
API credentials were supplied, and the probe made no live provider, model,
microphone, or booking calls. Dependency installation used the package index;
the probe run itself was offline.

## Outcomes

The fixture hash matched. Pytest exited `1` with **4 failed in 2.86s**, matching
the four failures documented in AccessFlow's retained evidence:

| Probe | Observed failure |
|---|---|
| `test_current_image_delays_final_and_write_but_allows_read_prefetch[final]` | Emitted a final while the current frame was still pending. |
| `test_current_image_delays_final_and_write_but_allows_read_prefetch[write]` | Registered a write before the current frame completed. |
| `test_current_image_delays_final_and_write_but_allows_read_prefetch[read]` | Emitted a final before the pending current frame completed after read prefetch. |
| `test_current_frame_failure_is_reported_after_new_speech_and_resumes` | Timed out after 2 seconds waiting for the frame backend error; recovery final was not observed. |

These are reproduced controller failures, not passing safety evidence. No blocker
prevented reproduction. No THREAD source, Samsung kit, or other agent file was
changed; this report is the only change on the report branch.
