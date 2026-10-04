"""Small, explicit native chains. Source data can fill a draft, never grant authority."""
from copy import deepcopy
import re
from urllib.parse import urlparse

from jsonschema import Draft202012Validator


def text(limit): return {'type': 'string', 'minLength': 1, 'maxLength': limit}


EXTRA_SPECS = {
    'compose_whatsapp': ('Open a WhatsApp draft to an explicitly supplied international phone number. body is the requested text. This NEVER sends; the user must review and tap Send.',
                         {'number': text(40), 'body': text(4000)}, ['number', 'body']),
    'open_url': ('Open the supplied http/https URL in Chrome, with the default browser as fallback. No arbitrary intent/file/javascript URLs. A handoff does not verify loading.', {'url': text(4000)}, ['url']),
    'play_store_search': ('Open a Play Store search for the requested app. Does not install or purchase anything.', {'query': text(200)}, ['query']),
    'directions': ('Open Maps directions with an explicit travel mode. This is a route preview, not verified navigation or a ride booking.',
                   {'destination': text(500), 'travel_mode': {'type': 'string', 'enum': ['driving', 'walking', 'bicycling', 'transit']}}, ['destination', 'travel_mode']),
    'share_text': ('Open a text share draft in the named installed app. If the app cannot accept text, fail honestly. The user chooses the recipient and sends it; never claim delivery.', {'app': text(100), 'body': text(4000)}, ['app', 'body']),
    'open_camera': ('Open the camera app. Does not capture or upload an image.', {}, []),
}
NEWS_SPEC = ('Fetch current news headlines from keyless Google News RSS. This is a read, not article verification.', {'topic': text(200)}, ['topic'])
CHAIN_ACTIONS = ['latest_news', 'compose_whatsapp', 'set_volume', 'open_app', 'open_url', 'media_search', 'play_store_search', 'directions', 'share_text', 'open_camera']
CHAIN_SPEC = ('Run 2–3 explicitly requested steps with individual receipts. Only the FINAL step may open another app; earlier steps may fetch latest_news or set_volume. Quote each command clause in order as user_request. For "find the latest on X and send it to NUMBER on WhatsApp", use latest_news(topic) then compose_whatsapp(number, use_latest_news=true); do not invent a body. That binds the newest returned headline, source and link directly into a draft. Stop/correction aborts remaining steps. Never replay completed or uncertain steps.',
              {'steps': {'type': 'array', 'minItems': 2, 'maxItems': 3, 'items': {'type': 'object', 'properties': {
                  'action': {'type': 'string', 'enum': CHAIN_ACTIONS}, 'user_request': text(4000),
                  'arguments': {'type': 'object', 'properties': {
                      'topic': text(200), 'number': text(40), 'body': text(4000), 'use_latest_news': {'type': 'boolean'},
                      'percent': {'type': 'integer', 'minimum': 0, 'maximum': 100}, 'query': text(500), 'url': text(4000), 'app': text(100),
                      'provider': {'type': 'string', 'enum': ['youtube', 'spotify']}, 'destination': text(500),
                      'travel_mode': {'type': 'string', 'enum': ['driving', 'walking', 'bicycling', 'transit']}}, 'additionalProperties': False}},
                  'required': ['action', 'user_request', 'arguments'], 'additionalProperties': False}}}, ['steps'])


def normalize(value):
    return ' '.join(re.sub(r"[^\w]+", ' ', str(value).casefold().replace('’', "'").replace("'s", '')).split())


def mentioned(value, words):
    return bool(normalize(value)) and (' ' + normalize(value) + ' ') in (' ' + normalize(words) + ' ')


def authorize_values(name, args, words):
    """Bind new native destinations/content to user words, not the model's own plan."""
    for field in {'media_search': ['query'], 'open_url': ['url'], 'play_store_search': ['query'],
                  'compose_whatsapp': ['body'], 'directions': ['destination'], 'share_text': ['app', 'body'],
                  'latest_news': ['topic']}.get(name, []):
        if field in args and not mentioned(args[field], words): raise ValueError(f'The {field} must come from the current request.')
    if name == 'open_url':
        url = urlparse(args['url'])
        if url.scheme not in ('https', 'http') or not url.hostname or url.username or url.password or any(c.isspace() for c in args['url']):
            raise ValueError('Use an explicit http or https URL without credentials.')
    if name == 'compose_whatsapp':
        if not re.search(r'\bwhatsapp\b', words, re.I): raise ValueError('Name WhatsApp explicitly for this draft.')
        raw = args['number']
        if not re.fullmatch(r'\+?[0-9 ()-]{7,40}', raw): raise ValueError('Supply a phone number with country code.')
        digits = re.sub(r'\D', '', raw)
        numbers = [re.sub(r'\D', '', match) for match in re.findall(r'\+?\d[\d ()-]{5,39}\d', words)]
        if not re.fullmatch(r'[1-9]\d{6,14}', digits) or digits not in numbers:
            raise ValueError('Use the explicitly supplied international WhatsApp number, not an unresolved contact.')
        args['number'] = digits
    if name == 'directions':
        modes = {'walking': r'walk(?:ing)?', 'driving': r'driv(?:e|ing)', 'bicycling': r'(?:bik(?:e|ing)|cycl(?:e|ing)|bicycling)', 'transit': r'(?:transit|public transport)'}
        if not re.search(r'\b' + modes[args['travel_mode']] + r'\b', words, re.I):
            raise ValueError('Ask for the travel mode when it was not specified.')


