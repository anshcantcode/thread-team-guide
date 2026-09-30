# THREAD — historical evidence demonstration

[THREAD_Recorded_Demo.mp4](THREAD_Recorded_Demo.mp4) is a **3:10 edited demonstration of two separate historical sessions**, prepared for ReflexAi, SRM Institute of Science and Technology Kattankulathur. Exact asset identity, source records, edits, narration text and QA are in [the provenance JSON](THREAD_Recorded_Demo.PROVENANCE.json).

| Time | Content |
|---|---|
| 0:00–0:20 | Team and evidence scope |
| 0:20–0:40 | Audio, recognition, planner, controller, tool outcome and received speech |
| 0:40–1:30 | Complete original 50-second benchmark chapter: original input and received reply with a visibly labelled saved-log reconstruction |
| 1:30–1:45 | Same historical call and success receipt |
| 1:45–2:00 | Separate local diagnostics: 61/100 strict tool passes for selected measured source `8dd530f`; 64/100 for experimental `771981a` |
| 2:00–2:50 | Complete original 50-second native extension chapter: original authored synthetic input, real received reply, actual cropped emulator recording and a separate after-restart screenshot |
| 2:50–3:10 | Source boundaries and release reference |

The benchmark chapter is from `20260927T175531Z-6dcc34fa/case-011`, source `088cf6fcfbb33958f631738c808d26cbb0088241`. It records a quantity correction **before dispatch**, followed by one `add_to_cart(product_id="B7", quantity=1)` and its successful mock-tool receipt. Its screen is a report reconstruction, not captured application footage.

The native chapter is from `extension-audio015`, desktop runtime `fecb5c221e2609e39799b87627e1f7327a54da89`, native viewer `8e9324ab74d84c3a77c47e278702a6a066a1bf41`. One actual `add_checklist_item(text="wash the spinach")` writes the item; no celery write is present in the agent call journal. A real read-only emulator viewer shows the saved item and receipt. The final image is a **separate actual after-restart screenshot**, explicitly labelled. Audio/display alignment is approximate. The developer-authored input uses Windows SAPI, and the controller runs on a tethered desktop.

Both complete evidence chapters are retained from the earlier reviewed `VIDEO_DRAFT.mp4` at their original pace, without replacement assistant speech, music, new words, or internal editorial cuts. Their existing source banners, including historical draft markings, remain visible. The container is re-encoded; preservation refers to the chapter contents and pacing, not identical compressed audio/video packets. New narration is local **Windows System.Speech / Microsoft Zira Desktop**, clearly labelled and restricted to context chapters.

The two result cards cite **separate later runs**, not the recordings shown. Both used the local Qwen diagnostic judge and evaluated 100 recordings; neither is an official Samsung score. No benchmark result is transferred to another source revision.

This video does not claim active-speech barge-in, a real purchase, a standalone phone voice agent, or successful execution on current release code. Those claims would need their own actual capture. The three-minute [launch film](https://github.com/anshcantcode/thread-team-guide/releases/download/PRISM_GENAI_HACKATHON_Y2026/THREAD_Launch_Film.mp4) is a separate creative companion, with [its own provenance addendum](THREAD_Launch_Film.PROVENANCE_ADDENDUM.md).

Release reference: https://github.com/anshcantcode/thread-team-guide/releases/tag/PRISM_GENAI_HACKATHON_Y2026

CPU-only assembly used existing local software. No model inference, device action, network request or paid generation was performed. Full human listening/playback remains distinct from the recorded technical and sampled-frame QA.
