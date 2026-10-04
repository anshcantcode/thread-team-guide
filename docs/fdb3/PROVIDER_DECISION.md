# Observed local route, not a final provider selection

**Historical development profiles.** The CPU/base.en/2B/4B experiments below are not the selected small.en/CUDA/seed-42 candidate. See [current reproduction configuration](REPRODUCE.md) and [the final-source results](../submission/RESULTS.md). “Current” below describes the dated experiment only.

The owner authorized INR 0 on 2026-09-25. No configured key was treated as spending
permission. The current usable diagnostic route is local Whisper base.en (CPU
int8), existing Qwen3.5 Q4_K_M models through llama.cpp, Microsoft David Desktop SAPI,
and loopback LiveKit 1.13.7. These use installed/downloaded local assets, not
provider inference, hosted speech or cloud LiveKit. The original environments and
credentials were not changed.

Observed experiments, including failures:

| Experiment | Observation | Limit |
|---|---|---|
| Local 4B, manual first slice | Real speech/tool/output; argument spelling error | One recording, no provider ranking |
| Local 4B, automatic file slice | One valid local judged pass | Partial, caching observed in early judge; not qualification |
| Independent 4B planner probes | Invalid decision format and timeouts retained | Different developer fixtures/configurations |
| Local 2B, smaller context/batch | Two independent identifier probes passed | Text probes, not held-out audio or complete dataset |
| Early 2B real room slice | Real WebRTC, tool and captured speech | Judge malformed; zero valid judged passes |
| Native JSON-schema judge controls | Independently authored positive and negative controls both correct | Local Qwen, not organizer judge |
| Full room batch 001 | Aborted after judge failures | No valid all-pass claim; raw fallback booleans retained |
| Full room batch002 | All100 attempted:33 valid local strict passes,13 infrastructure,47 tool-selection and7 argument/response failures | Frozen older2B planner; default instant profile with unchanged per-API latency overrides; local diagnostic only |
| Repaired native2B room slice |1/1 valid local strict pass with diagnostic latency | Predates later mechanism repairs; not complete validation |
| Native4B independent literal/reported/replacement probes001 |2/3passed; full imperative copied into text argument | Controlled memory tools; no audio or benchmark content |
| Same4B probes002 with generic prompt reminder |Same2/3 result; redundant reminder removed | Failed improvement preserved; not a qualifying run |

The installed llama.cpp chat endpoint failed JSON response-format controls.
Native `/apply-template` plus `/completion` with JSON schema succeeded for the
judge controls. The planner now uses this protocol, with descriptor-based step
schemas and optional current-index citations. A fresh room slice passed; complete
current-source validation remains pending. The existing4B model is now under test
with the same CPU/context settings; the prior2B service identity is retained.
No post-generation JSON repair or answer substitution is used.

Current local model service: CPU only, four threads, context 4096, parallelism 1,
batch 128, microbatch 64, cache RAM 0, reasoning off, skip chat parsing enabled.
Sampling temperature 0 is not a promise of deterministic generation. The actual
binary, model, arguments, source snapshot and returned usage belong in each run's
identity/evidence. Model service identity is stored locally without credentials.

Host memory pressure and competing GPU workloads were observed. They are not
proof of the cause of every timeout. No unrelated owner process was stopped.
Published provider scores, old Gemini results, and this different local route are
not controlled comparisons. A final provider decision requires matching test
conditions, authorized finite resources, full audio coverage and meaningful
latency measurements. The current route is retained to make progress at zero spend.
