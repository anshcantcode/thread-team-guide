import json
import time
import unittest
from unittest.mock import AsyncMock

from thread_agent.engine import Session
from thread_agent.live import LiveConversation


class Browser:
    def __init__(self):self.events=[]
    async def send_json(self,event):self.events.append(event)


class NoiseRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.session=Session(None,date='2026-09-13')
        self.browser=Browser();self.live=LiveConversation(self.session,self.browser)
        self.live.input_epoch=1;self.live.last_audio_id='reply'
        self.session.transcript.append({'id':'reply','role':'assistant','text':'The first thing to consider is the date.','source':'native_audio'})
        self.live.begin_barge();self.live.barge['created']=time.monotonic()-2
        self.live.last_speech_end=time.monotonic()-2
        self.live.send_text_turn=AsyncMock()

    async def asyncTearDown(self):await self.session.close()

    async def test_completed_reply_resumes_without_regeneration(self):
        self.live.completed_audio.add('reply')
        self.live.barge['interrupted']=True
        await self.live.recover_noise('reply')
        self.assertEqual(self.browser.events[-1],{'type':'resume_after_noise','message_id':'reply','continue_needed':False})
        self.live.send_text_turn.assert_not_awaited()

    async def test_partial_reply_continues_exactly_once(self):
        self.live.barge['interrupted']=True
        await self.live.recover_noise('reply')
        self.assertTrue(self.browser.events[-1]['continue_needed'])
        await self.live.recover_noise('reply',continuation=True)
        await self.live.recover_noise('reply',continuation=True)
        self.live.send_text_turn.assert_awaited_once()
        self.assertIn('The first thing to consider is the date.',self.live.send_text_turn.call_args.args[0])
        self.assertEqual(self.browser.events[-1]['type'],'resume_denied')

    async def test_actual_words_prevent_false_resume(self):
        await self.live.caption('user','No, stop.')
        await self.live.recover_noise('reply')
        self.assertEqual(self.browser.events[-1]['type'],'resume_denied')

    async def test_no_speech_markers_are_not_words(self):
        await self.live.caption('user','[noise]')
        self.assertFalse(self.live.barge['words'])

    async def test_revision_change_cannot_resume_stale_answer(self):
        self.session.revision+=1
        await self.live.recover_noise('reply')
        self.assertEqual(self.browser.events[-1]['type'],'resume_denied')

    async def test_new_input_epoch_cannot_resume_old_answer(self):
        self.live.input_epoch+=1
        await self.live.recover_noise('reply')
        self.assertEqual(self.browser.events[-1]['type'],'resume_denied')

    async def test_active_speaker_is_never_talked_over(self):
        self.live.user_speaking=True
        await self.live.recover_noise('reply')
        self.assertEqual(self.browser.events[-1]['type'],'resume_denied')

    async def test_explicit_silence_and_pause_block_recovery(self):
        for field in ['speech_muted','paused','ended']:
            with self.subTest(field=field):
                setattr(self.session,field,True)
                await self.live.recover_noise('reply')
                self.assertEqual(self.browser.events[-1]['type'],'resume_denied')
                setattr(self.session,field,False)

    async def test_different_generation_in_progress_defers_instead_of_overlapping(self):
        self.live.response_started=True
        self.live.last_audio_id='newer-reply'
        await self.live.recover_noise('reply')
        self.assertEqual(self.browser.events[-1]['type'],'resume_deferred')
        self.assertIsNotNone(self.live.barge)

    async def test_same_generation_can_resume_while_its_audio_still_streams(self):
        self.live.response_started=True;self.live.block_old_calls=True
        await self.live.recover_noise('reply')
        self.assertEqual(self.browser.events[-1]['type'],'resume_after_noise')
        self.assertFalse(self.live.block_old_calls)
        self.live.send_text_turn.assert_not_awaited()

    async def test_recovery_keeps_transcription_of_audio_received_during_pause(self):
        self.live.caption_ids['assistant']='reply'
        await self.live.caption('assistant',' Then consider the time.')
        self.assertTrue(self.live.barge['text'].endswith(' Then consider the time.'))

    async def test_noise_recovery_cannot_execute_functions(self):
        self.live.barge['interrupted']=True
        await self.live.recover_noise('reply')
        result=self.live.apply_tool({'id':'unsafe-recovery','name':'lookup_calculate','args':{'expression':'2+2','base_revision':0}})
        self.assertFalse(result['ok']);self.assertIn('Playback recovery',result['error'])
        await self.live.caption('user','Calculate two plus two.')
        self.assertFalse(self.live.recovery_only)

    async def test_resume_id_must_match_server_message(self):
        await self.live.recover_noise('invented')
        self.assertEqual(self.browser.events[-1]['type'],'resume_denied')

    async def test_short_noise_cannot_unmute_explicit_speech_stop(self):
        self.session.speech_muted=True
        await self.live.caption('user','[cough]')
        self.assertTrue(self.session.speech_muted)