def prepare_chain(args, words, specs, authorizes):
    steps = deepcopy(args['steps'])
    cursor = 0
    for index, step in enumerate(steps):
        name, values, quote = step['action'], step['arguments'], step['user_request'].strip()
        if name not in CHAIN_ACTIONS: raise ValueError('Unsupported chain step.')
        start = words.casefold().find(quote.casefold(), cursor)
        gap = words[cursor:start] if start >= 0 else 'invalid'
        if not quote or not re.fullmatch(r'[\s,;.!]*(?:(?:and then|and|then)[\s,]+)?', gap, re.I):
            raise ValueError('Quote every command clause in order; no quoted or omitted instructions can authorize a chain.')
        cursor = start + len(quote)
        if index < len(steps) - 1 and name not in ('latest_news', 'set_volume'):
            raise ValueError('Only the final step may open another app. Return to THREAD for another handoff.')
        _, props, required = NEWS_SPEC if name == 'latest_news' else specs[name]
        props, required = deepcopy(props), list(required)
        if name == 'compose_whatsapp' and values.get('use_latest_news') is True:
            if index == 0 or steps[index - 1]['action'] != 'latest_news' or 'body' in values:
                raise ValueError('A news draft must directly follow its RSS lookup and cannot supply a model-written body.')
            props['use_latest_news'] = {'const': True}
            required.remove('body')
        errors = list(Draft202012Validator({'type': 'object', 'properties': props, 'required': required, 'additionalProperties': False}).iter_errors(values))
        if errors: raise ValueError(errors[0].message[:300])
        if not authorizes(name, quote): raise ValueError('Each chain step needs an explicit current command.')
        authorize_values(name, values, quote)
        if name == 'set_volume' and not mentioned(values['percent'], quote): raise ValueError('Supply the requested volume as a numeric percentage.')
        if name == 'open_app' and not mentioned(values['query'], quote): raise ValueError('The app name must match the request.')
        if name == 'media_search' and not mentioned(values['provider'], quote): raise ValueError('Name the media provider.')
    if not re.fullmatch(r'[\s.!?]*', words[cursor:]): raise ValueError('Finish or clarify the complete chain request first.')
    return steps


def authorize_watch(name, args, words):
    from .watches import cadence
    prefix = r'(?:(?:please|now)[, ]+)*(?:(?:can|could|would|will) you (?:please )?)?'
    patterns = {
        'create_watch': r'(?:every .+[, ]+(?:give|send|tell|notify|update) .+|(?:watch|follow|track|monitor|keep (?:me )?updated|(?:create|start|set up) (?:a )?watch|(?:give|send) me updates).+ every .+)',
        'list_watches': r'(?:list|show|what are)(?: me)?(?: my| the)? (?:active |saved )?watches',
        'stop_watch': r'(?:stop watching|stop (?:the |my )?watch|stop watch)(?: .+)?',
        'check_watch_now': r'(?:check|refresh)(?: (?:the|my))? (?:watch|watches)(?: .+)?',
    }
    if not re.fullmatch(prefix + patterns[name] + r'[.!?]*', words.strip(), re.I) or re.search(r"\b(?:if|unless|when|don't|do not|never mind|not yet|later|cancel)\b", words, re.I):
        raise ValueError('A Watch needs an explicit current command.')
    if args.get('topic') and not mentioned(args['topic'], words): raise ValueError('The Watch topic must match the request.')
    if args.get('id') and not mentioned(args['id'], words): raise ValueError('Use a topic named in the request, or omit the target for a single active Watch.')
    if name == 'create_watch':
        minutes = cadence(args)
        numbers = {'a': 1, 'an': 1, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'eight': 8, 'twelve': 12, 'fifteen': 15, 'thirty': 30, 'sixty': 60}
        def duration(match):
            value = numbers.get(match[1].lower())
            if value is None:
                try: value = float(match[1])
                except ValueError: return None
            return value * (60 if match[2].lower().startswith('hour') else 1440 if match[2].lower().startswith('day') else 1)
        period = re.search(r'\bevery\s+([\w.]+)\s+(minutes?|hours?|days?)\b', words, re.I)
        if not period or duration(period) != minutes: raise ValueError('The cadence must match the explicitly requested interval (15 minutes minimum).')
        stop = re.search(r'\b(?:for|stop after)\s+([\w.]+)\s+(minutes?|hours?|days?)\b', words, re.I)
        if (duration(stop) if stop else None) != args.get('stop_after'): raise ValueError('Keep the requested stop-after duration; do not invent or omit it.')
