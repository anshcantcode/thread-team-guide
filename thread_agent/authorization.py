"""Bounded English command evidence, independent of the model's action label.

Named objects belong to the declared capability. Unfamiliar capabilities can use
the canonical 'Submit the selected action' command without language metadata.
Unsupported phrasing preserves clear corrections and requests clarification.
"""
import re


# A manifest cannot redefine an acknowledgment such as 'yes' as permission.
ACTION_VERBS = frozenset('book reserve hold save store allocate issue file raise open create submit register order purchase schedule enroll dispatch send'.split())
STOP_WORK = frozenset(("don't book it", 'do not book it', "wait, don't", 'cancel the search', 'cancel the task', 'stop the search', 'stop the task'))


def normalize(text):
    return text.strip().casefold().replace('\u2019', "'") if isinstance(text, str) else ''


def _command(words, verbs, objects):
    verb = '|'.join(re.escape(v) for v in sorted(verbs, key=lambda v: (-len(v), v)))
    noun = '|'.join(re.escape(v) for v in sorted(objects, key=lambda v: (-len(v), v)))
    prefix = r'(?:(?:please|yes|okay|ok|now)[, .]*\s*)*(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?)?(?:go\s+ahead\s+and\s+)?'
    modifiers = r'(?:(?:another|additional|separate|new|selected|current|exact|first|second|third|fourth|one more)\s+)*'
    reference = r'(?:it|this|that|(?:(?:the|this|that|a|an|one)\s+)?' + modifiers + '(?:' + noun + '))'
    suffix = r'(?:\s+(?:for me|now|please))*[.!?]*'
    return bool(re.fullmatch(prefix + '(?:' + verb + r')\s+' + reference + suffix, words))


def explicit_write_request(text, tool, *, additional=False):
    words = normalize(text)
    if not words or tool is None or re.search(r"\b(?:don't|do not|not yet|hold off|never mind|cancel|wait)\b", words):
        return False
    leaf = tool.name.rsplit('.', 1)[-1].split('_')[0].casefold()
    verbs = set(tool.authorization_verbs) & ACTION_VERBS
    if leaf in ACTION_VERBS:
        verbs.add(leaf)
        if leaf in ('book', 'reserve', 'hold'): verbs.update(('book', 'reserve', 'hold'))
    # Generic create/submit cannot refer to a different capability's named object.
    matched = _command(words, {'create', 'submit'}, {'action', 'option'})
    if verbs:
        matched = matched or _command(words, verbs, {'action', 'option', *tool.authorization_objects})
    return matched and (not additional or bool(re.search(r'\b(?:another|additional|separate|one more)\b', words)))


def explicit_cancel_request(text, create_tool):
    words = normalize(text)
    if not words or create_tool is None or re.search(r"\b(?:don't|do not|not yet|hold off|never mind|wait)\b", words):
        return False
    return _command(words, {'cancel', 'undo', 'withdraw'}, {'action', *create_tool.authorization_objects})


def guard_interpretation(plan, words, manifest):
    """Return a safe proposal and refusal reason; never drop parsed corrections."""
    tool = manifest.tool('create') if manifest else None
    if plan.intent == 'speech_only' and not re.fullmatch(
            r'(?:please )?(?:stop (?:talking|speaking)|mute (?:your voice|speech)|be quiet)(?:[, .]+(?:but )?(?:keep (?:searching|working)|let (?:the )?(?:current )?(?:search|work) continue|continue (?:the )?(?:search|work)))?[.!]*', normalize(words)):
        return plan.model_copy(update={'intent': 'revise' if plan.changes or plan.remove else 'acknowledge'}), ''
    if plan.intent == 'cancel' and normalize(words).rstrip('.!') in STOP_WORK:
        return plan.model_copy(update={'intent': 'stop_work'}), ''
    refused = (plan.intent in ('commit', 'additional_action') and not explicit_write_request(words, tool, additional=plan.intent == 'additional_action'))
    refused = refused or (plan.intent == 'cancel' and not explicit_cancel_request(words, tool))
    if not refused:
        return plan, ''
    question = ('I kept the clear task details, but have not requested an action or cancellation. '
                'Review the updated details and current option first. To submit it, say "Submit the selected action"; '
                'to undo an existing action, say "Cancel that action".')
    return plan.model_copy(update={'intent': 'clarify', 'question': question}), question
