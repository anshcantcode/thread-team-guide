# Local Whisper uncertainty decision

## Decision

The four recorded decodes do not justify a numeric confidence cutoff. Pub05 turn 1 has Austin at 0.4751 and does not emit Boston; the weakest destination word in the clear pub06 New York correction is New at 0.6992. A cutoff between those values would only separate these four observations. The word scores are uncalibrated model outputs, and there is one timed warm pass per clip.

A conservative source-local policy can still handle these examples without a fitted cutoff:

- Bind each destination and its evidence to the exact audio segment. If the completed-turn transcript is garbled around the destination, omits or truncates it, or leaves competing destinations live, hold the action and ask the user. Do not use a raw word score as a decision boundary until it has been calibrated.
- Keep a chunk with `end_of_turn: false` provisional. Within that same user turn, apply an explicit self-repair from a later chunk; in a later turn, accept a clear spoken confirmation as resolving the pending destination. Do not act on a provisional or superseded value.

Applied to the recorded examples, this policy flags pub05 turn 1: “I broke off my head to Austin” is garbled around the destination, and Boston was not recognized, so clarify before searching. Pub05 turn 2, “I said Boston,” is a clear explicit confirmation and resolves it. Pub06 part 1, “Book a flight to Boston,” is intelligible but not end-of-turn, so retain it provisionally. Pub06 part 2, “Actually make that New York,” is an intelligible explicit repair at end-of-turn, so New York supersedes Boston. Its 0.6992 score for “New” alone is not enough to label the chunk uncertain.

This is a conservative handling rule, not evidence that a general ASR uncertainty classifier has been validated. Its garbled-transcript judgment is qualitative and should be evaluated before deployment.

## Evidence needed for a numeric rule

Collect repeated, labeled destination spans across speakers, accents, noise levels, city names, and ambiguous pronunciations, including clear confirmations and within-turn repairs. Preserve per-word scores and alternatives from each exact source span. Calibrate a cutoff on a separate calibration set, then report false acceptance and unnecessary clarification rates on a held-out set, with repeated runs and the deployed model version. Include chunk-boundary and explicit-repair cases so turn aggregation is evaluated separately from ASR confidence.

## Source records

- [Recorded four-clip findings](local-whisper-feasibility.md)
- [Public audio05 scenario](../../theme5_kit/participant-kit/participant-kit/scenarios/pub_05_audio_asr_ambiguity.json)
- [Public audio06 scenario](../../theme5_kit/participant-kit/participant-kit/scenarios/pub_06_audio_disfluency.json)
