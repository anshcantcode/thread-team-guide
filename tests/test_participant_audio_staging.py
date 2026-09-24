"""Offline source/epoch/cancellation tests for completed-turn acoustic perception."""
import asyncio
import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from participant.agent import ParticipantAgent
from participant.planner import ACOUSTIC_SYSTEM, Planner, PlannerError


FIXTURES = Path(__file__).parent / 'fixtures/mp3'
CLIPS = [(FIXTURES / name).read_bytes() for name in ('tone-cbr.mp3', 'tone-vbr.mp3')]


def response(body, *, uncertain=False, conflict=False, changed_index=None):
    acoustic = 'perception only' in body['systemInstruction']['parts'][0]['text']
    variants = body['generationConfig']['responseJsonSchema']['properties']['observations']['items']['anyOf']
    observations = []
    for variant in variants:
        index = variant['properties']['message_index']['enum'][0]
        changed = changed_index is None or index == changed_index
        observations.append({'message_index': index, 'type': 'audio',
            'transcript': f'Find option {index}' + ('' if conflict and changed else '.'),
            'uncertain': uncertain and changed})
    decision = {'observations': observations}
    if not acoustic:
        decision.update(intent='find', slots={}, tool_calls=[{'api_name': 'lookup', 'args': {}}],
                        response=None, clarification=None)
    return httpx.Response(200, json={'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': json.dumps(decision)}]}}]})


class AudioStagingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        for index, raw in enumerate(CLIPS):
            (self.root / f'{index}.mp3').write_bytes(raw)
        env = patch.dict(os.environ, {'SECRET_GEMINI_API_KEY': 'offline-only',
                        'PARTICIPANT_MEDIA_ROOT': str(self.root), 'PARTICIPANT_PREWARM': '0'}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.messages = [{'message_index': index, 'revision': 1, 'event_type': 'user_audio_chunk',
                          'payload': {'audio_ref': f'{index}.mp3', 'end_of_turn': index == 1}} for index in range(2)]
        self.requests = []

    async def planner(self, handler=None):
        async def capture(request):
            body = json.loads(request.content)
            self.requests.append(body)
            return await handler(body) if handler else response(body)
        planner = Planner(transport=httpx.MockTransport(capture))
        self.addAsyncCleanup(planner.close)
        await planner.setup()
        return planner

    def context(self, **updates):
        return {'messages': deepcopy(self.messages), 'revision': 1, 'current_turn_start': 0,
                'tools': {'lookup': {'kind': 'read_only', 'args': {}}}, **updates}

    @staticmethod
    def acoustic(body):
        return 'perception only' in body['systemInstruction']['parts'][0]['text']

    @staticmethod
    def targets(body):
        return [variant['properties']['message_index']['enum'][0] for variant in
                body['generationConfig']['responseJsonSchema']['properties']['observations']['items']['anyOf']]

    @staticmethod
    def clips(body):
        return [base64.b64decode(part['inlineData']['data']) for part in body['contents'][0]['parts'] if 'inlineData' in part]

    async def test_completed_turn_starts_two_parallel_passes_over_all_ordered_bytes(self):
        started = {False: asyncio.Event(), True: asyncio.Event()}
        release = asyncio.Event()
        async def handle(body):
            started[self.acoustic(body)].set()
            await release.wait()
            return response(body)
        planner = await self.planner(handle)
        planner.observe_input(self.messages[0], 0)
        extra = deepcopy(self.messages[1])
        extra['payload']['end_of_turn'] = False
        planner.observe_input(extra, 0)
        await asyncio.sleep(.02)
        self.assertEqual(self.requests, [])
        self.assertEqual(planner._audio_jobs, {})
        self.assertEqual(planner._audio_cache, {})
        planner.observe_input(self.messages[1], 0)
        task = asyncio.create_task(planner.plan(self.context()))
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started.values())), .5)
        self.assertFalse(task.done())
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(set(planner._audio_jobs), {'turn'})
        for body in self.requests:
            self.assertEqual(self.clips(body), CLIPS)
            self.assertEqual(self.targets(body), [0, 1])
        acoustic = next(body for body in self.requests if self.acoustic(body))
        self.assertEqual(acoustic['systemInstruction'], {'parts': [{'text': ACOUSTIC_SYSTEM}]})
        self.assertEqual(len(acoustic['contents'][0]['parts']), 4)
        release.set()
        result = await asyncio.wait_for(task, .5)
        self.assertTrue(result['tool_calls'])
        self.assertEqual([key[:2] for key in planner._audio_jobs['turn']['keys']], [(0, 1), (1, 1)])
        record = next(row for row in planner.evidence if row['phase'] == 'acoustic')
        self.assertEqual([row['message_index'] for row in record['input_media']], [0, 1])
        self.assertEqual([row['message_index'] for row in result['observations']], [0, 1])
        self.assertEqual({key[0] for key in planner._audio_cache}, {0, 1})

    async def test_three_clip_turn_requires_all_targets_in_one_acoustic_pass(self):
        (self.root / '2.mp3').write_bytes(CLIPS[0])
        messages = deepcopy(self.messages)
        messages[1]['payload']['end_of_turn'] = False
        third = deepcopy(messages[0])
        third['message_index'] = 2
        third['payload'] = {'audio_ref': '2.mp3', 'end_of_turn': True}
        messages.append(third)
        planner = await self.planner()
        planner.observe_input(messages[0], 0)
        result = await planner.plan(self.context(messages=messages))
        self.assertTrue(result['tool_calls'])
        self.assertEqual(len(self.requests), 2)
        for body in self.requests:
            self.assertEqual(self.targets(body), [0, 1, 2])
            self.assertEqual(self.clips(body), [*CLIPS, CLIPS[0]])
        self.assertEqual([row['message_index'] for row in result['observations']], [0, 1, 2])

    async def test_full_context_never_verifies_missing_duplicate_or_extra_targets(self):
        for fault in ('missing_first', 'missing_second', 'duplicate', 'unknown', 'boolean'):
            with self.subTest(fault=fault):
                async def handle(body):
                    reply = response(body)
                    if self.acoustic(body):
                        payload = reply.json()
                        output = json.loads(payload['candidates'][0]['content']['parts'][0]['text'])
                        rows = output['observations']
                        if fault.startswith('missing'):
                            rows.pop(0 if fault == 'missing_first' else 1)
                        elif fault == 'duplicate':
                            rows[1] = dict(rows[0])
                        elif fault == 'unknown':
                            rows.append({**rows[0], 'message_index': 2})
                        else:
                            rows[0]['message_index'] = False
                        payload['candidates'][0]['content']['parts'][0]['text'] = json.dumps(output)
                        return httpx.Response(200, json=payload)
                    return reply
                planner = await self.planner(handle)
                planner.observe_input(self.messages[0], 0)
                result = await planner.plan(self.context())
                self.assertTrue(result['clarification'])
                self.assertEqual(result['tool_calls'], [])
                self.assertEqual(planner._audio_cache, {})
                self.assertTrue(planner._audio_stopped)
                await planner.close()
                self.assertEqual(planner._pending_tasks, set())

    async def test_inflight_change_to_either_clip_cancels_without_an_acoustic_replay(self):
        for index in (0, 1):
            with self.subTest(index=index):
                for i, raw in enumerate(CLIPS):
                    (self.root / f'{i}.mp3').write_bytes(raw)
                self.requests.clear()
                arrived, cancelled = asyncio.Event(), asyncio.Event()
                async def handle(body):
                    if self.acoustic(body):
                        arrived.set()
                        try:
                            await asyncio.Future()
                        except asyncio.CancelledError:
                            cancelled.set()
                            return response(body)
                    return response(body)
                planner = await self.planner(handle)
                planner.observe_input(self.messages[0], 0)
                first = asyncio.create_task(planner.plan(self.context()))
                await asyncio.wait_for(arrived.wait(), .5)
                original = planner._audio_jobs['turn']
                keys = original['keys']
                first.cancel()
                await asyncio.gather(first, return_exceptions=True)
                (self.root / f'{index}.mp3').write_bytes(CLIPS[1 - index])
                result = await planner.plan(self.context(revision=2))
                await asyncio.wait_for(cancelled.wait(), .5)
                self.assertTrue(result['clarification'])
                self.assertEqual(result['tool_calls'], [])
                self.assertEqual(original['keys'], keys)
                self.assertEqual(sum(self.acoustic(body) for body in self.requests), 1)
                self.assertEqual(planner._audio_cache, {})
                await planner.close()
                self.assertEqual(planner._audio_jobs, {})
                self.assertEqual(planner._pending_tasks, set())

    async def test_whole_job_source_identity_is_checked_on_rejoin_and_completion(self):
        for rejoin in (False, True):
            with self.subTest(rejoin=rejoin):
                arrived, release = asyncio.Event(), asyncio.Event()
                async def handle(body):
                    if self.acoustic(body):
                        arrived.set()
                        await release.wait()
                    return response(body)
                planner = await self.planner(handle)
                planner.observe_input(self.messages[0], 0)
                first = asyncio.create_task(planner.plan(self.context()))
                await asyncio.wait_for(arrived.wait(), .5)
                # Every attached clip is a target; one key tuple binds both roles.
                planner._audio_jobs['turn']['keys'] = planner._audio_jobs['turn']['keys'][:1]
                if rejoin:
                    first.cancel()
                    await asyncio.gather(first, return_exceptions=True)
                    result = await planner.plan(self.context(revision=2))
                else:
                    release.set()
                    result = await asyncio.wait_for(first, .5)
                self.assertTrue(result['clarification'])
                self.assertEqual(result['tool_calls'], [])
                self.assertEqual(planner._audio_cache, {})
                await planner.close()
                self.assertEqual(planner._pending_tasks, set())

    async def test_acoustic_first_uncertainty_in_either_clip_cannot_cache_clear_unmatched_words(self):
        for index in (0, 1):
            with self.subTest(index=index):
                main_started = asyncio.Event()
                async def handle(body):
                    if not self.acoustic(body):
                        main_started.set()
                        await asyncio.Future()
                    await main_started.wait()
                    return response(body, uncertain=True, changed_index=index)
                planner = await self.planner(handle)
                planner.observe_input(self.messages[0], 0)
                result = await asyncio.wait_for(planner.plan(self.context()), .5)
                self.assertTrue(result['clarification'])
                self.assertEqual(result['tool_calls'], [])
                self.assertEqual([row['message_index'] for row in result['observations']], [index])
                self.assertEqual([key[0] for key in planner._audio_cache], [index])
                self.assertTrue(all(row['uncertain'] for row in planner._audio_cache.values()))
                self.assertTrue(planner._audio_stopped)
                await planner.close()
                self.assertEqual(planner._pending_tasks, set())

    async def test_independent_uncertainty_vetoes_confident_write_but_clear_audio_can_authorize_it(self):
        command = 'Set the label to Harbor.'
        tools = {'set_label': {'kind': 'state_modifying', 'description': 'Set a display label.',
                               'args': {'label': {'type': 'string', 'required': True}}}}
        for uncertain in (True, False):
            with self.subTest(uncertain=uncertain):
                async def handle(body):
                    observations = [{'message_index': 0, 'type': 'audio', 'transcript': command,
                                     'uncertain': uncertain and self.acoustic(body)}]
                    decision = {'observations': observations}
                    if not self.acoustic(body):
                        decision.update(intent='set_label', slots={'label': 'Harbor'}, tool_calls=[{
                            'api_name': 'set_label', 'args': {'label': 'Harbor'},
                            'authorization': {'quote': command, 'message_index': 0},
                            'response_template': 'The label was updated.'}], response=None, clarification=None)
                    return httpx.Response(200, json={'candidates': [{'finishReason': 'STOP',
                        'content': {'parts': [{'text': json.dumps(decision)}]}}]})

                planner = await self.planner(handle)
                agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue(), planner=planner)
                self.addAsyncCleanup(agent.close)
                await agent.setup()
                agent._handle({'event_type': 'tool_manifest', 'payload': {'tools': tools}})
                message = deepcopy(self.messages[0]['payload'])
                message['end_of_turn'] = True
                agent._handle({'event_type': 'user_audio_chunk', 'payload': message})
                _, decision = await asyncio.wait_for(agent._plan_task, .5)
                agent._apply(decision)
                events = []
                while not agent.out_queue.empty():
                    events.append(agent.out_queue.get_nowait())
                writes = [event for event in events if event['action'] == 'tool_call']
                if uncertain:
                    self.assertTrue(decision['clarification'])
                    self.assertEqual(decision['tool_calls'], [])
                    self.assertEqual(writes, [])
                    self.assertTrue(decision['observations'][0]['uncertain'])
                else:
                    self.assertIsNone(decision['clarification'])
                    self.assertEqual(len(decision['tool_calls']), 1)
                    self.assertEqual(len(writes), 1)
                    self.assertEqual(writes[0]['payload']['api_name'], 'set_label')
                    key, cached = next(iter(planner._audio_cache.items()))
                    self.assertEqual(key[:3], (0, agent.messages[0]['revision'], 'audio/mpeg'))
                    self.assertEqual(cached['transcript'], command)
                    self.assertFalse(cached['uncertain'])

    async def test_main_first_uncertainty_only_caches_clear_words_after_both_full_readings_agree(self):
        for index in (0, 1):
            with self.subTest(index=index):
                main_done, release = asyncio.Event(), asyncio.Event()
                async def handle(body):
                    if self.acoustic(body):
                        await release.wait()
                        return response(body, uncertain=True, changed_index=index)
                    return response(body)
                planner = await self.planner(handle)
                original = planner._decide
                async def completed_main(*args):
                    result = await original(*args)
                    main_done.set()
                    return result
                with patch.object(planner, '_decide', completed_main):
                    planner.observe_input(self.messages[0], 0)
                    task = asyncio.create_task(planner.plan(self.context()))
                    await asyncio.wait_for(main_done.wait(), .5)
                    await asyncio.sleep(0)
                    release.set()
                    result = await asyncio.wait_for(task, .5)
                self.assertTrue(result['clarification'])
                self.assertEqual(result['tool_calls'], [])
                self.assertEqual([row['message_index'] for row in result['observations']], [0, 1])
                self.assertEqual({key[0]: row['uncertain'] for key, row in planner._audio_cache.items()},
                                 {0: index == 0, 1: index == 1})
                self.assertTrue(planner._audio_stopped)
                await planner.close()
                self.assertEqual(planner._pending_tasks, set())

    async def test_replan_joins_one_inflight_job_without_resetting_original_clock(self):
        release, acoustic_started, main_done = asyncio.Event(), asyncio.Event(), asyncio.Event()
        acoustic_count = 0
        async def handle(body):
            nonlocal acoustic_count
            if self.acoustic(body):
                acoustic_count += 1
                acoustic_started.set()
                await release.wait()
            else:
                main_done.set()
            return response(body)
        planner = await self.planner(handle)
        planner.observe_input(self.messages[0], 0)
        task = asyncio.create_task(planner.plan(self.context()))
        await asyncio.wait_for(acoustic_started.wait(), .5)
        await asyncio.wait_for(main_done.wait(), .5)
        job = planner._audio_jobs['turn']['task']
        self.assertFalse(task.done())
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.assertFalse(job.done())
        newer = asyncio.create_task(planner.plan(self.context(revision=3)))
        await asyncio.sleep(.02)
        self.assertEqual(acoustic_count, 1)
        self.assertIs(planner._audio_jobs['turn']['task'], job)
        self.assertFalse(newer.done())
        release.set()
        result = await asyncio.wait_for(newer, .5)
        self.assertTrue(result['tool_calls'])

    async def test_changed_bytes_or_message_identity_cannot_reuse_a_completed_turn_job(self):
        for index in (0, 1):
            for change in ('bytes', 'revision', 'missing'):
                with self.subTest(index=index, change=change):
                    for i, raw in enumerate(CLIPS):
                        (self.root / f'{i}.mp3').write_bytes(raw)
                    self.requests.clear()
                    planner = await self.planner()
                    planner.observe_input(self.messages[0], 0)
                    self.assertTrue((await planner.plan(self.context()))['tool_calls'])
                    original_cache = deepcopy(planner._audio_cache)
                    context = self.context()
                    if change == 'bytes':
                        (self.root / f'{index}.mp3').write_bytes(CLIPS[1 - index])
                    elif change == 'revision':
                        context['messages'][index]['revision'] = 7
                    else:
                        context['messages'].pop(index)
                    result = await planner.plan(context)
                    self.assertTrue(result['clarification'])
                    self.assertEqual(result['tool_calls'], [])
                    self.assertEqual(planner._audio_cache, original_cache)
                    self.assertEqual(sum(self.acoustic(body) for body in self.requests), 1)
                    await planner.close()
                    self.assertEqual(planner._pending_tasks, set())

    async def test_changed_historical_bytes_cannot_reuse_retained_audio_observation(self):
        planner = await self.planner()
        planner.observe_input(self.messages[0], 0)
        first = await planner.plan(self.context())
        self.assertTrue(first['tool_calls'])

        messages = deepcopy(self.messages)
        messages.append({'message_index': 2, 'revision': 2, 'event_type': 'user_speech_chunk',
                         'payload': {'text': 'What did I say?', 'end_of_turn': True}})
        (self.root / '0.mp3').write_bytes(CLIPS[1])
        result = await planner.plan(self.context(messages=messages, revision=2, current_turn_start=2,
                                                  observations=first['observations']))

        self.assertTrue(result['tool_calls'])
        main = next(body for body in reversed(self.requests) if not self.acoustic(body))
        prepared = json.loads(main['contents'][0]['parts'][0]['text'])
        self.assertEqual([row['message_index'] for row in prepared['observations']], [1])
        self.assertEqual([source['message_index'] for source in planner.evidence[-1]['reused_audio']], [1])

    async def test_new_text_or_wordless_interruption_evicts_late_swallowed_completion(self):
        for kind in ('user_speech_chunk', 'interruption'):
            with self.subTest(kind=kind):
                arrived, cancelled = asyncio.Event(), asyncio.Event()
                async def handle(body):
                    if self.acoustic(body):
                        arrived.set()
                    try:
                        await asyncio.Future()
                    except asyncio.CancelledError:
                        if self.acoustic(body):
                            cancelled.set()
                        return response(body)
                planner = await self.planner(handle)
                planner.observe_input(self.messages[0], 0)
                first = asyncio.create_task(planner.plan(self.context()))
                await asyncio.wait_for(arrived.wait(), .5)
                planner.observe_input({'message_index': 2, 'revision': 2, 'event_type': kind,
                                       'payload': {} if kind == 'interruption' else {'text': 'Stop.', 'end_of_turn': True}}, 2)
                self.assertEqual(planner._audio_jobs, {})
                await asyncio.wait_for(cancelled.wait(), .5)
                outcome = await asyncio.wait_for(asyncio.gather(first, return_exceptions=True), .5)
                self.assertIsInstance(outcome[0], asyncio.CancelledError)
                await planner.close()
                self.assertEqual(planner._audio_jobs, {})
                self.assertEqual(planner._audio_cache, {})
                self.assertEqual(planner._pending_tasks, set())

    async def test_identical_audio_in_a_new_turn_has_new_source_ownership(self):
        planner = await self.planner()
        planner.observe_input(self.messages[0], 0)
        first = await planner.plan(self.context())
        original = planner._audio_jobs['turn']
        newer = deepcopy(self.messages[0])
        newer.update(message_index=2, revision=2)
        newer['payload']['end_of_turn'] = True
        planner.observe_input(newer, 2)
        self.assertEqual(planner._audio_jobs, {})
        result = await planner.plan(self.context(messages=[*self.messages, newer], revision=2,
            current_turn_start=2, observations=first['observations']))
        self.assertTrue(result['tool_calls'])
        self.assertEqual(len(self.requests), 4)
        self.assertIsNot(planner._audio_jobs['turn'], original)
        self.assertEqual(planner._audio_jobs['turn']['keys'][0][:2], (2, 2))
        self.assertEqual([self.targets(body) for body in self.requests[-2:]], [[2], [2]])
        self.assertEqual([self.clips(body) for body in self.requests[-2:]], [CLIPS[:1], CLIPS[:1]])

    async def test_either_native_source_vetoes_uncertainty_or_conflict_in_either_clip(self):
        for acoustic in (False, True):
            for conflict in (False, True):
                for index in (0, 1):
                    with self.subTest(acoustic=acoustic, conflict=conflict, index=index):
                        async def handle(body):
                            changed = self.acoustic(body) == acoustic
                            return response(body, uncertain=changed and not conflict,
                                            conflict=changed and conflict, changed_index=index)
                        planner = await self.planner(handle)
                        planner.observe_input(self.messages[0], 0)
                        result = await planner.plan(self.context())
                        self.assertTrue(result['clarification'])
                        self.assertEqual(result['tool_calls'], [])
                        self.assertTrue(planner._audio_stopped)
                        count = len(self.requests)
                        repeated = await planner.plan(self.context(revision=2))
                        self.assertTrue(repeated['clarification'])
                        self.assertEqual(len(self.requests), count)
                        await planner.close()
                        self.assertEqual(planner._pending_tasks, set())

    async def test_preparation_counts_toward_acoustic_deadline_and_failure_does_not_retry(self):
        planner = await self.planner()
        planner.acoustic_timeout = .02
        prepare = planner.media.prepare
        async def slow(messages):
            await asyncio.sleep(.05)
            return await prepare(messages)
        planner.observe_input(self.messages[0], 0)
        with patch.object(planner.media, 'prepare', slow):
            result = await planner.plan(self.context())
        self.assertTrue(result['clarification'])
        self.assertEqual(result['tool_calls'], [])
        self.assertFalse(any(self.acoustic(body) for body in self.requests))
        self.assertTrue(any(row['phase'] == 'acoustic' and row['status'] == 'timeout' for row in planner.evidence))
        count = len(self.requests)
        await planner.plan(self.context(revision=2))
        self.assertEqual(len(self.requests), count)
        self.assertEqual(planner._audio_cache, {})

    async def test_uncertain_main_cancels_full_turn_transport_without_caching_late_success(self):
        for index in (0, 1):
            with self.subTest(index=index):
                arrived, cancelled = asyncio.Event(), asyncio.Event()
                async def handle(body):
                    if self.acoustic(body):
                        arrived.set()
                        try:
                            await asyncio.Future()
                        except asyncio.CancelledError:
                            cancelled.set()
                            return response(body)
                    await arrived.wait()
                    return response(body, uncertain=True, changed_index=index)
                planner = await self.planner(handle)
                planner.observe_input(self.messages[0], 0)
                result = await asyncio.wait_for(planner.plan(self.context()), .5)
                await asyncio.wait_for(cancelled.wait(), .5)
                self.assertTrue(result['clarification'])
                self.assertEqual(result['tool_calls'], [])
                self.assertEqual(result['observations'], [])
                self.assertEqual(planner._audio_cache, {})
                await planner.close()
                self.assertEqual(planner._audio_jobs, {})
                self.assertEqual(planner._pending_tasks, set())

    async def test_replanning_cannot_extend_or_replay_acoustic_timeout(self):
        arrived = asyncio.Event()
        async def handle(body):
            if self.acoustic(body):
                arrived.set()
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    return response(body)
            return response(body)
        planner = await self.planner(handle)
        planner.acoustic_timeout = .04
        planner.observe_input(self.messages[0], 0)
        first = asyncio.create_task(planner.plan(self.context()))
        # Allow a busy test host to dispatch the first mocked request; the
        # acoustic deadline being tested remains the explicit 40 ms above.
        await asyncio.wait_for(arrived.wait(), 2.0)
        original = planner._audio_jobs['turn']['task']
        await asyncio.sleep(.01)
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        result = await asyncio.wait_for(planner.plan(self.context(revision=2)), .5)
        self.assertTrue(result['clarification'])
        self.assertEqual(result['tool_calls'], [])
        self.assertEqual(sum(self.acoustic(body) for body in self.requests), 1)
        self.assertTrue(original.done())
        self.assertFalse(original.cancelled())
        self.assertIsInstance(original.exception(), PlannerError)
        self.assertTrue(any(row['phase'] == 'acoustic' and row['status'] == 'timeout'
                            and [source['message_index'] for source in row['input_media']] == [0, 1]
                            for row in planner.evidence))
        count = len(self.requests)
        await planner.plan(self.context(revision=3))
        self.assertEqual(len(self.requests), count)
        self.assertEqual(planner._audio_cache, {})

    async def test_complete_clip_keeps_two_requests_and_optional_hook_ignores_malformed_payload(self):
        planner = await self.planner()
        planner.observe_input({'event_type': 'user_audio_chunk', 'payload': None}, 0)
        single = deepcopy(self.messages[0])
        single['payload']['end_of_turn'] = True
        planner.observe_input(single, 0)
        self.assertEqual(self.requests, [])
        result = await planner.plan(self.context(messages=[single]))
        self.assertTrue(result['tool_calls'])
        self.assertEqual(len(self.requests), 2)

    async def test_audio_repair_overrides_a_stale_read_only_flight_search(self):
        tool = {'flight_search': {'kind': 'read_only',
            'description': 'Search flights to a destination city on a given date.', 'args': {
                'destination': {'type': 'string', 'required': True,
                                'description': 'Destination city name or airport code.'}}}}
        transcripts = ['Book a flight to Alderford.', 'Actually make that Rivermouth.']
        acoustic_transcripts = ['book a flight to Alderford', 'actually, make that Rivermouth']

        async def handle(body):
            acoustic = self.acoustic(body)
            indices = self.targets(body)
            source = acoustic_transcripts if acoustic else transcripts
            decision = {'observations': [
                {'message_index': index, 'type': 'audio', 'transcript': source[index], 'uncertain': False}
                for index in indices]}
            if not acoustic:
                decision.update(intent='book_flight', slots={'destination': 'Alderford'}, tool_calls=[{
                    'api_name': 'flight_search', 'args': {'destination': 'Alderford'},
                    'response_template': 'Flights to Alderford: option {flights.0.flight_id}.'}],
                    response=None, clarification=None)
            return httpx.Response(200, json={'candidates': [{'finishReason': 'STOP', 'content': {'parts': [
                {'text': json.dumps(decision)}]}}]})

        planner = await self.planner(handle)
        planner.observe_input(self.messages[0], 0)
        result = await planner.plan(self.context(tools=tool))
        self.assertEqual(result['tool_calls'][0]['args']['destination'], 'Rivermouth')
        self.assertEqual(result['slots']['destination'], 'Rivermouth')
        self.assertEqual([call['api_name'] for call in result['tool_calls']], ['flight_search'])
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(sum(self.acoustic(body) for body in self.requests), 1)
        self.assertTrue(all(self.clips(body) == CLIPS for body in self.requests))
        audit = next(row for row in planner.evidence if row['phase'] == 'planning')
        self.assertNotIn('audio_transcript_conflicts', audit)
        self.assertEqual({row['message_index'] for row in audit['audio_format_equivalence']}, {0, 1})

    async def test_controller_never_dispatches_for_an_unclosed_audio_turn(self):
        planner = await self.planner()
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue(), planner=planner)
        self.addAsyncCleanup(agent.close)
        await agent.setup()
        agent._handle({'event_type': 'tool_manifest', 'payload': {'tools': self.context()['tools']}})
        agent._handle({'event_type': 'user_audio_chunk', 'payload': deepcopy(self.messages[0]['payload'])})
        agent._handle({'event_type': 'scenario_end', 'payload': {}})
        await asyncio.sleep(.02)
        self.assertTrue(agent._turn_open)
        self.assertIsNone(agent._plan_task)
        self.assertTrue(agent.out_queue.empty())
        self.assertEqual(self.requests, [])
        self.assertEqual(planner._audio_jobs, {})
        agent._handle({'event_type': 'user_audio_chunk', 'payload': deepcopy(self.messages[1]['payload'])})
        _, result = await asyncio.wait_for(agent._plan_task, .5)
        self.assertTrue(result['tool_calls'])
        self.assertEqual(len(self.requests), 2)
        self.assertTrue(all(self.clips(body) == CLIPS for body in self.requests))


if __name__ == '__main__':
    unittest.main()
