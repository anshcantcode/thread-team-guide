# Samsung provider route comparison

Checked 24 September 2026. The experiment uses the reviewed checkpoint `f45f0b1`, the nine **public** participant-kit scenarios, the kit's `EvaluationHarness` and `score_scenario`, real-time replay, a 4.5-second planning limit and the participant's 3.5-second acoustic limit. It does not use private expectations or modify the submission. Results are local experiments, not a judge score or a guarantee for hidden cases.

## Measured routes

| Route and model | Cases run | Result | Interpretation |
|---|---:|---:|---|
| Gemini API, `gemini-3.5-flash-lite`, minimal thinking | 9 public cases × 2 | 86.5 weighted, median of two per case | Best complete route measured here. Five planner/acoustic calls hit local timeouts. Text was mostly stable; audio and visual varied. |
| Gemini API, `gemini-3.1-flash-lite`, minimal thinking | Focused audio × 2, visual × 1, unseen tool × 1 | 66.4 weighted over those four cases | One visual HTTP 503 and repeated audio timeouts. One pass, so no reliable quality ranking. |
| Gemini API, `gemini-3.8-flash`, low thinking | Focused audio, visual, unseen tool | 39.5 weighted over those three cases | All three calls returned HTTP 503. This measures current availability, not model quality. |

The complete Gemini 3.5 Flash-Lite run scored 100 in both repeats on public text cases 01–04 and 08. Case 09 scored 100 then 76.9 despite two on-time model responses. Audio case 05 scored 60.8 then 100; audio case 06 scored 56.9 twice; visual case 07 scored 47.7 then 100. The detailed redacted timings are in `.runtime/provider-benchmark/gemini-public-2x.json` (local, ignored by Git). A one-off 100 on audio or visual should not be used as evidence of repeatability.

The first Groq `qwen/qwen3.8-27b` call for public case 09 returned in 594 ms, but the participant rejected the JSON decision and the case scored 47.7. A follow-up request received HTTP 429; the next recorded `retry-after` was 561 seconds. Thus, Groq's raw speed is promising, but its current account quota and output acceptance do not yet support a full route comparison. A JSON Schema probe is queued after the stated cooldown. The earlier 47.7 result used JSON object mode.

## Routes prepared, awaiting credentials

| Route | Fit | Constraint before a valid head-to-head |
|---|---|---|
| [Groq Qwen3.8 27B](https://console.groq.com/docs/model/qwen/qwen3.8-27b) + [Whisper Large V3 Turbo](https://console.groq.com/docs/speech-to-text) | Qwen handles text/image planning; Whisper transcribes audio. Free tier lists 30 RPM / 8K TPM for Qwen and 20 RPM for Whisper. | The experiment reads `THREAD_GROQ_API_KEY` or `GROQ_API_KEY`. The adapter uses JSON object mode, not Gemini's schema enforcement, and splits audio into ASR plus planning. Compare score, latency, invalid JSON, and uncertain speech before considering production. |
| [Alibaba Model Studio Singapore Qwen3.8 Flash](https://www.alibabacloud.com/help/en/model-studio/model-pricing) | Introductory 1M-token free quota for Flash; Qwen3-ASR-Flash has 10 hours, each valid 90 days subject to account eligibility. | Needs `DASHSCOPE_API_KEY` and the Singapore workspace `DASHSCOPE_BASE_URL`. The current adapter covers text/image only; audio must wait for a validated ASR path. Enable **Free Quota Only** to prevent paid overage. A key alone cannot validate all nine cases. |
| [Cloudflare Workers AI](https://developers.cloudflare.com/workers-ai/platform/pricing/) Qwen3.8 27B + Whisper | 10,000 neurons/day free; possible hosted fallback. | Requires account credentials. Neuron budget and latency for two full 27-attempt batches are unmeasured, so it is a backup candidate. |
| [OpenRouter Qwen3.8 27B](https://openrouter.ai/qwen/qwen3.8-27b) | Multiple upstream providers can improve availability. | Router fallback can add latency; free-tier request allowance is too small for repeated full qualification without verification. |

## Paid Gemini decision

Paying for **standard** Gemini raises rate limits but does not demonstrate a faster individual response. [Priority inference](https://ai.google.dev/gemini-api/docs/priority-inference) claims lower latency and higher reliability and currently runs through the Interactions API. For 3.5 Flash-Lite, [published pricing](https://ai.google.dev/gemini-api/docs/pricing) is $0.54 per 1M input tokens and $4.50 per 1M output tokens at Priority, versus $0.30 and $2.50 at paid Standard. The participant uses `generateContent`, so a Priority comparison needs a separate adapter and a small capped paid trial. Billing alone must not be treated as a fix for these 3.5-/4.5-second deadlines. See [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits).

## Decision gate

Run the same frozen participant with Groq on one text, one audio and the visual case first. If requests complete and the controller accepts the outputs, run all nine public cases three times using the kit's official package evaluator, then a second independent repeat. Compare weighted score, per-case minima, p95 provider time, invalid output, 429/503, and audio uncertainty. Move a route into the submission only after it matches or improves the incumbent and the complete offline safety suite still passes. Hidden tests remain unknown.

The probe is `scripts/provider_route_probe.py`. It reads local credentials using `--env-file`, redacts prompts and credentials from reports, and has an offline route-boundary check in `tests/test_provider_route_probe.py`. For example:

```powershell
python scripts/provider_route_probe.py --route groq --env-file 'C:\path\to\.env' --cases pub_09_text_unseen_tool --out '.runtime\provider-benchmark\groq-smoke.json'
```
