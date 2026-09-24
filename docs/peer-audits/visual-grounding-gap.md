# pub_07 visual grounding trace

Reviewed at base `09f91640dd833cab7efaa387cd52847260802c35`.

## Finding

No general image/frame referent-binding defect was demonstrated, so no runtime change is justified. The checked-in evidence records one bounded successful `pub_07` run, but does not include its raw provider trace; the exact native observation and returned result cannot be replayed offline from this checkout.

## Trace

- `pub_07_visual_port_lookup.json` supplies `frames/pub_07_f017.png` at event 0 and the question at event 1. An offline `MediaLoader.prepare()` check attached one PNG at message index 0; its decoded inline bytes exactly matched the source file (675,326 bytes; SHA-256 `52620CB1296765D663D7CDA409E4C5181E561BD301EDD4EF542675175E5F4B9E`).
- `ParticipantAgent` records the appended frame index and passes it as `latest_frame_index`. `Planner._validate()` requires each observation to match attached media and only accepts a conditional printed-text target when its subject is the selected literal label from that current frame. Such a lookup must be terminal and read-only.
- Optional image embedding uses the same inline image part. The planner attaches the returned vector only when its input hash matches the media source hash and the supplied tool schema accepts an embedding.
- Result rendering requires the cited result path to appear in the template and the actual returned value at that path to contain the cited subject. The separate ordinary-purpose phrase also rechecks the current frame's selected label.
- The selected-run evidence reports a native HDMI label selection with the referent left ambiguous, a returned manual reference (`GENERIC-laptop-manual`, page 27, “HDMI Output”), and a conditional final. It explicitly says neighboring visual observations were not independently corroborated. See `docs/submission-2026-09-23/DEMO_EVIDENCE_CHECKLIST.md` and `docs/submission-2026-09-23/ENGINEERING_UPDATE.md`.

## Offline checks

- Exact `pub_07` source bytes through `MediaLoader.prepare()`: passed.
- `python -m unittest tests.test_participant_visual_recognition tests.test_participant_media tests.test_participant_embedding`: 27 passed.
- Nine focused planner, embedding, citation, and rendering tests: passed. The provider replies in those tests are constructed protocol fixtures, not image-recognition evidence.

No failure was reproduced. Without the raw native trace, the code contract can be checked offline, but the original provider's image observation and result binding cannot be replayed or independently re-evaluated.
