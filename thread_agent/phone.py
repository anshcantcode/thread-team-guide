"""Typed, session-bound Android actions. The phone reports effects, never the model."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import re

from jsonschema import Draft202012Validator

from .watches import WATCH_SPECS, host_watches, fetch_news
from .action_chains import EXTRA_SPECS, CHAIN_SPEC, authorize_values, authorize_watch, prepare_chain


def string(limit=300): return {'type': 'string', 'minLength': 1, 'maxLength': limit}
def integer(low, high): return {'type': 'integer', 'minimum': low, 'maximum': high}


SPECS = {
    **EXTRA_SPECS,
    'run_chain': CHAIN_SPEC,
    'set_alarm': ('Set an alarm in the phone Clock app. Ask AM or PM when a time such as five is ambiguous. Hours are 24-hour. The Clock app handles persistence, ringing and repeats.',
                  {'hour': integer(0, 23), 'minute': integer(0, 59), 'label': string(120), 'days': {'type': 'array', 'maxItems': 7, 'uniqueItems': True, 'items': integer(1, 7)}}, ['hour', 'minute', 'label']),
    'set_timer': ('Start a real phone Clock timer, not a session-only web timer.', {'seconds': integer(1, 86400), 'label': string(120)}, ['seconds', 'label']),
    'show_alarms': ('Open the phone Clock alarm list.', {}, []),
    'open_app': ('Open an installed app by its actual name. The phone resolves the name locally; if ambiguous it shows choices. Never guess package names.', {'query': string(100)}, ['query']),
    'web_search': ('Open a Google search on Android in the requested all/images/videos/news tab. Resolve a compound search-and-tab request to its final tab in ONE call. query is the user requested search, never an invented URL. For a follow-up such as images instead, omit query to retain this conversation\'s previous Google query. This is a browser handoff, not proof the page loaded.',
                   {'query': string(500), 'tab': {'type': 'string', 'enum': ['all', 'images', 'videos', 'news']}}, ['tab']),
    'media_search': ('Open a search inside YouTube or Spotify, with a web fallback. This searches; it does NOT play a track or video. For personal top-track playback use phone_spotify_top_track instead.',
                     {'provider': {'type': 'string', 'enum': ['youtube', 'spotify']}, 'query': string(500)}, ['provider', 'query']),
    'spotify_top_track': ('Find the user\'s top Spotify track by affinity and play it on their currently active controllable Spotify device. Set repeat-one ONLY if explicitly requested. short_term is about four weeks, medium_term six months, long_term one year. Default to medium_term and say the period. Needs connected Spotify and Premium. Read-back determines completion; never claim playback for needs_connection, needs_device or unknown. Connecting an account does not replay the old request.',
                          {'time_range': {'type': 'string', 'enum': ['short_term', 'medium_term', 'long_term']}, 'repeat': {'type': 'boolean'}}, ['time_range', 'repeat']),
    'spotify_control': ('Pause/resume Spotify or set repeat one/off on the active device. Follow-up repeat commands apply to Spotify, never to a booking. The provider verifies playback state. Cannot silently transfer to a different device.',
                        {'command': {'type': 'string', 'enum': ['pause', 'resume', 'repeat_one', 'repeat_off']}}, ['command']),
    'navigate': ('Open a map for the requested place or destination. Does not book transportation.', {'query': string(500)}, ['query']),
    'dial': ('Prepare a phone call in the dialer; the user presses Call. Requires a supplied phone number, not an invented number or an unresolved contact name.', {'number': string(40)}, ['number']),
    'compose_sms': ('Open a prefilled SMS draft. The user sends it. Never report the message as sent.', {'number': string(40), 'body': string(4000)}, ['number', 'body']),
    'compose_email': ('Open a prefilled email draft. The user sends it. Never report delivery.', {'recipient': string(320), 'subject': string(200), 'body': string(8000)}, ['recipient', 'subject', 'body']),
    'calendar_event': ('Open an event draft in the phone calendar. The user saves it. Require resolved start/end ISO 8601 timestamps with timezone offsets. Never claim it was saved.', {'title': string(200), 'start': string(40), 'end': string(40), 'location': string(500)}, ['title', 'start', 'end']),
    'set_volume': ('Change the phone media volume, with an actual read-back. Does not change alarm/ringer volume.', {'percent': integer(0, 100)}, ['percent']),
    'flashlight': ('Switch the phone torch on or off. Camera permission is needed.', {'enabled': {'type': 'boolean'}}, ['enabled']),
    'open_settings': ('Open the appropriate Android settings page. Android requires the user to change Wi-Fi/Bluetooth settings; never say a switch was changed by opening the page.', {'screen': {'type': 'string', 'enum': ['internet', 'bluetooth', 'display', 'notifications', 'assistant', 'battery']}}, ['screen']),
    'create_widget': ('Create a complete native home-screen widget from one or two result cards. Supports ticking multi-city world clocks, full sports match/innings/race histories and statistics, weather forecasts, countdowns, calculations, sources/news, plans, recipes, comparisons, notes and interactive checklists. Fetch or compose the requested content FIRST, then pass exact workspace result IDs. Sports uses every returned record, not just the first score. World clocks use lookup_world_clocks with all cities in ONE request. Custom informational widgets use publish_document with useful structured content. The phone previews the actual layout; the user pins it.',
                      {'title': string(60), 'result_ids': {'type': 'array', 'minItems': 1, 'maxItems': 2, 'uniqueItems': True, 'items': string(120)}}, ['title', 'result_ids']),
}

PHONE_INSTRUCTIONS = """
This connection is the THREAD Android app with a native phone bridge. Use the phone_* functions for
alarms, timers, opening apps, navigation, draft calls/messages/email/calendar, volume, torch and widgets.
Use phone_web_search for opening Google searches or changing their tab, phone_media_search for YouTube/Spotify searches,
and phone_spotify_top_track / phone_spotify_control for personal Spotify playback. A compound Google search plus a tab
change is one final search destination. Do not just call open_app and claim you searched or played music.
"Open YouTube and search for X" is ONE phone_media_search(provider=youtube, query=X), not open_app.
Use phone_compose_whatsapp for WhatsApp drafts, phone_open_url for Chrome, phone_play_store_search,
phone_directions with the requested travel mode, phone_share_text and phone_open_camera.
Use phone_run_chain for 2–3 explicit steps. Only its final step may open another app. A latest-news-to-WhatsApp
request is latest_news then compose_whatsapp(use_latest_news=true). The controller fills the draft from the
actual newest returned headline and link. Read per-step receipts; never call a draft sent or replay partial work.
Use one bounded workflow per command. Spotify credentials never go in function arguments. A needs_connection receipt
means the user must connect in THREAD Settings; a needs_device receipt means they must choose/start a Spotify device.
For real phone timers use phone_set_timer instead of lookup_timer. Phone actions are available only while
this connection remains active. An explicit command authorizes a simple action; do not ask again unless
information is ambiguous. 'Alarm for five' needs AM/PM clarification; never silently choose.
user_request must quote the latest verified user words exactly; base_revision is the latest task revision.
input_token must match the latest THREAD turn marker or returned state. A streaming caption cannot authorize a phone action.
Device action results distinguish completed, handed_off, needs_permission, ambiguous and failed.
handed_off means Android opened the requested app/action; it is not independent proof of saving or sending.
Never say a message was sent, calendar saved, widget pinned or alarm confirmed when the result only says
handed_off or prepared. Explain the actual next step briefly. Do not retry uncertain actions automatically.
For widgets, fetch the requested data first. Current workspace and widget_sources include exact result IDs.
widget_sources retains recent actual results, so two weather locations or two teams can share a widget.
Look up multiple subjects sequentially: wait for the first completed result / BACKEND UPDATE before
starting the next lookup. A started lookup is not yet a result. Then pass BOTH exact result IDs for a
two-subject widget; one ID includes only that one result. Respect their timestamps and check that the
selected results cover every requested subject before saying the widget is ready.
Use lookup_world_clocks for current city times (all requested cities in one locations array), get_recent_games
for a team's/player's requested number of recent records, or publish_document for any useful custom plan,
recipe, checklist, comparison or informational reference. Then call phone_create_widget in the SAME turn.
Do not stop at saying the data is available or telling the user to build it manually. If a source cannot
provide the requested records, explain the gap; do not fabricate records or replace them with weather.
You can polish dictation into a document and draft it in the user's messaging app. Do not send automatically.
You cannot silently read other apps, contacts, accounts, notifications or the screen. Ask the user to share
the desired content through Android's share menu. Arbitrary UI automation and privileged AppFunctions
execution are not connected. Never imply that a settings page or app launch completed a task inside it.
"""


def authorizes_phone(name, words):
    """Bounded complete commands. Unsupported or deferred wording asks for repair."""
    number = r'(?:\d+(?::\d{2})?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|twenty|thirty|forty|forty five|sixty|a|an)'
    time = number + r'(?:\s*(?:a\.?\s*m\.?|p\.?\s*m\.?|o.clock))?(?:\s+(?:today|tomorrow|in the morning|in the evening|at night))?'
    target = r'[^.!?;\n]{1,300}'
    patterns = {
        'set_alarm': r'(?:set|create|add) (?:an? |the )?alarm (?:for|at) ' + time,
        'set_timer': r'(?:set|start|create) (?:an? |the )?timer for ' + number + r' (?:seconds?|minutes?|hours?)',
        'show_alarms': r'(?:show|open) (?:my |the )?(?:alarms|alarm list)',
        'open_app': r'(?:open|launch) ' + target,
        'web_search': r'(?:(?:on google[, ]+)?(?:search|look)(?: on google| google)?(?: for)? ' + target + r'|google ' + target + r'|(?:open|show|switch to)(?: the)? (?:all|images?|videos?|news)(?: (?:tab|results))?(?: instead)?|(?:images?|videos?|news)(?: (?:tab|results))? instead)',
        'media_search': r'(?:(?:on (?:youtube|spotify)[, ]+)?search(?: (?:youtube|spotify))?(?: for)? ' + target + r'|open (?:youtube|spotify) (?:and )?search(?: for)? ' + target + ')',
        'spotify_top_track': r'(?:open|play|put on) (?:my |the )?(?:(?:most played|top|favourite|favorite)(?: spotify)?(?: (?:song|track))?(?: on spotify)?|spotify (?:most played|top|favourite|favorite)(?: (?:song|track))?)(?: from (?:this month|the last six months|this year))?(?: (?:and )?play (?:it|that))?(?: (?:on (?:a )?(?:loop|repeat)|on repeat one|on loop|again and again))?',
        'spotify_control': r'(?:(?:pause|resume|stop|play) (?:my )?(?:spotify|music on spotify)|(?:put|set) (?:spotify|(?:this|the) (?:song|track)) on repeat(?: one)?|(?:turn|switch) off (?:spotify )?repeat|(?:repeat|loop) (?:this|the) (?:song|track))',
        'navigate': r'(?:navigate|route|take me|direct me|show directions) to ' + target,
        'dial': r'(?:call|dial) [\d+() -]{3,40}',
        'compose_sms': r'(?:text|(?:draft|compose|write) (?:an? |the )?(?:text|sms|message))(?: ' + target + ')?',
        'compose_email': r'(?:email|(?:draft|compose|write) (?:an? |the )?(?:email|mail))(?: ' + target + ')?',
        'calendar_event': r'(?:schedule (?:an? |the )?(?:event|meeting)|(?:add|create|prepare) (?:an? |the )?(?:calendar )?(?:event|meeting))(?: ' + target + ')?',
        'set_volume': r'(?:set|change|turn|adjust|raise|lower) (?:the )?(?:media )?volume (?:to )?' + number + r'(?:\s*(?:percent|%))?',
        'flashlight': r'(?:turn|switch) (?:(?:the )?(?:flashlight|torch) (?:on|off)|(?:on|off) (?:the )?(?:flashlight|torch))',
        'open_settings': r'(?:open|show) (?:the )?(?:(?:internet|wi-fi|bluetooth|display|notification|assistant|battery) )?settings',
        'create_widget': r'(?:make|create|add|build) (?:an? |the )?(?:home.screen )?widget(?: (?:for|with|from|showing) ' + target + ')?',
        'compose_whatsapp': r'(?:(?:draft|compose|write|prepare) (?:an? |the )?(?:whatsapp )?(?:message|draft)(?: .+)?|(?:send|share) (?:it|this|the (?:news|headline|latest update)) to [\d+() -]+ on whatsapp|whatsapp [\d+() -]+ .+)',
        'open_url': r'open (?:the (?:url|link) )?https?://\S+(?: in chrome)?',
        'play_store_search': r'(?:search (?:the )?play store(?: for)?|find (?:an? )?app(?: called)?) .+',
        'directions': r'(?:(?:show|open|get)(?: me)? )?(?:walking|driving|bicycling|cycling|transit|public transport) directions to .+',
        'share_text': r'share .+ (?:to|with|in) .+',
        'open_camera': r'(?:open|launch)(?: the)? camera(?: app)?',
        'latest_news': r'(?:find|look up|get|fetch)(?: me)? (?:the )?(?:latest|news|latest news|latest headlines|latest updates)(?: on| about| for)? .+',
    }
    words = words.casefold().replace('\u2019', "'")
    if re.search(r"\b(?:never mind|nevermind|not yet|hold off|later|eventually|only want to know|just asking|don't|do not|cancel|wait)\b", words): return False
    if name not in ('compose_sms', 'compose_email', 'compose_whatsapp', 'share_text') and re.search(r'\b(?:if|unless|when|once|provided)\b', words): return False
    if re.search(r"\b(?:but|and)\s+(?:don't|do not|wait|hold off)\b", words): return False
    clauses = re.split(r'(?<=[.!?;])\s+|\n+', words)
    if any(re.match(r"(?:no\b|don't\b|do not\b|wait\b|not yet\b|hold off\b)", clause.strip()) for clause in clauses): return False
    prefix = r'(?:(?:please|now|yes|okay|ok)[, ]+)*(?:(?:can|could|would|will) you (?:please )?)?'
    return bool(re.fullmatch(prefix + patterns.get(name, r'(?!)') + r'(?: now| please)?[.!?]*', words.strip()))


def phone_schemas():
    return [{'name': 'phone_' + name, 'description': description,
             'parametersJsonSchema': schema(name)} for name, (description, _, _) in SPECS.items()]


def schema(name):
    _, properties, required = (SPECS | WATCH_SPECS)[name]
    return {'type': 'object', 'properties': {**deepcopy(properties), 'base_revision': integer(0, 1_000_000), 'user_request': string(12000), 'input_token': string(100)},
            'required': [*required, 'base_revision', 'user_request', 'input_token'], 'additionalProperties': False}


def watch_schemas():
    return [{'name': name, 'description': spec[0], 'parametersJsonSchema': schema(name)} for name, spec in WATCH_SPECS.items()]


class PhoneBridge:
    def __init__(self, live):
        self.live = live
        self.pending = {}
        self.outcomes = {}
        self.fingerprints = {}
        self.browser_context = {}

    def result(self, data):
        """Only a response on this live socket can resolve its own outstanding request."""
        request_id = data.get('request_id')
        pending = self.pending.get(request_id)
        if not pending or pending.done(): return False
        outcome = data.get('result')
        if not isinstance(outcome, dict) or len(json.dumps(outcome)) > 24000: return False
        if outcome.get('status') not in ('completed', 'handed_off', 'prepared', 'needs_permission', 'ambiguous', 'failed', 'cancelled', 'unknown'): return False
        if not isinstance(outcome.get('detail'), str) or not 1 <= len(outcome['detail']) <= 2000: return False
        pending.set_result(deepcopy(outcome))
        return True

    async def execute(self, call):
        live, session = self.live, self.live.session
        call_id = call.get('id', '')
        if call_id in self.outcomes: return self.outcomes[call_id]
        name = call.get('name', '').removeprefix('phone_')
        try:
            if name not in SPECS | WATCH_SPECS or not call_id: raise ValueError('Unknown action.')
            if name not in WATCH_SPECS and not live.phone: raise ValueError('This action needs an Android connection.')
            live.check_action_boundary(call)
            if live.recovery_only or not live.input_epoch:
                raise ValueError('A current user request is required for a phone action.')
            if live.user_speaking or live.block_old_calls: raise ValueError('Listen to the current correction before acting.')
            args = deepcopy(call.get('args', {}))
            errors = list(Draft202012Validator(schema(name)).iter_errors(args))
            if errors: raise ValueError(errors[0].message[:300])
            if args.pop('base_revision') != session.revision: raise ValueError('Task state changed. Use the current revision.')
            if args.pop('input_token') != live.input_token: raise ValueError('The action belongs to an earlier input turn.')
            quote = args.pop('user_request').strip()
            latest = live.current_user_words(verified=True)
            if not quote or quote.casefold() not in latest.casefold(): raise ValueError('Phone actions need an exact quote of the latest user request.')
            if name in WATCH_SPECS:
                authorize_watch(name, args, latest)
            elif name == 'run_chain':
                args['steps'] = prepare_chain(args, latest, SPECS, authorizes_phone)
            else:
                if not authorizes_phone(name, latest): raise ValueError('No explicit current command requested this phone action. Ask for the specific action; acknowledgment is not permission.')
                authorize_values(name, args, latest)
            if name == 'open_app' and re.search(r'\b(?:and|then)\b', latest, re.I):
                raise ValueError('This asks for more than opening an app. Use media_search for an app search or run_chain for explicit steps.')
            if name == 'web_search':
                if not re.search(r'\b(?:search|look|google)\b', latest, re.I):
                    requested = re.search(r'\b(images?|videos?|news|all)\b', latest, re.I).group(1).lower()
                    requested = {'image': 'images', 'video': 'videos'}.get(requested, requested)
                    if args['tab'] != requested: raise ValueError('The search tab must match the current correction.')
                    args['query'] = self.browser_context.get('query', '')
                elif not args.get('query'): raise ValueError('A new search requires its own explicit query. Do not reuse an earlier query.')
                explicit_tabs = re.findall(r'\b(?:and(?: then)?|then)\s+(?:open|show|switch to)\s+(?:the\s+)?(images?|videos?|news|all)\s+(?:tab|results)\b', latest, re.I)
                if explicit_tabs:
                    requested = {'image': 'images', 'video': 'videos'}.get(explicit_tabs[-1].lower(), explicit_tabs[-1].lower())
                    if args['tab'] != requested: raise ValueError('Use the final explicitly requested Google tab.')
                if not args['query']: raise ValueError('There is no Google query in this conversation yet. Ask what to search for.')
            if name == 'media_search' and not re.search(r'\b' + args['provider'] + r'\b', latest, re.I):
                raise ValueError('The user must name the media search provider.')
            if name == 'spotify_top_track':
                if args['repeat'] != bool(re.search(r'\b(?:loop|repeat|again and again)\b', latest, re.I)):
                    raise ValueError('The repeat setting must match the explicit loop/repeat request.')
                period = 'short_term' if re.search(r'\bthis month\b', latest, re.I) else 'long_term' if re.search(r'\bthis year\b', latest, re.I) else 'medium_term'
                if args['time_range'] != period: raise ValueError('Use the requested Spotify ranking period, or the declared six-month default.')
            if name == 'spotify_control':
                expected = ('repeat_off' if re.search(r'\boff\b', latest, re.I) else 'repeat_one' if re.search(r'\b(?:repeat|loop)\b', latest, re.I)
                            else 'pause' if re.search(r'\b(?:pause|stop)\b', latest, re.I) else 'resume')
                if args['command'] != expected: raise ValueError('The Spotify control does not match the current request.')
            if name == 'calendar_event':
                start, end = (datetime.fromisoformat(args[k]) for k in ('start', 'end'))
                if not start.tzinfo or not end.tzinfo or end <= start: raise ValueError('Resolve the event timezone and end after start.')
            if name == 'create_widget':
                available = {**live.widget_sources, **{r['id']: r for r in session.workspace.values()}}
                if any(rid not in available for rid in args['result_ids']): raise ValueError('Use exact current workspace result IDs. Fetch the requested information first.')
                args['results'] = [deepcopy(available[rid]) for rid in args.pop('result_ids')]
                if any(not r.get('items') or r.get('provenance') in ('synthetic', 'demo') or r.get('domain') in ('phone', 'travel', 'flights', 'rooms', 'device') for r in args['results']):
                    raise ValueError('Widgets need actual informational results or composed documents, not empty results, action receipts or demo inventory.')
            fingerprint = json.dumps([live.input_epoch, name, args], sort_keys=True)
            if fingerprint in self.fingerprints:
                return self.outcomes[self.fingerprints[fingerprint]]
            request_id = 'phone-' + call_id
            live.check_action_boundary(call)
            live.action_token_used = live.input_token
            epoch, token, client_input = live.input_epoch, live.input_token, getattr(live, 'client_input_id', '')
            def current():
                live.check_action_lifecycle(epoch)
                if live.block_old_calls or token != live.input_token or call_id in live.withdrawn_calls:
                    raise ValueError('The action was withdrawn or superseded.')
            session.emit('phone_action_requested', 'Requested a bounded action.', request_id=request_id, action=name, arguments=args, input_epoch=epoch)
            try:
                if name in WATCH_SPECS and not live.phone:
                    current()
                    outcome = await host_watches().execute(name, args)
                elif name == 'run_chain':
                    outcome = await self.chain(args['steps'], call_id, epoch, client_input, current)
                elif name.startswith('spotify_'):
                    from .spotify import spotify
                    def progress(steps):
                        session.emit('smart_action_progress', steps[-1]['label'], steps=steps)
                    outcome = await spotify.perform(getattr(live, 'spotify_handle', ''), name, args, current, progress)
                else:
                    current()
                    outcome = await self.device(name, args, request_id, call_id, epoch, client_input)
            except ValueError as exc:
                outcome = {'status': 'cancelled', 'detail': str(exc)[:500]}
            result = {'ok': outcome['status'] in ('completed', 'handed_off', 'prepared'), **outcome,
                      'request_id': request_id, 'action': name, 'state': live.task_context()}
            self.outcomes[call_id] = result
            self.fingerprints[fingerprint] = call_id
            if name == 'web_search' and outcome['status'] == 'handed_off': self.browser_context = deepcopy(args)
            card = {'id': request_id, 'domain': 'phone', 'arguments': args, 'source': 'THREAD on Android' if live.phone else 'THREAD host Watches', 'provenance': 'device' if live.phone else 'local',
                    'status': outcome['status'], 'retrieved_at': datetime.now(timezone.utc).isoformat(),
                    'items': [{'id': request_id, 'kind': 'phone_action', 'title': name.replace('_', ' ').capitalize(), **outcome}]}
            session.workspace['phone:' + request_id] = card
            session.emit('phone_action_result', outcome['detail'], request_id=request_id, action=name, status=outcome['status'])
            session.publish()
            return result
        except (ValueError, KeyError, TypeError) as exc:
            result = {'ok': False, 'status': 'failed', 'detail': str(exc)[:500], 'state': live.task_context()}
            self.outcomes[call_id] = result
            return result

    async def device(self, name, args, request_id, call_id, epoch, client_input):
        pending = asyncio.get_running_loop().create_future()
        self.pending[request_id] = pending
        try:
            await self.live.client('device_action', request_id=request_id, call_id=call_id, action=name, arguments=args,
                                   input_epoch=epoch, client_input_id=client_input)
            return await asyncio.wait_for(asyncio.shield(pending), 30)
        except asyncio.TimeoutError:
            return {'status': 'unknown', 'detail': 'The phone has not confirmed this action. Check the phone before retrying.'}
        finally:
            self.pending.pop(request_id, None)
            if not pending.done(): pending.cancel()

    async def chain(self, steps, call_id, epoch, client_input, current):
        receipts, news = [], []
        for index, step in enumerate(steps):
            name, args = step['action'], deepcopy(step['arguments'])
            request_id = f'phone-{call_id}-step-{index + 1}'
            try:
                current()
                if name == 'latest_news':
                    news = await asyncio.wait_for(fetch_news(args['topic']), 15)
                    outcome = {'status': 'completed' if news else 'failed', 'detail': f'Retrieved {len(news)} RSS headlines.' if news else 'No headlines returned; no draft was opened.', 'items': news[:3]}
                else:
                    if args.pop('use_latest_news', False):
                        if not news: raise ValueError('There is no returned headline for this draft.')
                        item = news[0]
                        args['body'] = f"{item['title']}\n{item['source']}\n{item['link']}"
                        if len(args['body']) > 4000: raise ValueError('The returned headline/link exceeds the draft limit.')
                    current()
                    outcome = await self.device(name, args, request_id, call_id, epoch, client_input)
            except asyncio.CancelledError:
                outcome = {'status': 'cancelled' if name == 'latest_news' else 'unknown',
                           'detail': 'Connection ended during the lookup.' if name == 'latest_news' else 'Connection ended before the phone confirmed this step. Check the phone; do not replay it automatically.'}
                receipts.append({'action': name, 'request_id': request_id, 'label': outcome['detail'], **outcome})
                receipts.extend({'action': remaining['action'], 'status': 'not_submitted', 'label': 'Not started after the connection ended.'} for remaining in steps[index + 1:])
                status = 'partial' if any(r['status'] in ('completed', 'handed_off', 'prepared') for r in receipts) else outcome['status']
                self.publish_chain(call_id, steps, receipts, status, outcome['detail'])
                raise
            except ValueError as exc:
                outcome = {'status': 'cancelled', 'detail': str(exc)[:400]}
            except Exception:
                outcome = {'status': 'failed', 'detail': 'This step failed; no success was confirmed.'}
            receipts.append({'action': name, 'request_id': request_id, 'label': outcome['detail'], **outcome})
            self.live.session.emit('smart_action_progress', outcome['detail'], steps=deepcopy(receipts))
            self.publish_chain(call_id, steps, receipts, 'running', outcome['detail'])
            if outcome['status'] not in ('completed', 'handed_off', 'prepared'):
                receipts.extend({'action': remaining['action'], 'status': 'not_submitted', 'label': 'Not started after the previous step stopped.'} for remaining in steps[index + 1:])
                status = 'partial' if any(r['status'] in ('completed', 'handed_off', 'prepared') for r in receipts) else outcome['status']
                return {'status': status, 'detail': 'Chain stopped. ' + outcome['detail'] + ' Earlier receipts remain valid; remaining steps were not submitted.', 'steps': receipts}
        return {'status': receipts[-1]['status'], 'detail': receipts[-1]['detail'], 'steps': receipts}

    def publish_chain(self, call_id, steps, receipts, status, detail):
        request_id = 'phone-' + call_id
        self.live.session.workspace['phone:' + request_id] = {
            'id': request_id, 'domain': 'phone', 'arguments': {'steps': deepcopy(steps)},
            'source': 'THREAD on Android', 'provenance': 'device', 'status': status,
            'retrieved_at': datetime.now(timezone.utc).isoformat(),
            'items': [{'id': request_id, 'kind': 'phone_action', 'title': 'Action chain', 'status': status,
                       'detail': detail, 'steps': deepcopy(receipts)}]}
        self.live.session.publish()
