# Third-party assets and notices

This document identifies bundled assets and their provenance. Third-party names and marks identify their respective products or sources; their appearance does not imply endorsement.

| Asset | Location | Notice / source |
|---|---|---|
| Silero VAD v6.2.1 | `android/app/src/main/assets/silero_vad_16k.onnx` | MIT; [bundled license](android/app/src/main/assets/SILERO_LICENSE.txt), [model provenance and hash](android/MODEL_NOTICES.md). |
| Manrope | `web/fonts/Manrope.ttf` | [SIL Open Font License](web/fonts/Manrope-OFL.txt); [source manifest](web/fonts/sources.json). |
| Newsreader | `web/fonts/Newsreader.ttf` | [SIL Open Font License](web/fonts/Newsreader-OFL.txt); [source manifest](web/fonts/sources.json). |
| Android/Gradle wrapper | `android/gradle/`, `android/gradlew*` | Gradle wrapper files retain their upstream notices. |
| Voice acknowledgments | `web/sounds/` and Android assets | Generated Gemini voices; [voice manifest](web/sounds/sources.json). No personal voice clone. |
| Evaluation speech | `evaluation/audio/`, `evaluation/native-audio/` | Synthetic speech; provenance manifests accompany each fixture set. |
| Android speech test fixture | `android/app/src/androidTest/assets/speech-fixture.pcm` | Synthetic test input; see [model notices](android/MODEL_NOTICES.md). |
| THREAD sphere and design boards | `web/images/`, Android drawable, `design/` | Generated project imagery. Reference boards are design intent, not proof of implemented UI. |
| Film location/cat illustrations | `motion/v2/assets/` | Generated illustrations; [film asset provenance](motion/v2/ASSETS.md). |
| Airline marks, athlete portrait, astronomical image | `motion/v2/assets/` | Individual source links and EHT Collaboration credit in [film asset provenance](motion/v2/ASSETS.md). No blanket project license is granted over these assets. |
| Public-provider result captures | Android test assets and film data | Dated test/presentation snapshots with source fields; not a live data feed. |

Runtime dependencies are declared in the Python lockfiles and Android Gradle files. Their upstream licenses apply separately. This repository does not currently declare a project-wide redistribution license.
