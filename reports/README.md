# Verification output

Verification scripts write their results to this directory. Generated logs, device exports, and provider transcripts are ignored by Git because they may contain machine-specific or private context.

The checked-in [public-source validation record](public-source-validation.json) contains only aggregate check results and source-file hashes. See [validation scope](../docs/VALIDATION.md) before using any result in a presentation.

Generate a deterministic replay locally with:

```powershell
.\.venv\Scripts\python.exe scripts/check_theme5.py --seeds 50
.\.venv\Scripts\python.exe scripts/render_evidence.py
```

The second command creates a trace viewer from the generated replay. It does not invent model results when no matching model reports are present.
