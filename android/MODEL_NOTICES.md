# Local speech detection

Silero VAD v6.2.1 (MIT license), bundled from the official tagged repository:
https://github.com/snakers4/silero-vad/tree/v6.2.1

Model: `app/src/main/assets/silero_vad_16k.onnx`, 1,289,603 bytes.
SHA-256: `7ed98ddbad84ccac4cd0aeb3099049280713df825c610a8ed34543318f1b2c49`.
License: `app/src/main/assets/SILERO_LICENSE.txt`.
Source: https://raw.githubusercontent.com/snakers4/silero-vad/v6.2.1/src/silero_vad/data/silero_vad_16k_op15.onnx

Inference uses Microsoft's ONNX Runtime Android 1.23.2 (MIT license) from Maven Central. The wrapper follows Silero's documented 512-sample frame, 64-sample context and recurrent-state interface. This model detects speech; it is not a speech recognizer or the voice-generation model. It runs locally on the capture thread and saves no microphone recording.

The Android tests use generated fan/hiss/click/silence signals and a synthetic Windows speech fixture. They are diagnostic coverage, not evidence of universal noise or accent performance.
