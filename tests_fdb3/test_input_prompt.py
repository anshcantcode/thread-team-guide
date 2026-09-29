"""The contract-vocabulary ASR prompt reaches user input recognition only."""
import asyncio
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from livekit import rtc

from thread_agent.fdb3_voice import WhisperSTT, input_prompt


class InputPromptTests(unittest.TestCase):
    def recognizer(self, prompt):
        with patch("faster_whisper.WhisperModel"):
            recognizer = WhisperSTT("independent-fixture", prompt=prompt)
        recognizer.whisper.transcribe.return_value = ([SimpleNamespace(text=" gold card", start=0.0, end=1.0)], None)
        return recognizer

    def test_input_path_uses_the_prompt_and_output_asr_does_not(self):
        recognizer = self.recognizer("track order, gold.")
        frame = rtc.AudioFrame(data=b"\x00\x00" * 1600, sample_rate=16000, num_channels=1, samples_per_channel=1600)
        asyncio.run(recognizer._recognize_audio([frame]))
        self.assertEqual(recognizer.whisper.transcribe.call_args.kwargs["initial_prompt"], "track order, gold.")
        recognizer.transcribe("spoken-output.wav", filter_silence=True)  # evaluator output ASR
        self.assertIsNone(recognizer.whisper.transcribe.call_args.kwargs["initial_prompt"])

    def test_prompt_is_opt_in_and_contract_only(self):
        saved = os.environ.pop("THREAD_FDB3_WHISPER_PROMPT", None)
        try:
            self.assertIsNone(input_prompt("unused"))
            os.environ["THREAD_FDB3_WHISPER_PROMPT"] = "contract"
            fake = {"track_order": {"args": {"order_id": {"description": "Order identifier to track, e.g. 'BOB12'"}}},
                    "get_card_benefits": {"args": {"card_type": {"description": "The card type, e.g. 'platinum' or 'gold'"}}}}
            with patch("thread_agent.fdb3.load_contract", return_value=fake):
                self.assertEqual(input_prompt("contract-dir"), "track order, BOB12, get card benefits, platinum, gold.")
        finally:
            os.environ.pop("THREAD_FDB3_WHISPER_PROMPT", None)
            if saved is not None:
                os.environ["THREAD_FDB3_WHISPER_PROMPT"] = saved


if __name__ == "__main__":
    unittest.main()
