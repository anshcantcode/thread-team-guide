"""Single-event-loop controller. Model calls never hold execution locks.

Read relevance is checked using the tool's actual argument dependencies, not a global
revision. Submitted writes are reconciled forever within their owning live session.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone as utc_timezone
import json
import re
import time
from uuid import uuid4
from zoneinfo import ZoneInfo

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
try:
    from referencing.exceptions import Unresolvable
except ImportError:  # Android's portable jsonschema uses the earlier resolver.
    from jsonschema.exceptions import RefResolutionError as Unresolvable

from .fixtures import PACKS
from .capabilities import BUILTINS
from .planner import ProviderError, settings, provider_trace
from .protocol import InputEvent, Interpretation, Manifest
from .sandbox import Sandbox
from .clock import RealClock
from .authorization import guard_interpretation, STOP_WORK


def uid(prefix):
    return f'{prefix}-{uuid4().hex[:12]}'


class Session:
    def __init__(self, planner, timezone='Asia/Kolkata', date=None, external=False,
                 *, clock=None, evaluation=False, manifests=None):
        self.clock = clock or RealClock()
        self.evaluation = evaluation
        self._id_sequence = 0
        self.id = self.new_id('session')
        self.planner = planner
        self.timezone = timezone
        self.date = date if date is not None else self.clock.utcnow().astimezone(ZoneInfo(timezone)).date().isoformat()
        self.external = external
        available = manifests if manifests is not None else {} if evaluation else PACKS | BUILTINS
        self.manifests = {k: v.model_copy(deep=True) for k, v in available.items()}
        self.sandbox = Sandbox(clock=self.clock, persistent=not evaluation)
        self.domain = ''
        self.slots = {}
        self.slot_sources = {}
        self.previous_tasks = {}
        self.revision = 0
        self.results = None
        self.workspace = {}
        self.selection = None
        self.selection_generation = 0
        self.media = None
        self.frame_slots = {m.id: set(m.frame_slots) for m in self.manifests.values() if m.frame_slots}
        self.observation = ''
        self.provisional = ''
        self.paused = False
        self.ended = False
        self.floor_held = False
        self.speech_muted = False
        self.pending_inputs = 0
        self.interrupt_epoch = 0
        self.reasoning_generation = 0
        self.interpretation_task = None
        self.current_input = None
        self.unprocessed_inputs = []
        self.transcript_chunks = {}
        self.input_floor_held = False
        self._closed = False
        self.transcript = []
        self.operations = {}
        self.trace = []
        self.seen_inputs = set()
        self.seen_results = set()
        self.deferred = []
        self.outbox = asyncio.Queue()
        self.inputs = asyncio.Queue()
        self.tasks = set()
        self.start_time = self.clock.now()
        self.last_activity = time.monotonic()
        self.live_feedback = None
        self.worker = asyncio.create_task(self._work())
        self.emit('session_started', 'Session-scoped evaluation controller ready.' if evaluation else 'Fresh THREAD workspace. Live information, local tools and explicitly labelled demo services.', date=self.date, timezone=timezone, protocol='thread.v1')
        if not evaluation:
            self.say('Tell me what you need. You can interrupt or change the plan while I work.')

    def new_id(self, prefix):
        if not self.clock.deterministic:
            return uid(prefix)
        self._id_sequence += 1
        return f'{prefix}-{self._id_sequence:06d}'

    def spawn(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    def emit(self, kind, text='', **data):
        event = {'id': self.new_id('event'), 'seq': len(self.trace) + 1, 'type': kind,
                 'at_ms': round((self.clock.now() - self.start_time) * 1000, 2),
                 'timestamp': self.clock.utcnow().isoformat(), 'text': text, **deepcopy(data)}
        self.trace.append(event)
        self.outbox.put_nowait(event)
        return event

    def snapshot(self):
        return {'protocol': 'thread.v1', 'session_id': self.id, 'mode': 'external adapter' if self.external else 'voice workspace',
                'date': self.date, 'timezone': self.timezone, 'domain': self.domain,
                'revision': self.revision, 'slots': deepcopy(self.slots), 'slot_sources': deepcopy(self.slot_sources),
                'missing': self.missing(), 'results': deepcopy(self.results), 'selection': deepcopy(self.selection),
                'workspace': deepcopy(list(self.workspace.values())[-20:]),
                'capability': {'title': self.manifest().title, 'can_create': bool(self.manifest().tool('create'))} if self.manifest() else None,
                'paused': self.paused, 'ended': self.ended, 'floor_held': self.floor_held,
                'understanding': self.pending_inputs > 0, 'provisional': self.provisional,
                'media': {k: v for k, v in (self.media or {}).items() if k != 'base64'},
                'observation': self.observation, 'transcript': deepcopy(self.transcript),
                'operations': [{k: deepcopy(v) for k, v in op.items() if k != 'task'} for op in self.operations.values()],
                'challenge': deepcopy(self.sandbox.config), 'unresolved': self.unresolved(),
                'metrics': {'clock': 'virtual replay timeline' if self.clock.deterministic else 'server wall clock since session start; not speech-onset latency',
                            'submitted_creates': len(self.sandbox.submissions), 'actual_creations': len(self.sandbox.creations),
                            'excluded_read_results': sum(e['type'] == 'stale_result_excluded' for e in self.trace)}}

    def publish(self):
        self.outbox.put_nowait({'type': 'snapshot', 'state': self.snapshot()})

    def say(self, text, final=False, clarification=False):
        if self.live_feedback is not None:
            # Task feedback is evidence for the native voice, not a second speaker.
            event = self.emit('task_feedback', text, final=final, clarification=clarification,
                              revision=self.revision)
            self.live_feedback.put_nowait(event)
            return
        message = {'id': self.new_id('message'), 'role': 'assistant', 'text': text,
                   'delivery': 'text_only' if self.speech_muted or self.floor_held or self.ended else 'available', 'revision': self.revision}
        self.transcript.append(message)
        self.emit('clarify' if clarification else 'final' if final else 'speak', text,
                  message_id=message['id'], speak=not self.speech_muted and not self.floor_held and not self.ended,
                  **({'state_snapshot': self.summary()} if final else {}))

    def summary(self):
        return {'goal': self.domain, 'slots': deepcopy(self.slots), 'selected_option': deepcopy(self.selection),
                'perception': {'media_id': self.media['id'], 'observation': self.observation} if self.media else None,
                'result_source': self.results.get('source') if self.results else None,
                'evidence': {k: deepcopy(self.results[k]) for k in ('call_id', 'source', 'summary', 'items', 'evidence', 'media_id') if k in self.results} if self.results else None,
                'comparison_evidence': [deepcopy(value) for key,value in self.workspace.items() if key.startswith('comparison:')],
                'actions': [{'call_id': op['id'], 'tool': op['tool'], 'arguments': op['arguments'],
                             'status': op['status'], 'result': op.get('result'),
                             'confirmed_reference': op.get('confirmed_reference'),
                             'cancellation_pending': op.get('cancellation_pending', False)} for op in self.operations.values() if op['purpose'] == 'create'],
                'unresolved': self.unresolved()}

    def unresolved(self):
        return [op['id'] for op in self.operations.values() if op['purpose'] == 'create'
                and op['status'] in ('submitted', 'unknown', 'cancel_requested')]

    def manifest(self):
        return self.manifests.get(self.domain)

    def missing(self):
        manifest = self.manifest()
        if not manifest: return []
        tool = manifest.tool('lookup')
        return [k for k in tool.parameters.get('required', []) if k not in self.slots]

    def context(self, seen_results=None, include_frame=False):
        visible = self.results if self.results and (seen_results is None or seen_results == self.results['id']) else None
        return {'date': self.date, 'timezone': self.timezone, 'active_domain': self.domain,
                'slots': self.slots, 'selection': self.selection, 'visible_results': visible,
                'results_reference_stale': bool(seen_results and (not self.results or seen_results != self.results['id'])),
                'manifests': [m.model_dump() for m in self.manifests.values()],
                'previous_tasks': self.previous_tasks, 'history': self.transcript[-8:],
                'actions': self.summary()['actions'], 'media': self.media if self.domain == 'device' or include_frame else None,
                'observation': self.observation if self.domain == 'device' or include_frame else '', 'paused': self.paused}

    def yield_floor(self, hold=True):
        self.floor_held = hold
        for message in self.transcript:
            if message.get('delivery') in ('playing', 'queued'):
                message['delivery'] = 'interrupted'
        self.emit('speech_stop', 'Conversational floor yielded. Prepared writes are held.' if hold else 'Speech stopped.', hold=hold)

    def preempt_interpretation(self, *, discard=False):
        self.reasoning_generation += 1
        if discard:
            self.unprocessed_inputs.clear()
        if self.interpretation_task and not self.interpretation_task.done():
            self.interpretation_task.cancel()

    def retain_unprocessed(self, event):
        item = {'id': event.id, 'type': event.type, 'text': event.text}
        if event.type == 'audio':
            item['data'] = deepcopy(event.data)
        if event.type != 'frame' or event.text:
            self.unprocessed_inputs.append(item)

    async def acknowledge_processing(self, event, generation):
        await self.clock.sleep(.18)
        if (generation != self.reasoning_generation or not self.pending_inputs or self.ended
                or self.input_floor_held or self.speech_muted):
            return
        text = {'audio': 'I have the audio. I am checking what was said before changing the task.',
                'frame': 'I have the image. I am checking the visible details before using them.'}.get(event.type)
        if text is None:
            text = ('I am checking your update against the current task. Any prepared action is held.'
                    if self.domain else 'I am checking the details needed for your request.')
        substantive = False
        if self.manifest():
            # State-specific coordination has already taken effect, even though
            # semantic interpretation is pending. Report that separately from the
            # eventual corrected slots; never pretend the correction is understood.
            held = [op for op in self.operations.values() if op['purpose'] == 'create' and op['status'] == 'prepared']
            if held:
                text = f'I am holding the prepared action for {held[-1]["selection"]["title"]}. Your update must be resolved before it can be submitted.'
            elif self.selection:
                text = f'The current selection is {self.selection["title"]}. I will not submit a new action while I check your update.'
            else:
                detail = (f'{self.slots["origin"]} to {self.slots["destination"]}'
                          if self.slots.get('origin') and self.slots.get('destination') else self.manifest().title)
                text = f'I am keeping the current details for {detail} while I check your update. Any arriving result will be held until the update is resolved.'
            substantive = True
        self.emit('speak', text, speak=True, input_id=event.id, stage='coordination' if substantive else 'processing',
                  substantive=substantive, state_snapshot=self.summary())

    async def accept(self, event: InputEvent):
        if self._closed:
            raise ValueError('This session is closed.')
        self.last_activity = time.monotonic()
        if event.id in self.seen_inputs:
            self.emit('duplicate_input_ignored', 'Repeated input delivery ignored.', input_id=event.id)
            self.publish()
            return
        self.seen_inputs.add(event.id)
        if event.type == 'transcript':
            if not event.utterance_id or event.end_of_turn is None:
                raise ValueError('Transcript chunks require utterance_id and an explicit end_of_turn marker.')
            text = self.transcript_chunks.get(event.utterance_id, '') + event.text
            if len(text) > 12000 or (event.utterance_id not in self.transcript_chunks and len(self.transcript_chunks) >= 12):
                raise ValueError('Too many or oversized unfinished utterances.')
            if event.end_of_turn:
                self.transcript_chunks.pop(event.utterance_id, None)
            else:
                self.transcript_chunks[event.utterance_id] = text
            event = event.model_copy(update={'type': 'text' if event.end_of_turn else 'partial', 'text': text})
        if event.type == 'tool_result':
            if not self.external:
                raise ValueError('External tool results are only accepted by an external adapter session.')
            self.handle_result(event.data['call_id'], event.data['result'], event.data.get('notification_id', event.id))
            self.publish()
            return
        if event.type == 'speech_status':
            for message in self.transcript:
                if message['id'] == event.data.get('message_id') and event.data.get('status') in ('playing', 'played', 'interrupted', 'unavailable'):
                    message['delivery'] = event.data['status']
            self.publish()
            return
        if self.ended:
            self.emit('input_rejected', 'This session has ended. Start a new session.')
            return
        if event.type == 'interrupt':
            self.input_floor_held = True
            self.yield_floor()
            self.preempt_interpretation()
            self.publish()
            return
        if event.type == 'control':
            await self.control(event.data)
            self.publish()
            return
        if event.type == 'manifest':
            if not self.external: raise ValueError('Custom manifests use the external event adapter.')
            manifest = Manifest.model_validate(event.data['manifest']).check()
            if manifest.id in self.manifests: raise ValueError('Cannot replace a manifest inside an active session.')
            self.manifests[manifest.id] = manifest
            self.emit('manifest_added', f'Loaded described capability: {manifest.title}.', manifest=manifest.model_dump())
            self.publish()
            return
        if event.type == 'frame':
            self.media = {'id': event.id, 'mime': event.data['mime'], 'base64': event.data['base64'],
                          'label': event.data.get('label', 'Uploaded still image')}
            self.observation = ''
            for domain, keys in self.frame_slots.items():
                for key in keys:
                    self.previous_tasks.get(domain, {}).pop(key, None)
            # Prior observed identity/target are not evidence about a newly supplied frame.
            if self.domain in self.frame_slots:
                for key in self.frame_slots[self.domain]:
                    self.slots.pop(key, None)
                    self.slot_sources.pop(key, None)
                self.revision += 1
                self.invalidate()
            self.emit('frame_received', 'Current still image replaced. Temporal behaviour cannot be established from one frame.', media_id=event.id)
        if event.type == 'partial':
            self.input_floor_held = True
            self.provisional = event.text
            self.yield_floor()
            self.emit('partial_input', event.text, utterance_id=event.utterance_id)
            self.publish()
            # Partial input can launch harmless speculation; it never supplies write authority.
            self.spawn(self._speculate(event, self.revision, self.interrupt_epoch))
            return
        self.provisional = ''
        self.input_floor_held = bool(self.transcript_chunks)
        self.yield_floor()
        if event.type == 'text':
            normalized = event.text.strip().lower().rstrip('.!')
            # Exact complete utterances only. Quoted/negated/embedded text still goes to the model.
            immediate = {'stop': 'pause', 'wait': 'pause', 'wait, stop': 'pause',
                         **{words: 'stop_work' for words in STOP_WORK},
                         'stop talking, keep searching': 'speech_only'}
            if normalized in immediate:
                self.transcript.append({'id': event.id, 'role': 'user', 'text': event.text, 'source': 'text'})
                self.emit('input_received', event.text, input_id=event.id, source='text')
                if immediate[normalized] != 'speech_only': self.interrupt_epoch += 1
                self.stop(immediate[normalized])
                self.publish()
                return
        # New complete text/frame input replaces obsolete reasoning, retaining
        # unprocessed words as evidence for a fresh interpretation. Tool execution
        # itself remains dependency-based: a cough must not cancel useful reads.
        if event.type in ('text', 'frame', 'audio'):
            self.preempt_interpretation()
        self.pending_inputs += 1
        self.transcript.append({'id': event.id, 'role': 'user',
                               'text': '[Audio clip · awaiting transcription]' if event.type == 'audio' else event.text or 'Image attached',
                               'source': event.type})
        self.emit('input_received', event.text if event.type != 'audio' else 'Audio clip received for transcription and interpretation.', input_id=event.id, source=event.type)
        await self.inputs.put((event, self.interrupt_epoch, (self.media or {}).get('id'), self.reasoning_generation))
        self.spawn(self.acknowledge_processing(event, self.reasoning_generation))
        self.publish()

    async def _work(self):
        while True:
            event, epoch, frame_id, generation = await self.inputs.get()
            started = self.clock.now()
            self.current_input = event
            try:
                if epoch != self.interrupt_epoch or self.ended:
                    continue
                if generation != self.reasoning_generation and event.type == 'text':
                    self.retain_unprocessed(event)
                    continue
                if frame_id != (self.media or {}).get('id') and (event.type == 'frame' or self.domain in self.frame_slots):
                    self.emit('interpretation_superseded', 'A newer frame replaced the image this input referred to.', input_id=event.id)
                    continue
                context = deepcopy(self.context(event.seen_results, bool(self.media)))
                position = next((i for i,m in enumerate(self.transcript) if m['id'] == event.id), len(self.transcript))
                # Later queued utterances are not context for an earlier input's interpretation.
                context['history'] = deepcopy(self.transcript[:position][-8:])
                context['unprocessed_inputs'] = deepcopy(self.unprocessed_inputs)
                with provider_trace(lambda record, input_id=event.id: self.emit(
                        'provider_attempt', 'Model request attempt completed.', input_id=input_id, **record)):
                    self.interpretation_task = asyncio.create_task(self.planner.interpret(context, event))
                plan = await self.interpretation_task
                if epoch != self.interrupt_epoch or self.ended:
                    self.emit('interpretation_superseded', 'An earlier input cannot override the later stop.', input_id=event.id)
                    continue
                if generation != self.reasoning_generation:
                    self.emit('interpretation_superseded', 'Reasoning returned after it was replaced.', input_id=event.id)
                    self.retain_unprocessed(event)
                    continue
                if context.get('media') and context['media']['id'] != (self.media or {}).get('id'):
                    self.emit('interpretation_superseded', 'An interpretation of an older frame cannot describe the replacement image.', input_id=event.id)
                    continue
                plan, refusal = guard_interpretation(plan, plan.transcript if event.type == 'audio' else event.text,
                                                     self.manifests.get(plan.domain or self.domain))
                if refusal:
                    self.emit('authorization_rejected', refusal, input_id=event.id)
                if event.type == 'audio':
                    self.transcript[position]['text'] = plan.transcript or '[Unclear audio]'
                    self.emit('transcription', plan.transcript or '[Unclear audio]', input_id=event.id)
                self.emit('intent_interpreted', f'Understood: {plan.intent}.', input_id=event.id,
                          elapsed_ms=round((self.clock.now() - started) * 1000, 2),
                          measurement='Model interpretation time after queued input began processing',
                          provider=settings()['provider'], model=settings()['model'], intent=plan.model_dump())
                if self.pending_inputs == 1 and not self.input_floor_held:
                    self.floor_held = False
                self.unprocessed_inputs.clear()
                self.apply(plan, event)
            except asyncio.CancelledError:
                if self._closed:
                    raise
                if epoch == self.interrupt_epoch:
                    self.retain_unprocessed(event)
                self.emit('interpretation_superseded', 'Pending interpretation was cancelled for newer input.', input_id=event.id)
            except ProviderError as exc:
                if generation != self.reasoning_generation or epoch != self.interrupt_epoch:
                    continue
                if event.type == 'audio':
                    for message in self.transcript:
                        if message['id'] == event.id: message['text'] = '[Audio could not be interpreted]'
                self.paused = True
                if self.pending_inputs == 1 and not self.input_floor_held:
                    self.floor_held = False
                self.say(str(exc), clarification=True)
                self.emit('provider_error', str(exc), input_id=event.id)
            except (ValueError, KeyError, SchemaError, Unresolvable) as exc:
                self.paused = True
                if self.pending_inputs == 1 and not self.input_floor_held:
                    self.floor_held = False
                self.say(f'I could not use that input: {exc}', clarification=True)
                self.emit('input_error', str(exc), input_id=event.id)
            finally:
                self.interpretation_task = None
                self.current_input = None
                self.pending_inputs -= 1
                if self.pending_inputs == 0 and not self.input_floor_held:
                    self.floor_held = False
                    self._drain_results()
                self.inputs.task_done()
                self.publish()

    async def _speculate(self, event, revision, epoch):
        await self.clock.sleep(0.35)
        if self.provisional != event.text or self.pending_inputs or self.ended:
            return
        try:
            plan = await self.planner.interpret(self.context(event.seen_results), event)
            if self.revision != revision or self.interrupt_epoch != epoch or self.provisional != event.text or self.pending_inputs:
                return
            if plan.intent != 'revise': return
            domain = plan.domain or self.domain
            manifest = self.manifests.get(domain)
            if not manifest: return
            slots = deepcopy(self.slots if domain == self.domain else manifest.defaults)
            self._changes(slots, manifest, plan)
            tool = manifest.tool('lookup')
            args = {k: v for k, v in slots.items() if k in tool.parameters['properties']}
            if list(Draft202012Validator(tool.parameters, format_checker=FormatChecker()).iter_errors(args)):
                return
            if any(op['purpose'] == 'lookup' and op['domain'] == domain and op['arguments'] == args
                   and op['status'] in ('running', 'completed') for op in self.operations.values()):
                return
            self.start_lookup(domain, tool, args, speculative=True)
            self.publish()
        except (ProviderError, ValueError, KeyError):
            # Provisional ambiguity is resolved by the final utterance, without filler.
            return

    def _changes(self, slots, manifest, plan):
        properties = manifest.slots['properties']
        for name in plan.remove:
            if name not in properties: raise ValueError(f'Unknown task detail: {name}.')
            slots.pop(name, None)
        for change in plan.changes:
            if change.slot not in properties: raise ValueError(f'Unknown task detail: {change.slot}.')
            schema = properties[change.slot]
            value = change.value
            if isinstance(value, str) and schema.get('type') in ('integer', 'number', 'boolean', 'array', 'object'):
                try:
                    value = json.loads(value)
                except ValueError: raise ValueError(f'Invalid {change.slot} value.') from None
            try: json.dumps(value, allow_nan=False)
            except (ValueError, TypeError): raise ValueError(f'Invalid {change.slot} value.') from None
            errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value))
            if errors: raise ValueError(f'{change.slot}: {errors[0].message}')
            slots[change.slot] = value

    def apply(self, plan: Interpretation, event: InputEvent):
        intent = plan.intent
        if intent in ('cancel', 'stop_work', 'pause', 'speech_only', 'end'):
            self.stop(intent, action_id=plan.action_id)
            return
        if intent == 'status':
            self.report_status()
            return
        if intent == 'acknowledge':
            self.emit('work_retained', 'Acknowledgement received; applicable work continues.')
            return
        if intent == 'compare':
            if self.manifest() and plan.changes and (not plan.domain or plan.domain == self.domain):
                candidate = deepcopy(self.slots)
                self._changes(candidate, self.manifest(), plan)
                tool = self.manifest().tool('lookup')
                args = {k:v for k,v in candidate.items() if k in tool.parameters['properties']}
                errors = list(Draft202012Validator(tool.parameters,format_checker=FormatChecker()).iter_errors(args))
                if errors:
                    self.say('The comparison needs a complete set of details. Your active request is unchanged.',clarification=True)
                else:
                    operation = self.start_lookup(self.domain,tool,args,comparison=True)
                    operation['comparison_question'] = event.text or plan.transcript
            else:
                self.say(plan.question or 'Which alternative should I compare? Your active request is unchanged.',clarification=True)
            return
        if intent == 'unsupported':
            self.say(plan.question or 'That action service is not connected. I can help prepare a draft instead.', clarification=True)
            return
        if intent == 'observe' and (not self.media or not plan.observation.strip()):
            raise ValueError('A visual answer requires a current frame and an explicit observation.')
        domain = plan.domain or self.domain
        # Recover an omitted domain only when the supplied manifest schemas identify
        # exactly one capability. This also works for unfamiliar injected tools.
        keys = {change.slot for change in plan.changes}
        active = self.manifests.get(domain)
        if not plan.domain and keys and (not active or not keys <= active.slots['properties'].keys()):
            matches = [m.id for m in self.manifests.values() if keys <= m.slots['properties'].keys()]
            if len(matches) == 1:
                domain = matches[0]
                self.emit('capability_resolved', 'An omitted capability was resolved uniquely from its declared fields.', domain=domain)
            else:
                raise ValueError('Choose an explicit capability ID from the supplied manifests; these fields do not identify one unambiguously.')
        manifest = self.manifests.get(domain)
        if not manifest:
            if keys: raise ValueError('The requested capability is not in the supplied manifests. No task was changed.')
            if intent == 'observe':
                self.observation = plan.observation
                self.say(plan.observation + (' ' + plan.question if plan.question else ''), final=True)
                return
            self.say(plan.question or 'Tell me what you want to work on. I can research, calculate, check weather, save notes, and build plans or drafts.', clarification=True)
            return
        if self.media and (event.type == 'frame' or plan.observation) and (manifest.frame_slots or any(change.source == 'frame' for change in plan.changes)):
            self.frame_slots.setdefault(domain, set()).update(change.slot for change in plan.changes
                if change.source == 'frame' or (event.type == 'frame' and change.source != 'user' and change.slot in manifest.frame_slots))
        old = deepcopy(self.slots)
        switched = domain != self.domain
        candidate = deepcopy(self.previous_tasks.get(domain, manifest.defaults) if switched and intent == 'resume'
                             else manifest.defaults if switched else self.slots)
        if switched:
            # A switch already clears previous-domain slots. Redundant removals cannot corrupt the new task.
            plan = plan.model_copy(update={'remove': [k for k in plan.remove if k in manifest.slots['properties']]})
        self._changes(candidate, manifest, plan)
        if domain=='sports' and not switched and any(candidate.get(k)!=self.slots.get(k) for k in ('query','entity_type','sport')):
            # Entity IDs and team disambiguators describe one named subject. They
            # cannot carry into a different person's/team's query.
            for key in ('entity_id','team','competition','sport'):
                if key not in keys: candidate.pop(key,None)
        if domain == 'document' and not switched:
            supplied = {change.slot for change in plan.changes}
            new_document = candidate.get('kind') != self.slots.get('kind') or ('title' in supplied and 'blocks' in supplied and candidate.get('title') != self.slots.get('title'))
            if new_document:
                for key in ('summary', 'columns', 'rows'):
                    if key not in supplied: candidate.pop(key, None)
        if switched:
            if self.domain:
                self.previous_tasks[self.domain] = deepcopy(self.slots)
            self.domain = domain
            self.slots = deepcopy(self.previous_tasks.get(domain, manifest.defaults) if intent == 'resume' else manifest.defaults)
            self.slot_sources = {k: 'scenario default' for k in self.slots}
            self.selection = None
            self.results = None
            self.emit('goal_changed', f'Current task: {manifest.title}. Previous submitted actions remain accounted for.')
        changed = sorted(k for k in set(candidate) | set(self.slots) if candidate.get(k) != self.slots.get(k))
        self.slots = candidate
        for change in plan.changes:
            self.slot_sources[change.slot] = 'current image' if change.source == 'frame' else 'user report or current input interpretation'
        for key in plan.remove:
            self.slot_sources.pop(key, None)
        if changed or switched:
            self.revision += 1
            for key in changed:
                self.emit('slot_changed', f'{key.replace("_", " ").capitalize()}: {old.get(key, "unspecified")} → {self.slots.get(key, "removed")}.', slot=key, old=old.get(key), new=self.slots.get(key))
            self.invalidate()
        if plan.observation:
            self.observation = plan.observation
            self.emit('visual_observation', plan.observation, basis='Model interpretation of the current still image', media_id=(self.media or {}).get('id'))
        if intent == 'observe':
            self.paused = bool(plan.question)
            self.say(plan.observation + (' ' + plan.question if plan.question else ''), final=True)
            return
        if intent == 'clarify':
            self.paused = True
            self.say(plan.question or 'Please clarify the missing or uncertain detail.', clarification=True)
            return
        self.paused = False
        self.speech_muted = False
        if intent == 'resume': self.update_timer('resume')
        if self.slots.get('after') and self.slots.get('before') and self.slots['after'] >= self.slots['before']:
            self.paused = True
            self.say('Those time limits conflict on the same day. Which boundary should change?', clarification=True)
            return
        missing = self.missing()
        if missing:
            self.say('I still need ' + ', '.join(k.replace('_', ' ') for k in missing) + '.', clarification=True)
            return
        if plan.selection:
            if not self.results or (event.seen_results and event.seen_results != self.results['id']):
                self.say('The result list has changed. Please choose an option from the current results.', clarification=True)
                return
            selected = next((item for item in self.results['items'] if item['id'] == plan.selection), None)
            if not selected:
                self.say('That option is not in the current results. Which current option do you mean?', clarification=True)
                return
            if not self.selection or self.selection['id'] != selected['id']:
                self.selection_generation += 1
            self.selection = deepcopy(selected)
            for operation in self.operations.values():
                if (operation['purpose'] == 'create' and operation['status'] == 'prepared'
                        and operation['domain'] == self.domain and operation['selection']['id'] != selected['id']):
                    operation['status'] = 'not_submitted'
                    self.emit('authorization_invalidated', 'The selected option changed. The new option needs current authorization.', call_id=operation['id'])
            self.emit('option_selected', f'Selected {selected["title"]}.', option=selected, results_id=self.results['id'])
        if intent in ('commit', 'additional_action'):
            if event.seen_results and (not self.results or event.seen_results != self.results['id']):
                self.say('The results changed before that instruction arrived. Please choose from the current results.', clarification=True)
                return
            if self.domain in ('device', 'notes') and self.results and len(self.results['items']) == 1:
                self.selection = deepcopy(self.results['items'][0])
            self.prepare_action(event.id, additional=intent == 'additional_action')
            return
        if intent == 'select':
            self.say(f'Selected {self.selection["title"]}. Nothing new has been submitted.' if self.selection else 'Which current option should I select?', clarification=not bool(self.selection))
            return
        if self.results and self.result_current(self.results):
            if changed:
                self.say('Updated ' + ', '.join(k.replace('_', ' ') for k in changed) + '. The existing lookup still applies.')
            else:
                self.say('The current results are still available. Select an option or change a detail.')
        else:
            self.ensure_lookup()

    def lookup_args(self, manifest=None):
        manifest = manifest or self.manifest()
        return {k: v for k, v in self.slots.items() if k in manifest.tool('lookup').parameters['properties']}

    def result_current(self, result):
        if result.get('comparison'):
            return result['domain'] == self.domain and result.get('base_revision') == self.revision
        return bool(self.manifest() and result['domain'] == self.domain and result['arguments'] == self.lookup_args()
                    and (result.get('media_id') is None or result['media_id'] == (self.media or {}).get('id')))

    def cancel_read(self, op, reason):
        if op['purpose'] != 'lookup' or op['status'] != 'running':
            return
        op.update(status='superseded', obsolete=True)
        tool = self.manifests[op['domain']].tool('lookup')
        if tool.cancellable and not op.get('result_received'):
            self.emit('cancel', 'Read cancellation requested.', call_id=op['id'], reason=reason)
            if not self.external and not self.sandbox.config['late_reads'] and op.get('task') and not op['task'].done():
                op['task'].cancel()
                self.emit('cancellation_confirmed', 'Local read stopped before completion.', call_id=op['id'])

    def invalidate(self):
        if self.results and not self.result_current(self.results):
            self.results = None
            self.selection = None
        for op in list(self.operations.values()):
            if op['purpose'] == 'lookup' and op['status'] in ('running', 'completed') and not self.result_current(op):
                self.cancel_read(op, 'Task dependencies changed')
                op['status'] = 'superseded'
                op['obsolete'] = True
                self.emit('work_superseded', 'Lookup is no longer applicable to the current request.', call_id=op['id'])
            if op['purpose'] == 'create' and op['status'] == 'prepared' and (op['domain'] != self.domain or op['task_slots'] != self.slots):
                op['status'] = 'not_submitted'
                self.emit('authorization_invalidated', 'Prepared action stopped because its material details changed. A revised action needs current authorization.', call_id=op['id'])

    def ensure_lookup(self):
        args = self.lookup_args()
        for op in self.operations.values():
            if op['purpose'] == 'lookup' and self.result_current(op) and op['status'] == 'running':
                op['speculative'] = False
                self.emit('work_retained', 'Applicable lookup retained; no duplicate request.', call_id=op['id'])
                return
        self.start_lookup(self.domain, self.manifest().tool('lookup'), args)

    def start_lookup(self, domain, tool, args, speculative=False, comparison=False):
        errors = list(Draft202012Validator(tool.parameters, format_checker=FormatChecker()).iter_errors(args))
        if errors: raise ValueError(errors[0].message)
        op = {'id': self.new_id('call'), 'tool': tool.name, 'purpose': 'lookup', 'effect': 'read', 'domain': domain,
              'arguments': deepcopy(args), 'status': 'running', 'obsolete': False, 'speculative': speculative,
              'comparison': comparison, 'base_revision': self.revision,
              'media_id': (self.media or {}).get('id') if domain in self.frame_slots else None,
              'started_ms': round((self.clock.now() - self.start_time) * 1000, 2)}
        self.operations[op['id']] = op
        self.emit('tool_call', f'{"Provisional" if speculative else "Current"} lookup started: {tool.name}.', call_id=op['id'], tool=tool.name, effect='read', arguments=args)
        if not speculative:
            self.say('Checking ' + (f'{args["origin"]} to {args["destination"]} on {args["date"]}.' if domain == 'travel' else f'{self.manifests[domain].title.lower()} with the current details.'))
        if not self.external:
            op['task'] = self.spawn(self._run_lookup(op))
        return op

    async def _run_lookup(self, op):
        try:
            result = await self.sandbox.read(op['domain'], op['arguments'])
        except asyncio.CancelledError:
            return
        except Exception:
            result = {'status': 'failed', 'error': 'The tool could not complete this request. No result has been invented.'}
        self.handle_result(op['id'], result, self.new_id('notice'))
        self.publish()

    def prepare_action(self, input_id, additional=False):
        tool = self.manifest().tool('create')
        if not tool:
            self.say('This result does not have a connected action service. I can keep it in the workspace or prepare a draft.', clarification=True)
            return
        if not self.results or not self.result_current(self.results):
            self.ensure_lookup()
            self.say('I will find applicable options first. No action will be submitted until a current option is chosen.', clarification=True)
            return
        if not self.selection:
            self.say('Choose an option from the current results before I submit anything.', clarification=True)
            return
        if self.domain == 'device' and not self.slots.get('symptom'):
            self.say('What symptom should the support ticket report? A still image cannot establish blinking.', clarification=True)
            return
        args = {k: v for k, v in self.slots.items() if k in tool.parameters['properties']}
        if 'option_id' in tool.parameters['properties']:
            args['option_id'] = self.selection['id']
        for name, source in tool.bindings.items():
            if source == 'option_id': args[name] = self.selection['id']
        errors = list(Draft202012Validator(tool.parameters, format_checker=FormatChecker()).iter_errors(args))
        if errors:
            self.say('The action is missing a required detail: ' + errors[0].message, clarification=True)
            return
        if self.unresolved() and not additional:
            self.say('An earlier submitted action is still unresolved. I have not sent a replacement. Check its status first.', clarification=True)
            return
        existing = [op for op in self.operations.values() if op['purpose'] == 'create' and op['domain'] == self.domain
                    and op['status'] in ('prepared', 'submitted', 'unknown', 'cancel_requested', 'completed')]
        if existing and not additional:
            self.say('There is already a prepared, submitted, or confirmed action for this task. I have not created another. Specify a separate additional action if that is what you intend.', clarification=True)
            return
        op = {'id': self.new_id('call'), 'tool': tool.name, 'purpose': 'create', 'effect': 'write', 'domain': self.domain,
              'arguments': deepcopy(args), 'task_slots': deepcopy(self.slots), 'selection': deepcopy(self.selection),
              'results_id': self.results['id'], 'authorization_input': input_id,
              'status': 'prepared', 'obsolete': False,
              'started_ms': round((self.clock.now() - self.start_time) * 1000, 2)}
        self.operations[op['id']] = op
        self.emit('action_prepared', f'Prepared {tool.name}. No request has been submitted yet.', call_id=op['id'], arguments=args)
        self.say(f'Preparing {"to save the note" if self.domain == "notes" else "the demo action"} for {self.selection["title"]}.')
        op['task'] = self.spawn(self._submit_when_ready(op))

    async def _submit_when_ready(self, op):
        await self.clock.sleep(self.sandbox.config['prepare_delay'])
        while self.pending_inputs or self.floor_held:
            if op['status'] != 'prepared' or self.ended: return
            await self.clock.sleep(0.03)
        if op['status'] != 'prepared' or self.paused or self.ended:
            if op['status'] == 'prepared': op['status'] = 'not_submitted'
            self.publish()
            return
        if (op['domain'] != self.domain or op['task_slots'] != self.slots or not self.results
                or op['results_id'] != self.results['id'] or not self.selection
                or op['selection']['id'] != self.selection['id']):
            op['status'] = 'not_submitted'
            self.emit('authorization_invalidated', 'Action details changed before submission.', call_id=op['id'])
            self.publish()
            return
        op['status'] = 'submitted'
        self.emit('tool_call', 'Sandbox action submitted; outcome is pending.', call_id=op['id'], tool=op['tool'], effect='write', arguments=op['arguments'])
        self.publish()
        self.spawn(self._watch_outcome(op))
        if self.external: return
        result = await self.sandbox.create(op['id'], op['domain'], op['arguments'])
        self.handle_result(op['id'], result, self.new_id('notice'))
        if self.sandbox.config['duplicate_result']:
            self.handle_result(op['id'], result, self.new_id('notice'))
        self.publish()

    async def _watch_outcome(self, op):
        await self.clock.sleep(self.sandbox.config['timeout'])
        if op['status'] in ('submitted', 'cancel_requested'):
            if op.get('confirmed_reference'):
                return  # Creation is known; cancellation has its own deadline.
            op['status'] = 'unknown'
            self.emit('outcome_unknown', 'No terminal outcome received before the response timeout. This is not proof of failure.', call_id=op['id'])
            self.say('The request was sent, but its outcome is not yet confirmed. I have not submitted another action.', final=True)
            self.publish()

    def request_reconcile(self, parent, purpose):
        tool = self.manifests[parent['domain']].tool(purpose)
        if not tool or (purpose == 'status' and self.sandbox.ledger.get(parent['id'],{}).get('mode') == 'unverifiable' and not self.external):
            self.say(f'This environment does not provide a usable {purpose} capability for that action. Its outcome remains {parent["status"]}.', clarification=True)
            return
        if any(op['purpose'] == purpose and op.get('parent_id') == parent['id'] and op['status'] == 'running' for op in self.operations.values()):
            return
        arguments = {k: v for k, v in parent.get('task_slots', {}).items() if k in tool.parameters['properties']}
        bindings = tool.bindings or ({'operation_id': 'call_id'} if 'operation_id' in tool.parameters['properties'] else {})
        values = {'call_id': parent['id'], 'reference': parent.get('result', {}).get('reference'),
                  'option_id': parent.get('selection', {}).get('id')}
        for name, source in bindings.items():
            if values[source] is not None: arguments[name] = values[source]
        errors = list(Draft202012Validator(tool.parameters, format_checker=FormatChecker()).iter_errors(arguments))
        if errors:
            self.emit('reconciliation_blocked', 'The described tool needs an identifier not yet established by service evidence.', call_id=parent['id'], tool=tool.name)
            self.say('I cannot check or cancel that action until the required service identifier is known. Its existing outcome is preserved.', clarification=True)
            return
        op = {'id': self.new_id('call'), 'tool': tool.name, 'purpose': purpose, 'effect': tool.effect,
              'domain': parent['domain'], 'parent_id': parent['id'], 'arguments': arguments,
              'status': 'running', 'obsolete': False,
              'started_ms': round((self.clock.now() - self.start_time) * 1000, 2)}
        self.operations[op['id']] = op
        if purpose == 'cancel':
            parent['status'] = 'cancel_requested'
            parent['cancellation_pending'] = True
            self.emit('cancel', 'Cancellation requested. No cancellation is confirmed yet.', call_id=parent['id'], cancellation_call_id=op['id'])
        self.emit('tool_call', f'{purpose.capitalize()} request submitted.', call_id=op['id'], tool=op['tool'], effect=op['effect'], arguments=op['arguments'])
        self.spawn(self._watch_reconcile(op))
        if not self.external: self.spawn(self._reconcile(op))

    async def _watch_reconcile(self, op):
        await self.clock.sleep(self.sandbox.config['timeout'])
        if op['status'] != 'running':
            return
        op['status'] = 'unknown'
        parent = self.operations[op['parent_id']]
        self.emit('reconciliation_timeout', 'The service has not confirmed this reconciliation request.', call_id=op['id'], parent_id=parent['id'])
        self.say('The service has not confirmed ' + ('cancellation.' if op['purpose'] == 'cancel' else 'the status check.') +
                 (' The original action was confirmed as ' + parent['confirmed_reference'] + '.' if parent.get('confirmed_reference') else ' The original action remains unconfirmed.') +
                 ' No replacement has been submitted.', final=True)
        self.publish()

    async def _reconcile(self, op):
        result = await getattr(self.sandbox, op['purpose'])(op['parent_id'])
        self.handle_result(op['id'], result, self.new_id('notice'))
        self.publish()

    def handle_result(self, call_id, result, notification_id):
        op = self.operations.get(call_id)
        if not op:
            self.emit('protocol_error', 'Result for an unknown call ID rejected.', call_id=call_id)
            return
        if not isinstance(result, dict):
            self.emit('protocol_error', 'A tool result must be an object.', call_id=call_id)
            return
        try:
            json.dumps(result, allow_nan=False)
            if any(k in result and not isinstance(result[k], str) for k in ('summary', 'note', 'error', 'source', 'status')):
                raise ValueError('Tool result text fields must be strings.')
        except (ValueError, TypeError):
            self.emit('protocol_error', 'Malformed tool evidence rejected before state mutation.', call_id=call_id)
            return
        tool = self.manifests[op['domain']].tool(op['purpose'])
        if tool.result_schema is not None and not Draft202012Validator(tool.result_schema, format_checker=FormatChecker()).is_valid(result):
            self.emit('protocol_error', 'The result violates the tool output schema; no completion was accepted.', call_id=call_id)
            return
        if op['purpose'] == 'create' and op['status'] in ('prepared','not_submitted'):
            self.emit('protocol_error', 'A service result cannot complete an action that was never submitted.', call_id=call_id)
            return
        fingerprint = (call_id, json.dumps(result, sort_keys=True))
        if notification_id in self.seen_results or fingerprint in self.seen_results:
            self.emit('duplicate_result_ignored', 'Repeated outcome notification ignored; no additional consequence.', call_id=call_id)
            return
        self.seen_results.add(notification_id)
        self.seen_results.add(fingerprint)
        self.sandbox.last_results[call_id] = deepcopy(result)
        self.emit('tool_result', 'Service result received.', call_id=call_id, result=result)
        if op['purpose'] == 'lookup':
            op['result_received'] = True
            if self.pending_inputs or self.floor_held:
                self.deferred.append((call_id, deepcopy(result)))
                self.emit('result_held', 'Read result held while the user has the floor.', call_id=call_id)
                return
            self._apply_read_result(op, result)
        elif op['purpose'] == 'create':
            self._apply_write_result(op, result)
        else:
            parent = self.operations[op['parent_id']]
            op['status'] = 'running' if result.get('status') == 'pending' else 'unknown' if result.get('status') == 'unknown' else 'completed'
            op['result'] = deepcopy(result)
            if result.get('status') == 'declined':
                parent['cancellation_pending'] = False
                self.emit('cancellation_declined', 'Service declined cancellation; the requested stop did not undo the action.', call_id=parent['id'])
                known = result.get('known_status', 'unknown')
                if known == 'completed' and result.get('reference'):
                    self._apply_write_result(parent, {'status': 'completed', 'reference': result['reference']})
                    self.say('Cancellation was declined. The sandbox record exists; the stop did not undo it.', final=True)
                elif parent.get('confirmed_reference'):
                    parent['status'] = 'completed'
                    self.say('Cancellation was declined. I retain the original action confirmation, reference ' + parent['confirmed_reference'] + '. No successful cancellation is established.', final=True)
                else:
                    parent['status'] = 'unknown'
                    self.say('Cancellation was declined and the outcome is still unknown. No replacement was submitted.', final=True)
            else:
                if op['purpose'] == 'status' and result.get('status') in ('not_performed', 'failed'):
                    # An observational read can predate a delayed create. It does
                    # not certify that the original write can never take effect.
                    self._apply_write_result(parent, {'status': 'unknown'})
                else:
                    self._apply_write_result(parent, result)

    def _drain_results(self):
        deferred, self.deferred = self.deferred, []
        for call_id, result in deferred:
            self._apply_read_result(self.operations[call_id], result)

    def _apply_read_result(self, op, result):
        if self.ended or self.paused or op.get('obsolete') or not self.result_current(op):
            op['status'] = 'superseded'
            self.emit('stale_result_excluded', 'Not used: this lookup no longer matches the active request, or the task is paused.', call_id=op['id'], active_domain=self.domain, active_slots=self.slots)
            return
        op['speculative'] = False
        if result.get('status') == 'failed':
            op['status'] = 'failed'
            op['result'] = deepcopy(result)
            self.say(result.get('error', 'The lookup service failed. Availability is not established.') + ' Your task details are preserved; you can retry.', final=True)
            return
        items = result.get('items')
        valid = result.get('status') == 'completed' and isinstance(items, list) and isinstance(result.get('source'), str)
        if valid:
            valid = all(isinstance(x, dict) and isinstance(x.get('id'), str) and isinstance(x.get('title'), str) for x in items)
            valid = valid and len({x['id'] for x in items}) == len(items)
        if not valid:
            op['status'] = 'failed'
            self.say('The lookup returned incomplete or malformed evidence. I cannot recommend an option from it.', final=True)
            return
        op['status'] = 'completed'
        op['result'] = deepcopy(result)
        if op.get('comparison'):
            compared = {**deepcopy(result), 'id':self.new_id('results'), 'call_id':op['id'], 'domain':op['domain'],
                        'arguments':deepcopy(op['arguments']), 'comparison':True, 'base_revision':op['base_revision']}
            self.workspace['comparison:'+op['domain']] = compared
            self.emit('comparison_published','Alternative evidence published without changing the active request.',results_id=compared['id'])
            answer = result.get('summary',f'{len(items)} comparison results returned.')
            baseline = self.results if self.results and self.results['domain'] == op['domain'] else None
            prices = [*items, *((baseline or {}).get('items', []))]
            price_question = re.search(r'\b(?:cheap(?:er|est)?|costs?|prices?|fares?|expensive|affordable|budget)\b',op.get('comparison_question',''),re.I)
            comparable = (price_question and items and baseline and baseline.get('items') and all(type(item.get('price')) in (int,float)
                and 0 <= item['price'] <= 1e15 and isinstance(item.get('currency'),str) and item['currency'] for item in prices)
                and len({item['currency'] for item in prices}) == 1)
            if comparable:
                current_min = min(item['price'] for item in baseline['items'])
                alternative_min = min(item['price'] for item in items)
                difference, currency = alternative_min-current_min, prices[0]['currency']
                relation = 'the same' if difference == 0 else f'{abs(difference):g} {currency} '+('lower' if difference < 0 else 'higher')
                compared['price_comparison'] = {'baseline_result_id':baseline['id'], 'baseline_min':current_min,
                    'alternative_min':alternative_min,'currency':currency,'difference':difference,
                    'basis':'Lowest listed amounts among returned options in the same currency; not live-market or fee-inclusive verification.'}
                answer = f'Among the returned options, the lowest listed price is {alternative_min:g} {currency} for the alternative and {current_min:g} {currency} for the active request: {relation}. Sources: {result["source"]}; {baseline["source"]}.'
            self.say(answer+' This is a separate comparison; your active request and selection are unchanged.',final=True)
            return
        self.results = {**deepcopy(result), 'id': self.new_id('results'), 'call_id': op['id'], 'domain': op['domain'],
                        'arguments': deepcopy(op['arguments']), 'media_id': op.get('media_id')}
        # Keep a small, inspectable shelf of the latest result per task kind across goal switches.
        shelf_key = op['domain'] + (':' + op['arguments'].get('kind', '') if op['domain'] == 'document' else '')
        self.workspace.pop(shelf_key, None)
        self.workspace[shelf_key] = deepcopy(self.results)
        if len(self.workspace) > 20: self.workspace.pop(next(iter(self.workspace)))
        self.selection = None
        self.emit('results_published', 'Applicable evidence published for the current request.', call_id=op['id'], results_id=self.results['id'])
        if not items:
            self.say(result.get('note', 'No sandbox options match all current constraints. Which constraint may change?'), final=True)
        else:
            message = (f'According to {result["source"]}, {result["summary"]}' if result.get('summary') else
                       f'{len(items)} options returned by {result["source"]}: ' + '; '.join(item['title'] for item in items[:3]) + '.')
            if op['domain'] in ('travel', 'rooms'):
                message += ' Nothing new has been booked.'
            self.say(message, final=True)

    def _apply_write_result(self, op, result):
        status = result.get('status')
        if op['status'] in ('cancelled', 'not_performed') and status in ('pending', 'unknown', 'completed'):
            self.emit('older_outcome_retained_as_history', 'Older notification cannot undo a confirmed later cancellation.', call_id=op['id'])
            return
        if op.get('confirmed_reference') and (status in ('pending', 'unknown', 'not_performed', 'failed')
                or (status == 'completed' and result.get('reference') != op['confirmed_reference'])):
            self.emit('conflicting_outcome_excluded', 'A later-delivered negative or nonterminal result cannot erase confirmed creation. Cancellation needs explicit service confirmation.', call_id=op['id'])
            return
        if status == 'completed' and (not isinstance(result.get('reference'), str) or not result['reference'].strip()):
            status = 'unknown'
            self.emit('protocol_error', 'Completion result lacked the required service reference.', call_id=op['id'])
        if status == 'failed' and result.get('no_effect') is not True:
            status = 'unknown'
        if status not in ('completed', 'cancelled', 'not_performed', 'failed', 'pending', 'unknown'):
            status = 'unknown'
        if status == 'pending':
            if op['status'] != 'cancel_requested': op['status'] = 'submitted'
            return
        previous = op['status']
        if status == 'completed': op['confirmed_reference'] = result['reference']
        if status in ('cancelled', 'not_performed'): op['cancellation_pending'] = False
        op['status'] = 'cancel_requested' if status == 'completed' and op.get('cancellation_pending') else status
        op['result'] = deepcopy(result)
        self.emit('action_outcome', f'Action outcome: {status.replace("_", " ")}.', call_id=op['id'], status=status, reference=result.get('reference'))
        if previous == status: return
        if status == 'completed':
            detail = op['selection']['title']
            if op['domain'] == 'notes' and self.domain == 'notes' and self.results and self.slots == op['task_slots']:
                self.results.update(provenance='saved', source='THREAD local notebook', summary='This exact note is saved on this laptop.')
                self.results['items'][0]['reference'] = result['reference']
                self.workspace['notes'] = deepcopy(self.results)
            self.say(f'{"Note saved on this laptop" if op["domain"] == "notes" else "Sandbox action confirmed"} for {detail}. Reference {result["reference"]}.' +
                     (' This belongs to the earlier request; changing the task did not undo it.' if op['domain'] != self.domain or op['task_slots'] != self.slots or previous == 'cancel_requested' else ''), final=True)
        elif status == 'cancelled':
            if op['domain'] == 'notes' and self.domain == 'notes' and self.results and self.slots == op['task_slots']:
                self.results.update(provenance='archived', source='THREAD notebook · archived note')
                self.workspace['notes'] = deepcopy(self.results)
            self.say('The note has been archived in the local notebook.' if op['domain'] == 'notes' else 'The service confirms that the sandbox record was created and then cancelled.', final=True)
        elif status == 'not_performed':
            self.say('The service confirms that this action did not take effect. No record was created for it.', final=True)
        elif status == 'failed':
            self.say('The action failed; the service confirmed that no record was created.', final=True)
        else:
            self.say('The action outcome is unknown. I have not assumed failure or submitted a replacement.', final=True)

    def stop(self, scope, *, action_id=''):
        self.input_floor_held = False
        self.yield_floor(hold=False)
        if scope == 'speech_only':
            self.speech_muted = True
            self.emit('work_retained', 'Speech muted; applicable work continues.')
            return
        self.interrupt_epoch += 1
        self.preempt_interpretation(discard=True)
        self.update_timer(scope)
        self.paused = True
        if scope == 'end': self.ended = True
        candidates = [op for op in self.operations.values() if op['domain'] == self.domain and op['purpose'] == 'create'
                      and op['status'] in ('submitted', 'unknown', 'completed', 'cancel_requested')]
        target = next((op for op in candidates if op['id'] == action_id), None) if action_id else candidates[0] if len(candidates) == 1 else None
        for op in list(self.operations.values()):
            if op['purpose'] == 'lookup' and op['status'] == 'running':
                self.cancel_read(op, 'The user stopped this task.')
            if op['purpose'] == 'create' and op['status'] == 'prepared':
                op['status'] = 'not_submitted'
                self.emit('action_not_submitted', 'Prepared action was stopped before submission.', call_id=op['id'])
            elif scope == 'cancel' and op is target:
                self.request_reconcile(op, 'cancel')
        if scope == 'cancel' and candidates and target is None:
            self.say('New work is stopped. Which submitted action should I cancel? Specify its action call ID; existing outcomes are unchanged.', clarification=True)
        elif scope == 'pause':
            self.say('Paused. No new action will be submitted. Did you want to cancel the task or just stop speech?', clarification=True)
        elif scope == 'end':
            self.say('Session ended.' + (' Submitted actions remain unresolved; ending the session does not undo them.' if self.unresolved() else ' No further work will be started.'), final=True)
        elif self.unresolved():
            self.say('Stopped new work. A submitted action still needs an outcome; cancellation is not yet confirmed.', final=True)
        else:
            self.say('Stopped new work. Prepared actions were not submitted; confirmed prior outcomes remain in the action history.', final=True)

    def update_timer(self, scope):
        if self.domain != 'timer' or not self.results or not self.results['items']: return
        item = self.results['items'][0]
        now = self.clock.utcnow()
        if scope == 'pause' and not item.get('paused_at') and not item.get('cancelled'):
            item['paused_at'] = now.isoformat()
        elif scope == 'resume' and item.get('paused_at') and not item.get('cancelled'):
            duration = now - datetime.fromisoformat(item.pop('paused_at'))
            item['end_at'] = (datetime.fromisoformat(item['end_at']) + duration).isoformat()
        elif scope in ('cancel', 'end'):
            item['cancelled'] = True
        self.workspace['timer'] = deepcopy(self.results)

    def report_status(self):
        if self.domain == 'timer' and self.results and self.results['items']:
            item = self.results['items'][0]
            point = datetime.fromisoformat(item['paused_at']) if item.get('paused_at') else self.clock.utcnow()
            remaining = max(0, round((datetime.fromisoformat(item['end_at'])-point).total_seconds()))
            self.say('This timer was cancelled.' if item.get('cancelled') else f'{remaining} seconds remain on the {"paused" if item.get("paused_at") else "running"} timer.', final=True)
            return
        unresolved = self.unresolved()
        if unresolved:
            self.say('A submitted action is still unresolved. I will use the available status capability.')
            for call_id in unresolved: self.request_reconcile(self.operations[call_id], 'status')
        else:
            actions = [op for op in self.operations.values() if op['purpose'] == 'create']
            if actions:
                self.say('Action status: ' + '; '.join(f'{op["selection"]["title"]}: {op["status"].replace("_", " ")}' for op in actions) + '.', final=True)
            else:
                running = sum(op['status'] == 'running' for op in self.operations.values())
                self.say(f'{running} lookup(s) pending. No action has been submitted.' if running else 'No action has been submitted.', final=True)

    async def control(self, data):
        action = data.get('action')
        if action in ('pause', 'stop_work', 'cancel', 'cancel_action', 'speech_only', 'end'):
            if action != 'speech_only': self.interrupt_epoch += 1
            if action == 'cancel_action' and (not isinstance(data.get('call_id'), str) or not data['call_id']):
                raise ValueError('Cancelling a submitted action requires its exact call_id.')
            self.stop('cancel' if action == 'cancel_action' else action, action_id=data.get('call_id', ''))
        elif action == 'resume':
            self.input_floor_held = False
            self.floor_held = False
            self.paused = False
            self.speech_muted = False
            self.update_timer('resume')
            if self.manifest() and not self.missing() and not (self.results and self.result_current(self.results)):
                self.ensure_lookup()
            self._drain_results()
        elif action == 'status':
            self.report_status()
        elif action == 'select':
            if self.pending_inputs or self.floor_held or self.paused:
                self.say('The current input must be resolved before selecting an option.', clarification=True)
                return
            self.apply(Interpretation(intent='select', selection=data.get('option_id', '')), InputEvent(id=self.new_id('input'), type='text', seen_results=data.get('results_id')))
        elif action == 'book':
            if self.pending_inputs or self.floor_held or self.paused:
                self.say('The current input must be resolved before authorizing an action.', clarification=True)
                return
            self.apply(Interpretation(intent='commit'), InputEvent(id=self.new_id('authorization'), type='text', seen_results=data.get('results_id')))
        elif action == 'challenge':
            allowed = {'read_delay': (int, float), 'write_delay': (int, float), 'prepare_delay': (int, float),
                       'late_reads': (bool,), 'duplicate_result': (bool,), 'fail_next_read': (bool,), 'action_mode': (str,)}
            for key, value in data.get('config', {}).items():
                if key not in allowed or type(value) not in allowed[key]: raise ValueError('Invalid challenge setting.')
                if key.endswith('delay') and not 0.05 <= value <= 15: raise ValueError('Delay must be 0.05–15 seconds.')
                if key == 'action_mode' and value not in ('normal', 'delayed', 'too_late', 'unverifiable'): raise ValueError('Unknown action mode.')
                self.sandbox.config[key] = value
            self.emit('challenge_enabled', 'Sandbox conditions changed. Outcomes are determined by the service.', config=self.sandbox.config)
        elif action == 'duplicate_result':
            if self.sandbox.last_results:
                call_id = next(reversed(self.sandbox.last_results))
                self.handle_result(call_id, self.sandbox.last_results[call_id], self.new_id('repeat'))
        else:
            raise ValueError('Unknown control action.')

    async def close(self):
        self._closed = True
        if self.interpretation_task:
            self.interpretation_task.cancel()
        self.worker.cancel()
        for task in list(self.tasks): task.cancel()
        await asyncio.gather(self.worker, *list(self.tasks), return_exceptions=True)
        self.sandbox.close()
