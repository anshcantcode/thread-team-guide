# Independent DUET public evaluator run

Checked 24 September 2026 against [DUET Team SE7EN](https://github.com/tannnmayy/DUET-SAMSUNGPRISM-HACKATHON-TEAM-SE7EN) at detached commit `4d08c2b0c9a0a29e39559fb7b2439029aff5725d`. The checkout was outside THREAD source under the ignored `.runtime/competitor-research/` directory. DUET's `eval_submission.py`, harness and nine public scenario files, plus their media, match THREAD's Samsung kit byte for byte across the 17 relevant files checked before this run. No DUET source or scoring rule was edited.

DUET's pinned `requirements.txt` was installed in a separate Python 3.11 virtual environment. On Windows, the documented CUDA 12.8 build of `torch==2.10.0` and `torchvision==0.25.0` was installed from the PyTorch wheel index. The pinned faster-whisper GPU and CPU checkpoints and CLIP checkpoint were fetched; DUET's optional Qwen vision model remained disabled by its default configuration. The host was an RTX 4050 Laptop GPU with 6 GB VRAM. A separate ASR warmup confirmed `device=cuda` and the pinned `dropbox-dash/faster-whisper-large-v3-turbo` model. No THREAD provider key was supplied to the DUET process.

The command below was run from DUET's repository root after clearing provider-key environment variables:

```powershell
.\.venv-duet\Scripts\python.exe eval_submission.py . --time-scale 1 --reps 3 --out results/independent-local-2026-09-24.json
```

Package validation and the agent contract smoke test passed. The untouched evaluator completed 27 attempts and wrote the [per-attempt score report](../benchmarks/duet-public-2026-09-24-3x.json) (SHA-256 `EB013B5DAD4C993A7ABB40DE9DF87C7F4547C714E6DD3CE715A6509B45B69E5B`). Its result **reproduced DUET's headline claim exactly: 97.4 weighted, 97.9 plain, text 100, audio 100, visual 81.5**. Every text attempt and every audio-06 attempt scored 100. Audio-05 scored `53.8, 100, 100`, and visual-07 scored `81.5, 81.5, 81.5`; 23 of 27 attempts scored 100.

This establishes a reproducible public-kit result at that pinned source and configuration. The report contains per-attempt scores but no raw event traces or independent factual transcript review. It does not establish hidden-set performance. THREAD's earlier 94.0 weighted run used the same public kit and repeat count at its own frozen source, but it occurred at another time and uses a hosted provider, so the two samples are informative rather than a simultaneous controlled A/B test.
