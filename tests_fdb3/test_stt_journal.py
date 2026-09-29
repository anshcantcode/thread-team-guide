import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from thread_agent.fdb3_voice import WhisperSTT, SapiTTS, SapiStream


class RecognitionJournalTests(unittest.TestCase):
    def test_word_alignment_uses_the_same_durable_recognition_attempt(self):
        with tempfile.TemporaryDirectory() as directory,patch('faster_whisper.WhisperModel'):
            recognizer=WhisperSTT('independent-fixture')
            recognizer.transcription_journal=Path(directory)/'stt.jsonl'
            recognizer.whisper.transcribe.return_value=([SimpleNamespace(text=' Willow',start=.2,end=4.0,
                words=[SimpleNamespace(word=' Willow',start=.2,end=.7)])],None)
            text,chunks=recognizer.transcribe('independent.wav',filter_silence=True,word_timestamps=True)
            self.assertEqual(text,'Willow')
            self.assertEqual(chunks[0]['words'],[{'text':' Willow','timestamp':[.2,.7]}])
            self.assertTrue(recognizer.whisper.transcribe.call_args.kwargs['word_timestamps'])
            rows=[json.loads(line) for line in recognizer.transcription_journal.read_text().splitlines()]
            self.assertTrue(all(row['word_timestamps'] for row in rows))
            self.assertEqual(rows[0]['request_id'],rows[-1]['request_id'])
            self.assertEqual(len(recognizer.attempts),1)

    def test_pending_request_is_durable_before_decoder_and_failure_is_retained(self):
        with tempfile.TemporaryDirectory() as directory,patch('faster_whisper.WhisperModel'):
            recognizer=WhisperSTT('independent-fixture')
            recognizer.transcription_journal=Path(directory)/'stt.jsonl'
            def fail(*args,**kwargs):
                row=json.loads(recognizer.transcription_journal.read_text().splitlines()[-1])
                self.assertEqual(row['outcome'],'pending')
                raise RuntimeError('authored decoder failure')
            recognizer.whisper.transcribe.side_effect=fail
            with self.assertRaisesRegex(RuntimeError,'authored'):
                recognizer.transcribe('independent.wav',filter_silence=True)
            rows=[json.loads(line) for line in recognizer.transcription_journal.read_text().splitlines()]
            self.assertEqual(rows[-1]['outcome'],'error')
            self.assertEqual(rows[-1]['request_id'],rows[0]['request_id'])
            self.assertEqual(len(recognizer.attempts),1)

    def test_actual_decode_text_is_recorded_without_changing_transcription(self):
        with tempfile.TemporaryDirectory() as directory,patch('faster_whisper.WhisperModel'):
            recognizer=WhisperSTT('independent-fixture')
            recognizer.transcription_journal=Path(directory)/'stt.jsonl'
            recognizer.whisper.transcribe.return_value=([SimpleNamespace(text=' Elm',start=.2,end=.8)],None)
            text,chunks=recognizer.transcribe('independent.wav')
            self.assertEqual(text,'Elm')
            row=json.loads(recognizer.transcription_journal.read_text().splitlines()[-1])
            self.assertEqual(row['chunks'],chunks)
            self.assertEqual(row['outcome'],'success')


class SynthesisJournalTests(unittest.IsolatedAsyncioTestCase):
    async def test_synthesis_pending_precedes_work_and_failure_remains_on_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            synthesizer=SapiTTS()
            synthesizer.synthesis_journal=Path(directory)/'tts.jsonl'
            stream=object.__new__(SapiStream)
            stream._tts=synthesizer
            stream._input_text='Independent authored speech'
            async def fail(emitter):
                row=json.loads(synthesizer.synthesis_journal.read_text().splitlines()[-1])
                self.assertEqual(row['outcome'],'pending')
                raise RuntimeError('authored synthesis failure')
            with patch.object(stream,'_speak',side_effect=fail):
                with self.assertRaisesRegex(RuntimeError,'authored'):
                    await stream._run(None)
            rows=[json.loads(x) for x in synthesizer.synthesis_journal.read_text().splitlines()]
            self.assertEqual(rows[-1]['outcome'],'error')
            self.assertEqual(rows[0]['request_id'],rows[-1]['request_id'])
