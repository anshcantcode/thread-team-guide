# Dependency and model provenance

This migration does not bundle provider credentials, benchmark recordings, model
weights, LiveKit binaries or competitor repositories in Git. Their local hashes
and provenance belong to run evidence; preserve upstream notices when preparing
a distributable artifact.

- FDB-v3 public tools and evaluators: pinned Full-Duplex-Bench commit
  `3e799c45a045256f47d5f1c9cda90157e2d2ec9e`. Exact source copies are retained in
  ignored runtime/evidence directories; upstream semantics were not rewritten.
- Python dependency versions: `requirements-fdb3.lock`. Existing Android
  dependency/configuration files remain in place; the APK build used their
  configured repositories and includes its declared third-party dependencies.
- LiveKit server 1.13.7: downloaded from its official release; archive SHA256
  `e539e7d2f75807b9c9202cd2a0bf2cb3d52fc4c52978a6953e0f47bc339fe77f`.
- Existing Qwen GGUF assets were used read-only. This migration has not established
  the original quantizer's complete distribution/license provenance; resolve that
  before bundling weights. Model names alone are not a license review.
- The optional [Systran faster-whisper-small.en conversion](https://huggingface.co/Systran/faster-whisper-small.en)
  is identified as MIT on its model card. Downloaded revision
  `d1d751a5f8271d482d14ca55d9e2deeebbae577f`; model SHA256
  `62b2a45b05ee59acb4a5341b33ee35e041395d378d418a18acfe4c9e768ee37a`.
  Download does not establish performance; controlled comparison is pending.
- Microsoft David Desktop SAPI is an installed Windows component. The current
  speech route is not portable to the organizer's Linux environment.

This is a provenance record, not a completed release-license clearance. No
third-party implementation was copied from the competitor audit. Public access
alone was not treated as permission to reuse competitor code.
