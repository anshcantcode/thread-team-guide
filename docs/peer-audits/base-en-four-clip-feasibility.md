# base.en CPU feasibility: four public Samsung audio clips

## Scope

This read-only ASR check used only the four public audio05/audio06 MP3s listed below. It did not modify source, use provider credentials, or download a model. The cache was the local `Systran/faster-whisper-base.en` snapshot `3d3d5dee26484f91867d81cb899cfcf72b96be6c` under `C:\Users\ANSH\Documents\samsung voice interupt model\.runtime\whisper`.

The semantic targets below come from the two public scenario files. They were consulted as labels only; the model received only each MP3.

## Run

Used an isolated temporary CPython 3.11.9 environment on Windows 10 x64 with `faster-whisper==1.2.1` and `ctranslate2==4.8.2`, matching the repo's local lock. The environment was created at `%TEMP%\codex-samsung-whisper-baseen-audit-py311-20260924`.

The model was loaded once with `HF_HUB_OFFLINE=1` and `local_files_only=True`. Load time was **0.8101 s**. Settings match [thread_agent/asr.py](../../thread_agent/asr.py): `base.en`, CPU, int8, four CPU threads, English, beam size 3, VAD on, previous-text conditioning off, and the worker's `avg_logprob < -1.2` rejection filter.

After one unmeasured warm-up decode of `pub_05_turn1` (**2.6671 s**), one decode per clip was timed from the transcribe call through consuming all segments. Times include MP3 reading and the worker's base64 round trip. The first clip therefore appears once as warm-up and once as its timed decode.

## Results

| Clip | Scenario target | Verbatim worker transcript | Decode | Target / repair result |
| --- | --- | --- | ---: | --- |
| `pub_05_turn1.mp3` (1.4 s) | Boston (ambiguous with Austin) | “I woke up and I took a second.” | 2.7783 s | **Failed.** Neither candidate city nor the booking phrase survived. |
| `pub_05_turn2.mp3` (0.9 s) | Boston confirmation | “I said Boston.” | 0.6734 s | **Survived.** Boston and the explicit “I said” confirmation survived. |
| `pub_06_turn1_part1.mp3` (1.2 s) | Initial Boston destination | “book applied to Boston.” | 0.7320 s | **Partial.** Boston survived; “book a flight” was misrecognized. |
| `pub_06_turn1_part2.mp3` (1.1 s) | Explicit repair to New York | “Actually make that New York.” | 0.7342 s | **Survived.** New York and the explicit repair wording survived. |

## Readout and limits

The base.en model retained the public audio06 destination change in its correction chunk and the audio05 confirmation, but it failed on the ambiguous audio05 first turn. That first timed decode also took about twice the clip duration; the other three one-off decodes were shorter than their clip durations. These four clips are a feasibility check, not a reliability or stable latency benchmark.

The timing loop reused one loaded model to isolate decode cost. The current worker constructs `WhisperModel` inside `transcribe()`, so its load cost is repeated when that function is invoked for separate clips. This is an ASR-only check; it does not measure chunk aggregation, clarification behavior, or end-to-end response time. The earlier [large-v3-turbo GPU check](local-whisper-feasibility.md) is not a controlled speed comparison because its model, device, and decode settings differ.
