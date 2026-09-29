"""Bounded, descriptor-based evidence checks for state-changing proposals.

Language interpretation remains the planner's job. These checks independently
reject a model label/quote without a current, affirmative user command.
"""
from __future__ import annotations

import json
import math
import re

from .schema import call_key, scalar_fields, validate_args


def words(text: str) -> str:
    return " ".join(text.casefold().replace("\u2019", "'").split())


def contains_value(value: str, text: str) -> bool:
    value = words(value)
    return bool(value) and re.search(r"(?<![\w-])" + re.escape(value) + r"(?![\w-])", words(text)) is not None


_CORRECTION_FILLER = {"wait", "actually", "instead", "change", "make", "that", "this", "sorry", "scratch", "rather",
                      "please", "just", "want", "need", "also", "then", "with", "from", "into", "have", "like", "know",
                      "okay", "well", "sure", "mean", "meant", "update", "switch", "those", "them", "these", "what"}
_NUMBER_WORDS = {"zero", "four", "five", "three", "seven", "eight", "nine", "eleven", "twelve", "thirteen", "fourteen",
                 "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty", "thirty", "forty", "fifty",
                 "sixty", "seventy", "eighty", "ninety", "hundred", "thousand", "million", "double", "triple"}


def _corrects_other_target(step: dict, correction: str, other_commands: str, own_command: str) -> bool:
    """A later correction that restates a different target of the cited request.

    "Set the filter so pets are allowed and set the max price to 3,000 ... wait,
    actually change the max price to 3500 instead": the correction names another
    thing the cited request named (the max price) and never any word of this
    step's values, so it leaves the pets write standing. A pronoun correction
    ("make it savings instead") names nothing shared and still voids the command.
    """
    parts = set()
    for _, value in scalar_fields(step.get("args", {})):
        if isinstance(value, bool):
            continue
        parts |= {part for part in re.split(r"[\s_\-,./]+", str(value).casefold()) if len(part) >= 3 or part.isdigit()}
    if not parts or re.search(r"\b(?:no|not|don't|dont|never|cancel|stop)\b", words(correction)):
        return False
    said = set(re.findall(r"[a-z0-9]+", words(correction)))
    values = [value for _, value in scalar_fields(step.get("args", {})) if isinstance(value, str)]
    if (parts & said or any(contains_value(part, correction) for part in parts)
            or any(contains_identifier(value, correction) for value in values)
            or {value.casefold() for value in values} & {run.casefold() for run in spelled_runs(correction)}):
        return False
    # Compare named targets before their value-setting preposition, never new
    # values ("change my address to Phone Street" does not correct a phone).
    target_pattern = r"\b(?:" + "|".join(_IMPERATIVES) + r")\s+([^.!?;]+?)\s+(?:to|from|as)\b"
    target = re.search(target_pattern, words(correction))
    if target is None:
        return False
    other_targets = " ".join(re.findall(target_pattern, words(other_commands)))
    said = set(re.findall(r"[a-z0-9]+", target[1]))
    # Shared words in this very command ("address", "cart") do not identify a
    # different target. Require a word exclusive to another cited target.
    shared = ({word for word in said if len(word) >= 4 and word not in _CORRECTION_FILLER
               and word not in _NUMBER_WORDS and not word.isdigit()}
              & set(re.findall(r"[a-z0-9]+", other_targets))
              - set(re.findall(r"[a-z0-9]+", words(own_command))))
    return bool(shared)


_DIGIT_WORDS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
                "six": "6", "seven": "7", "eight": "8", "nine": "9"}


_SHORT_WORDS = {"is", "it", "at", "an", "as", "be", "by", "do", "go", "he", "if", "in", "me", "my", "no", "of", "on",
                "or", "so", "to", "up", "us", "we", "am", "are", "was", "its", "the", "and", "for", "but", "not", "you",
                "all", "can", "her", "his", "has", "had", "how", "our", "out", "one", "two", "six", "ten", "day", "now",
                "see", "who", "why", "yes", "too", "get", "got", "let", "may", "per", "off", "any", "few", "new", "old",
                "pm", "am", "mr", "ms", "dr", "st", "oh", "ok", "hi", "her", "him", "she", "way", "yet", "end", "ago"}


def spelled_runs(text: str) -> set[str]:
    """Compact forms of maximal runs of individually spoken letters/digits.

    "item J nine" -> j9, "A-B-C-1-2-3" -> abc123. A run needs a lone letter and at
    least two tokens. Runs are maximal, so a prefix of a longer spelling never
    matches. The one exception is a space-separated leading article "a" (as in
    "add a J nine"), which is also tried without the article. A spelling alphabet
    word names its letter: "v as in vector-4-4" -> v44.
    """
    source = re.sub(r"\b([a-z])\s+as\s+in\s+[a-z]+\b", r"\1", words(text))
    tokens = list(re.finditer(r"[a-z0-9]+", source))
    # A short letter-digit chunk ("p5" in ASR's "P5-2") is part of a spelling too.
    single = [bool(re.fullmatch(r"[a-z]|\d+|[a-z]\d{1,3}|\d{1,3}[a-z]", token[0])) or token[0] in _DIGIT_WORDS
              for token in tokens]
    runs, run, segment = set(), [], 0

    def flush():
        if len(run) >= 2 and any(re.fullmatch(r"[a-z]|[a-z]\d{1,3}|\d{1,3}[a-z]", t[0]) for t in run):
            runs.add("".join(_DIGIT_WORDS.get(t[0], t[0]) for t in run))
            if run[0][0] == "a" and source[run[0].end():run[1].start()] == " " and len(run) >= 3:
                runs.add("".join(_DIGIT_WORDS.get(t[0], t[0]) for t in run[1:]))

    def segment_from(index):
        """Spelled tokens from index up to the next comma or unspelled word."""
        count = 0
        while index + count < len(tokens) and single[index + count]:
            if count and "," in source[tokens[index + count - 1].end():tokens[index + count].start()]:
                break
            count += 1
        return count

    joined_by_word = False
    for index, token in enumerate(tokens):
        # "B7, two of them" ends the identifier before an explicit count phrase.
        # ASR may omit the comma; a quantity must never complete a product ID.
        if (run and not joined_by_word and "-" not in source[run[-1].end():token.start()]
                and (token[0].isdigit() or token[0] in _DIGIT_WORDS)
                and re.match(r"\s+(?:of\s+(?:them|those|these|it|each)|units?|pieces?|copies)\b", source[token.end():])):
            flush()
            run, segment = [], 0
            continue
        if run and token[0] in {"dash", "hyphen"} and index + 1 < len(tokens) and single[index + 1]:
            joined_by_word = True  # A spoken separator: the next character continues this spelling.
            continue
        gap = source[run[-1].end():token.start()] if run else ""
        adjacent = bool(run) and (joined_by_word or re.fullmatch(r"[\s,\-]*", gap) is not None)
        joined_by_word = False
        # ASR writes one comma per spoken character ("A, B, C, 1, 2, 3"). A comma
        # between two multi-token spellings ("not J four four, J four five")
        # separates two identifiers instead.
        if adjacent and "," in gap and segment > 1 and segment_from(index) > 1:
            adjacent = False
        if single[index] and (not run or adjacent):
            segment = segment + 1 if run and "," not in gap else 1
            run.append(token)
            continue
        flush()
        run, segment = ([token], 1) if single[index] else ([], 0)
    flush()
    # "DL. / 555.": ASR can end a segment inside one spelling, so a short letters-only
    # chunk, a sentence break and a digits-only chunk also form a run.
    # Ordinary short words ("is.", "it.") never start such a spelling.
    for match in re.finditer(r"(?<![a-z0-9'])([a-z]{2,3})\.\s+(\d{2,6})(?=\s*(?:[.!?;](?:\s|$)|$))", source):
        # The digits must be a complete bare segment, not a price/quantity or
        # the prefix of a decimal, hyphenated ID, or another numeric segment.
        following = source[match.end():]
        continued = re.match(r"\s*[.!?;]\s+(?:\d+|" + "|".join(_DIGIT_WORDS)
                             + r"|[a-z](?=\s*(?:[.!?;]|$|(?:to|into)\b)))\b", following)
        if continued and re.match(r"\s+(?:of\s+(?:them|those|these|it|each)|units?|pieces?|copies)\b",
                                  following[continued.end():]):
            continued = None  # A separately stated quantity is not an ID character.
        if match[1] not in _SHORT_WORDS and not continued:
            runs.add(match[1] + match[2])
    return runs


def contains_identifier(value: str, text: str) -> bool:
    """A compact identifier equals one complete spoken spelling in the text."""
    compact = value.casefold() if isinstance(value, str) else ""
    if not re.fullmatch(r"[a-z0-9]{2,}", compact) or not re.search(r"[a-z]", compact):
        return False
    return compact in spelled_runs(text)


def truncated_identifier(value: str, text: str) -> bool:
    """A value that is only part of a longer spoken spelling ("M" of "M four")."""
    if not isinstance(value, str):
        return False
    # A value copied as its spoken spelling ("m four") is compared in compact form.
    compact = "".join(_DIGIT_WORDS.get(token, token) for token in re.split(r"[\s,\-]+", value.casefold()) if token)
    if not re.fullmatch(r"[a-z0-9]+", compact):
        return False
    runs = spelled_runs(text)
    return compact not in runs and any(compact in run for run in runs)


def identifier_field(name: str, descriptor: object) -> bool:
    description = descriptor.get("description", "") if isinstance(descriptor, dict) else ""
    return str(name).endswith(("_id", "_code", "_number")) or "identifier" in str(description).lower()


def turn_clauses(texts: list[tuple[int, str]]) -> list[dict]:
    """Deterministic clauses of the current turn with immutable source provenance.

    Offsets index the words()-normalized turn joined by single spaces. Sentence
    ends are [.!?;] before whitespace/end; commas before whitespace also end a
    clause. A message without final punctuation continues its sentence into the
    next message, because ASR often splits one sentence into fragments. IDs are
    "<original message_index>.<ordinal>" and stay stable while the turn grows.
    """
    rows, sentence, offset = [], 0, 0
    for index, text in texts:
        normalized = words(text) if isinstance(text, str) else ""
        if not normalized:
            continue
        ordinal, start = 0, 0
        boundaries = [(match.end(), match[0] != ",")
                      for match in re.finditer(r"(?:[.!?;]+|,)(?=\s|$)", normalized)]
        if not boundaries or boundaries[-1][0] != len(normalized):
            boundaries.append((len(normalized), False))
        for end, closes_sentence in boundaries:
            piece = normalized[start:end]
            lead = len(piece) - len(piece.lstrip())
            if re.search(r"\w", piece):
                rows.append({"clause_id": f"{index}.{ordinal}", "message_index": index, "sentence": sentence,
                             "text": piece.strip(), "start": offset + start + lead,
                             "end": offset + start + lead + len(piece.strip())})
                ordinal += 1
            if closes_sentence:
                sentence += 1
            start = end
        offset += len(normalized) + 1
    return rows


def _language_only(source):
    """JSON argument values are data, not quoted or negated user instructions."""
    decoder = json.JSONDecoder()
    chars, index = list(source), 0
    while index < len(source):
        if source[index] in "[{" and (index == 0 or not re.match(r"[\w.\]]", source[index - 1])):
            try:
                _, length = decoder.raw_decode(source[index:])
                chars[index:index + length] = " " * length
                index += length
                continue
            except ValueError:
                pass
        index += 1
    return "".join(chars)


def _verified_conditions(source, selection):
    """Only exact equality conditions proved by a validated result selection."""
    if not re.search(r"\bif\b", source):
        return source
    if not selection:
        return None
    pattern = r"\bif\s+(?:the\s+)?([a-z][a-z_ ]*?)\s+(?:is|equals?)\s+(?:exactly\s+)?(-?\d+(?:\.\d+)?|true|false|[a-z]+)(?=[.!?;]|$)"
    chars = list(source)
    for match in re.finditer(pattern, source):
        field, expected = match[1].strip(), match[2]
        try:
            expected = json.loads(expected)
        except ValueError:
            pass
        verified = any(path.rsplit(".", 1)[-1].replace("_", " ").casefold() == field
                       and type(actual) is type(expected) and actual == expected
                       for path, actual in selection.items())
        if not verified:
            return None
        chars[match.start():match.end()] = " " * len(match[0])
    scrubbed = "".join(chars)
    return None if re.search(r"\bif\b", scrubbed) else scrubbed


# A price condition the user tied to this request's own lookup ("if you find one
# under 50 dollars, add two"). Verified only against a returned price.
_PRICE_KEY = re.compile(r"(?:^|_)(?:price|cost|fare|amount|total|rent)$")
_NUMERIC_CONDITION = re.compile(
    r"\bif\s+(?:you\s+(?:can\s+)?find\s+(?:one|something|anything|any|a\s+[a-z]+)"
    r"(?:\s+(?:that's|that\s+is|which\s+is|that\s+costs|for))?"
    r"|it(?:'s|\s+is|\s+costs)|(?:the\s+)?(?:price|cost|fare|rent)\s+is"
    r"|(?P<plural>everything(?:'s|\s+is|\s+costs)|all\s+of\s+them\s+(?:are|cost)|they(?:'re|\s+are|\s+cost))"
    r"|there(?:'s|\s+is|\s+happens\s+to\s+be)\s+(?:a|an|one)(?:\s+[a-z]+)?)\s+"
    r"(?P<op>under|below|less\s+than|cheaper\s+than|over|above|more\s+than|at\s+most|no\s+more\s+than|at\s+least)\s+")
# A number with another unit is not a price ("if it's under 30 minutes").
_OTHER_UNIT = re.compile(r"\s*(?:minutes?|mins?|hours?|hrs?|seconds?|miles?|km|kilomet(?:er|re)s?|percent|%|days?|"
                         r"weeks?|months?|years?|degrees?|bedrooms?|beds?|people|persons?|items?|units?|pounds?|"
                         r"euros?|yen)\b")
_SMALL_NUMBERS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                  "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
                  "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}


def _leading_amount(text):
    """The amount that starts text, in digits or words: (value, length) or None.

    "$50", "1,500", "fifty", "twenty-five", "a hundred", "fifteen hundred",
    "two thousand five hundred". Nothing is inferred from context.
    """
    digits = re.match(r"\s*\$?(\d[\d,]*(?:\.\d+)?)(?![\d,.]*\d)", text)
    if digits:
        return float(digits[1].replace(",", "")), digits.end()
    total = current = 0
    started, end, position = False, None, 0
    for token in re.finditer(r"[a-z]+", text[:80]):
        gap = text[position:token.start()]
        if not re.fullmatch(r"\s*\$?" if not started else r"[\s-]*", gap):
            break
        word = token[0]
        if word in _SMALL_NUMBERS:
            current += _SMALL_NUMBERS[word]
        elif word in _TENS:
            current += _TENS[word]
        elif word == "hundred" and (started or current):
            current = max(current, 1) * 100
        elif word == "thousand" and (started or current):
            total, current = total + max(current, 1) * 1000, 0
        elif word == "a" and not started and re.match(r"\s+(?:hundred|thousand)\b", text[token.end():]):
            current = 1
        elif word == "and" and started:
            position = token.end()
            continue
        else:
            break
        started, end, position = True, token.end(), token.end()
    return (float(total + current), end) if started else None
_COMPARISONS = {"under": lambda price, n: price < n, "below": lambda price, n: price < n,
                "less than": lambda price, n: price < n, "cheaper than": lambda price, n: price < n,
                "over": lambda price, n: price > n, "above": lambda price, n: price > n,
                "more than": lambda price, n: price > n, "at most": lambda price, n: price <= n,
                "no more than": lambda price, n: price <= n, "at least": lambda price, n: price >= n}


def _price_objects(results, *, require_complete=False):
    """Returned finite prices; incomplete universal option lists carry None."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            prices = [value for key, value in node.items() if type(value) in (int, float)
                      and (type(value) is int or math.isfinite(value)) and _PRICE_KEY.search(str(key))]
            if len(prices) == 1:
                found.append((node, prices[0]))
            elif require_complete and any(_PRICE_KEY.search(str(key)) for key in node):
                found.append((node, None))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            if require_complete and any(isinstance(item, dict) and any(_PRICE_KEY.search(str(key)) for key in item)
                                        for item in node):
                # One missing price in a returned option list prevents proving
                # "all/everything" from just its conveniently priced siblings.
                found.extend((item if isinstance(item, dict) else {}, None) for item in node
                             if not isinstance(item, dict) or not any(_PRICE_KEY.search(str(key)) for key in item))
            for value in node:
                walk(value)
    for result in results:
        walk(result)
    return found


def _verified_price_conditions(source, step, lookups, pending, falsify_only=False):
    """Blank price conditions a returned price proves; report false or pending ones.

    The object is the returned one this step names (an argument value equal to one
    of its fields); without such a link, only a single returned priced object counts.
    """
    chars, status = list(source), "ok"
    values = {str(value) for _, value in scalar_fields(step.get("args", {})) if isinstance(value, str)}
    for match in _NUMERIC_CONDITION.finditer(source):
        amount = _leading_amount(source[match.end():])
        if amount is None:
            continue  # Not a price this rule understands: it stays a condition.
        n, length = amount
        span_end = match.end() + length
        currency = re.match(r"\s*(?:dollars?|bucks|usd)\b", source[span_end:])
        if currency:
            span_end += currency.end()
        elif _OTHER_UNIT.match(source[span_end:]):
            continue
        # A proved numeric prefix is not proof of the whole condition. Keep
        # "and in stock", "including shipping", an unfinished decimal, etc.
        # conditional unless the amount ends here or a clear consequent follows.
        rest = source[span_end:]
        boundary = r"\s*,?\s*(?:(?:please|thanks|thank you)\s*)?(?:[.!?;]|$)"
        consequent = (r"\s*,?\s*(?:(?:and|then|please|also|go ahead and)\s+)*"
                      r"(?:" + "|".join(_IMPERATIVES) + r")\b")
        complete = re.match(boundary, rest) or re.match(consequent, rest)
        if not falsify_only and not complete:
            continue  # (A false price prefix still falsifies the whole conjunction.)
        objects = _price_objects(lookups, require_complete=bool(match["plural"]))
        linked = [price for node, price in objects if values & {str(item) for item in node.values()}]
        prices = ([price for _, price in objects] if match["plural"] else
                  linked or ([objects[0][1]] if len(objects) == 1 else []))
        phrase = source[match.start():span_end]
        if not prices or any(price is None for price in prices):
            return None, ("pending" if pending else "unverified"), phrase
        check = _COMPARISONS[" ".join(match["op"].split())]
        if not all(check(price, n) for price in prices):
            return None, "false", phrase
        if match["plural"] and pending:
            return None, "pending", phrase
        if complete:
            chars[match.start():span_end] = " " * (span_end - match.start())
    return "".join(chars), status, ""


def _single_text_command(clause, step, tool):
    """A literal whole phrase for a sole string field; no inferred arguments."""
    properties = tool.get("args", {})
    if not isinstance(properties, dict) or len(properties) != 1:
        return None
    spec = next(iter(properties.values()))
    if not isinstance(spec, dict) or spec.get("type") != "string":
        return None
    field = next(iter(properties))
    match = re.fullmatch(r"\s*(?:please\s+)?([a-z]+)\s+([^.!?;]+?)\.?\s*", clause, re.I)
    if match is None:
        return None
    value = match[2].strip()
    destination = re.search(r"\s+(?:to|in|on)\s+(?:my|the|our)\s+([\w -]+)$", value, re.I)
    if destination:
        descriptor = str(tool.get("description", "")) + " " + str(step.get("api_name", "")).replace("_", " ")
        if not contains_value(destination[1], descriptor):
            return None
        value = value[:destination.start()].strip()
    if (not re.fullmatch(r"[\w-]+(?:\s+[\w-]+)*", value)
            or re.search(r"\b(?:it|this|that|them|him|her|those|these|selected|chosen|and|or|then|but|also)\b", value, re.I)):
        return None
    args = {field: value}
    candidate = {"api_name": step.get("api_name"), "args": args, "authorization": {"quote": clause}}
    if validate_args(tool, args) or not _plain_authorization_grant(candidate, tool, [(0, clause)]):
        return None
    return match[1].casefold(), args


def _recent_speech_turns(history):
    """Keep boundary evidence; incomplete/nontext sources are not silently erased."""
    turns, chunks = [], []
    for message in history:
        kind, payload = message.get("event_type"), message.get("payload", {})
        text = payload.get("text")
        if kind not in {"user_speech_chunk", "interruption"} or not isinstance(text, str):
            turns.append(None)
            chunks = []
        elif text.strip():
            chunks.append(text)
            if kind == "interruption" or payload.get("end_of_turn") is True:
                turns.append(" ".join(chunks))
                chunks = []
        elif kind == "interruption" and chunks:
            turns.append(None)
            chunks = []
    if chunks:
        turns.append(None)
    return turns[-2:]


def _replacement_scope(step, tool, texts, history):
    """Recognize explicit cancellation plus a complete literal 'instead' command.

    This path only accepts a sole string argument. The ledger is checked before
    admitting it; canceled prose never establishes that an effect was undone.
    """
    if step.get("result_bindings"):
        return None
    raw = " ".join(text for _, text in texts)
    previous = _recent_speech_turns(history)
    if any(turn is None for turn in previous):
        return None
    pair = re.fullmatch(r"\s*(?P<cancel>(?:no\s*,\s*)?(?:do not|don't)\s+[^.!?;]+)\.\s*"
                        r"(?P<new>.+?)\s+instead\.?\s*", raw, re.I | re.S)
    if pair:
        match, canceled = pair, pair["cancel"]
        old_source = previous[-1] if previous else None
    else:
        match = re.fullmatch(r"\s*(?P<new>[^.!?;]+?)\s+instead\.?\s*", raw, re.I | re.S)
        if match is None or not previous:
            return None
        canceled = previous[-1]
        old_source = previous[-2] if len(previous) > 1 else None
    cancellation = re.fullmatch(r"\s*(?:no\s*,\s*)?(?:do not|don't)\s+([^.!?;]+?)\.?\s*", canceled, re.I)
    if cancellation is None:
        return None
    old = _single_text_command(cancellation[1], step, tool)
    new = _single_text_command(match["new"], step, tool)
    if (old is None or new is None or old[0] != new[0]
            or call_key("", new[1], write=True) != call_key("", step.get("args", {}), write=True)
            or call_key("", old[1], write=True) == call_key("", new[1], write=True)):
        return None
    if old_source is not None:
        original = _single_text_command(old_source, step, tool)
        field = next(iter(old[1]))
        if (original is None or original[0] != old[0]
                or not contains_value(old[1][field], original[1][field])
                or call_key("", original[1], write=True) == call_key("", new[1], write=True)):
            return None
    scoped, offset = [], 0
    for index, text in texts:
        start = max(offset, match.start("new"))
        if start < offset + len(text):
            scoped.append((index, text[start - offset:]))
        offset += len(text) + 1
    return scoped


# Qualifiers that scope a whole request: conditions, hypotheticals, reported or
# questioned commands. Anywhere in the turn they block write authority unless a
# selected result verifies the exact condition. Sequencing "after that" is not one.
_SCOPE = (r"\b(?:if|unless|until|when|whenever|after(?!\s+that\b|wards?\b)|once|provided|assuming|as long as|only\s+then|"
          r"in case|maybe|might|perhaps|could i|should i|would i|suppose|imagine|hypothetical(?:ly)?|example|"
          r"said|says|told)\b")
# Local retractions/holds. They void the command they follow unless a later
# cited clause restates the effective request; they never appear inside a citation.
_RETRACT_WORDS = ("no", "nope", "not", "don't", "dont", "do not", "never", "wait", "hold on", "hold off", "sorry",
                  "actually", "scratch that", "never mind", "nevermind", "forget", "cancel", "stop", "instead",
                  "hang on", "one second", "one sec", "just a second", "just a sec",
                  "let me think", "let me see", "let me check")
# Cancellations withdraw the whole action: a later modifier ("make it one") can
# refine a corrected command but never revive a cancelled one.
_CANCEL_WORDS = ("don't", "dont", "do not", "never", "hold off", "scratch that", "never mind", "nevermind",
                 "forget", "cancel", "stop")
_NEGATION = r"\b(?:don't|dont|do not|never|not|no longer|won't|wouldn't|shouldn't|can't|cannot|stop)\s+"
_PRONOUN_VALUES = {"it", "this", "that", "them", "him", "her", "those", "these", "one", "ones",
                   "selected", "chosen", "first", "second", "third"}
_COUNT_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "a couple of": 2, "a dozen": 12}


def _tool_verbs(step, tool):
    description = str(tool.get("description", ""))
    name = str(step.get("api_name", "")).rsplit(".", 1)[-1]
    verbs = set()
    first = re.match(r"\s*([a-zA-Z]+)\b", description)
    if first:
        verbs.add(first[1].casefold())
    verbs.add(re.split(r"[_\-]", name)[0].casefold())
    # Small language equivalences, independent of domains or tool names.
    for group in ({"book", "reserve"}, {"create", "open", "file", "submit"},
                  {"cancel", "undo", "withdraw"}, {"buy", "purchase", "order"},
                  {"send", "dispatch"}, {"delete", "remove"}, {"add", "put", "include"},
                  {"update", "modify", "set", "change", "switch", "adjust", "edit", "enable", "turn", "swap", "replace", "move",
                   # Moving a setting's value: "raise the max price", "bump up the bedrooms".
                   "raise", "increase", "bump", "lower", "decrease", "reduce"}):
        if verbs & group:
            verbs.update(group)
    return verbs - {"get", "find", "search", "lookup", "list", "check", "read", "show", "retrieve", "tool", "api", ""}


def _retraction_pattern(verbs):
    # A tool's own verb ("cancel", "stop") is a command there, not a retraction.
    return r"\b(?:" + "|".join(re.escape(item) for item in _RETRACT_WORDS if item not in verbs) + r")\b"


def command_head(command):
    """Direct command, excluding later assertions unless the gate kept a correction."""
    parts = re.split(r"[.!?;](?=\s|$)|\band\b", command, maxsplit=1)
    # The full gate checks corrections before this value-evidence helper runs.
    if len(parts) == 2 and re.search(_retraction_pattern(set()), parts[1]):
        return command
    return parts[0]


def _cited_clauses(evidence, clauses, source, texts):
    """Resolve citations to existing current-turn clauses; never repair a quote."""
    if "clauses" in evidence:
        ids = evidence["clauses"]
        known = {row["clause_id"]: position for position, row in enumerate(clauses)}
        if (not isinstance(ids, list) or not ids or len(ids) > 12
                or any(not isinstance(item, str) or item not in known for item in ids)):
            return None
        # A clause cited twice adds nothing, and order carries no authority: the
        # region runs from the earliest to the latest cited clause either way, so
        # sorting only widens what every later check inspects.
        positions = sorted({known[item] for item in ids})
        return [clauses[position] for position in positions], None
    if not isinstance(evidence.get("quote"), str):
        return None
    quote = words(evidence["quote"])
    if len(quote) < 4:
        return None
    if "message_index" in evidence:
        if type(evidence["message_index"]) is not int:
            return None
        cited = [text for index, text in texts if index == evidence["message_index"]]
        if not cited or quote not in words(" ".join(cited)):
            return None
    start = source.find(quote)
    if start < 0:
        return None
    end = start + len(quote)
    cited = [row for row in clauses if row["start"] < end and row["end"] > start]
    return (cited, (start, end)) if cited else None


def count_mentions(command):
    """Direct item-count phrases in order: "add two", "two of them", "make it one", "just one"."""
    number = r"(\d+|" + "|".join(sorted(map(re.escape, _COUNT_WORDS), key=len, reverse=True)) + r")"
    patterns = [r"^\w+\s+(?:(?:just|only)\s+)?" + number + r"\b(?!\s*(?:dollars?|percent|%|minutes?|hours?|days?)\b)",
                r"\b" + number + r"\s+of\s+(?:them|those|these|it|each|the|items?|products?|units?|pieces?)\b",
                r"\b" + number + r"\s+(?:units?|pieces?|copies)\b",
                r"\b(?:make|change)\s+(?:it|that|this)\s+(?:just\s+)?" + number + r"\b",
                r"\b(?:just|only)\s+(?:do\s+|get\s+|add\s+)?" + number +
                r"(?=\s*(?:[.!?;,]|$|of them\b|for now\b|please\b|just\b|i\b|we\b|and\b|okay\b|thanks?\b|then\b|right now\b))",
                r"\bquantity\s+(?:of\s+)?" + number + r"\b"]
    mentions = {}
    for pattern in patterns:
        for match in re.finditer(pattern, command):
            token = match[1]
            mentions[match.start(1)] = int(token) if token.isdigit() else _COUNT_WORDS[token]
    return sorted(mentions.items())


def natural_count(command):
    """The effective stated item count, or None if absent or ambiguous.

    The last mention wins only when every earlier different count is followed
    by a retraction before the next mention ("three ... no wait ... make it one").
    """
    ordered = count_mentions(command)
    if not ordered:
        return None
    retract = _retraction_pattern(set())
    for (position, value), (following, _) in zip(ordered, ordered[1:]):
        if value != ordered[-1][1] and not re.search(retract, command[position:following]):
            return None
    return ordered[-1][1]


_PHRASE_BREAK = {"please", "now", "too", "also", "then", "and", "or", "in", "on", "at", "into", "from", "with",
                 "by", "of", "as", "right", "today", "tomorrow", "again", "instead", "thanks", "thank",
                 # A determiner starts a new phrase ("send Nia a message").
                 "a", "an", "the", "my", "your", "our", "their", "his", "her", "its", "this", "that", "some", "any",
                 # Interjections and discourse markers end a spoken phrase.
                 "oh", "um", "uh", "hmm", "so", "well", "okay", "ok", "yeah", "anyway", "actually", "wait", "like"}


def _schema_words(tool):
    """Vocabulary of the tool's own argument names and descriptions."""
    properties = tool.get("args", {}) if isinstance(tool.get("args"), dict) else {}
    text = " ".join(f"{name} {spec.get('description', '') if isinstance(spec, dict) else ''}"
                    for name, spec in properties.items())
    # The tool's own object ("autopay" in "water autopay") is not a value continuation.
    text += " " + str(tool.get("description", "")) + " " + str(tool.get("name", ""))
    return {item.casefold().rstrip("s") for item in re.findall(r"[A-Za-z]+", text.replace("_", " "))}


def _truncated_value(value, span, schema_words=frozenset()):
    """A string value cut from a longer phrase: "quiet" of "quiet and safe",
    or "fresh" of the direct object "fresh fennel". A following word that names a
    schema field ("passport number" for doc_number) is not a continuation."""
    value = words(value)
    for match in re.finditer(r"(?<![\w-])" + re.escape(value) + r"(?![\w-])", span):
        rest = span[match.end():]
        if re.match(r",?\s+(?:and|or|&)\s+[\w-]+(?:\s+[\w-]+)?\s*(?:[.!?;](?=\s|$)|$)", rest):
            return True
    # Direct object: the words between the verb and "for"/"to" or clause end.
    tail = re.sub(r"^\w+\s+", "", span)
    target = re.split(r"\b(?:for|to)\b|[.!?;,](?=\s|$)", tail, maxsplit=1)[0]
    occurrences = list(re.finditer(r"(?<![\w-])" + re.escape(value) + r"(?![\w-])", target))
    def continues(match):
        # Only when exactly one more plain word completes the object phrase
        # ("fresh fennel" + end); a longer phrase makes the value a modifier
        # ("mortgage auto pay so ...", "passport number to ...").
        following = re.match(r"\s+([a-z][a-z'-]*)\s*$", target[match.end():])
        return (bool(following) and following[1] not in _PHRASE_BREAK
                and following[1].rstrip("s") not in schema_words)
    # Truncated only if no occurrence completes the phrase (an article "a" is not the value "A").
    return bool(occurrences) and all(continues(match) for match in occurrences)


# Generic imperative verbs (language, not tools) for deciding whether a
# conditional sentence carries its own consequent ("once you find it, book it").
_IMPERATIVES = ("book", "reserve", "add", "put", "include", "update", "change", "set", "switch", "modify", "adjust",
                "edit", "enable", "turn", "cancel", "remove", "delete", "order", "buy", "purchase", "send", "search",
                "find", "look", "track", "check", "show", "get", "tell", "give", "calculate", "convert", "compare",
                "pay", "move", "schedule", "create", "open", "submit", "file", "swap", "replace", "visit", "see",
                "call", "email", "text", "message", "watch", "listen", "read", "let", "try", "use", "start", "stop",
                "leave", "keep", "remember", "note", "forget")
# Words that make a following verb part of the condition, not its consequent.
_CONDITION_SUBJECTS = {"you", "i", "we", "they", "he", "she", "it", "there", "that", "which", "who", "to", "can",
                       "could", "will", "would", "should", "might", "may", "must", "not", "don't", "dont", "cannot",
                       "can't", "you've", "i've", "we've", "they've",
                       "a", "an", "the", "my", "your", "our", "their", "his", "her"}
# A dependency on the assistant's own lookup with a bare object and no further
# qualifier ("once you find something, book it"). Qualified conditions ("once you
# find one under $300") stay conditions.
_OWN_LOOKUP = (r"\b(?:once|when|after)\s+(?:you(?:'ve|\s+have)?|it)\s+(?:can\s+)?"
               r"(?:find|found|get|got|locate|located|see|have|pull|pulled|look|looked)(?:\s+(?:up|it\s+up))?\s+"
               r"(?:something|one|it|them|anything|results?|(?:a|an|the|some)\s+[a-z]+)"
               r"(?:\s+(?:good|nice|decent|suitable))?"
               r"(?=\s*(?:[,.!?;]|$|(?:uh|um|go|then|please|and|just)\b|(?:{verbs})\b))")


def _has_consequent(rest, verbs):
    """True when a conditional sentence states its own action after the condition."""
    pattern = r"\b(" + "|".join(re.escape(item) for item in sorted(set(_IMPERATIVES) | set(verbs))) + r")\b"
    for match in re.finditer(pattern, rest):
        # Adverbs do not sever the conditional subject from its verb ("if you
        # can actually find it"). Determiners similarly make "a watch" a noun.
        prefix = re.sub(r"\b(?:(?:just|actually|already|still|really|only|first|also|ever|even|successfully)\s+)+$",
                        "", rest[:match.start()])
        before = re.search(r"([\w']+)\W*$", prefix)
        if before is None or before[1] not in _CONDITION_SUBJECTS:
            return True
    return bool(re.search(r"\b(?:i'll|i will|we'll|we will)\b", rest))


def _names_own_value(step, text):
    """Any of this step's scalar values (or a count word for a number) occurs in text."""
    for _, value in scalar_fields(step.get("args", {})):
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            forms = {str(int(value)) if float(value).is_integer() else str(value)}
            forms |= {word for word, number in _COUNT_WORDS.items() if number == value}
        else:
            forms = {str(value), str(value).replace("_", " ")}
        if any(form.strip() and (contains_value(form, text) or contains_identifier(form, text)) for form in forms):
            return True
    return False


def _restated_after(step, tool, text):
    """Some proposed value is (re)introduced by a correction construction in text.

    "make it savings", "savings instead", "just one", "I mean X", "to/from/for X",
    "X is better", or a bare "no, X" answer. A value that only appears negated or
    evaluated ("two is too many") does not count.
    """
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)  # "3,500" -> "3500"
    descriptors = tool.get("args", {}) if isinstance(tool.get("args"), dict) else {}
    for path, value in scalar_fields(step.get("args", {})):
        field = path.split(".")[0]
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            forms = {str(int(value)) if float(value).is_integer() else str(value)}
            forms |= {word for word, number in _COUNT_WORDS.items() if number == value}
        elif isinstance(value, str) and value.strip():
            if identifier_field(field, descriptors.get(field)) and contains_identifier(value, text):
                return True
            forms = {words(value), words(value.replace("_", " "))}
        else:
            continue
        for form in forms:
            item = r"(?<![\w-])" + re.escape(form) + r"(?![\w-])"
            det = r"(?:(?:my|the|a|an)\s+)?"
            patterns = (r"\b(?:make|change|switch|set|put)\s+(?:it|that|this)\s+(?:to\s+|as\s+)?(?:just\s+)?" + det + item,
                        item + r"\s+instead\b",
                        r"\b(?:just|only)\s+(?:do\s+|get\s+|add\s+|use\s+)?" + item,
                        r"\b(?:i\s+mean|i\s+meant|rather|go\s+with|use)\s+" + det + item,
                        r"\b(?:to|from|for|with|under)\s+" + det + item,
                        item + r"\s+(?:is|would be|will be)\s+(?:better|right|correct|fine|good|the right one|what i want)\b",
                        r"^[\s,]*" + item + r"\s*(?:[.!?;,]|$)")
            if any(re.search(pattern, text) for pattern in patterns):
                return True
    return False


def _anaphoric(rest):
    """A repeated command whose object is only a pronoun ("can you switch that over")."""
    return re.match(r"[\s,]*(?:it|that|this|them)(?:\s+(?:over|up|out|in|through|back|now|too|please|for\s+me|for\s+us|"
                    r"then|right\s+away|as\s+well))*\s*(?:[.!?;,]|$)", rest) is not None


def _deny(trace, reason):
    """Refuse, recording why when the caller asked for a trace (evidence only)."""
    if trace is not None:
        trace.append(reason)
    return None


def authorization_grant(step: dict, tool: dict, texts: list[tuple[int, str]], *, selection=None, operations=(), history=(),
                        trace=None, lookup_done=False, lookups=(), lookups_pending=False,
                        allow_attachment=True) -> str | None:
    # "Instead" replaces an earlier request only if an earlier turn named this action;
    # otherwise it replaces the current state ("pull from savings instead").
    verbs = _tool_verbs(step, tool)
    earlier = " ".join(str(message.get("payload", {}).get("text", "")) for message in history
                       if isinstance(message, dict) and message.get("event_type") in {"user_speech_chunk", "interruption"})
    earlier_action = bool(verbs) and re.search(r"\b(?:" + "|".join(map(re.escape, sorted(verbs))) + r")\b",
                                               words(earlier)) is not None
    # "instead of X" is a preposition, not a replacement marker.
    if re.search(r"\binstead\b(?!\s+of\b)", _language_only(" ".join(text for _, text in texts)), re.I):
        if selection is not None or any(op.get("kind") == "state_modifying" and op.get("status") != "not_submitted"
                                        for op in operations):
            return _deny(trace, "instead: replacement after a submitted effect or selection")  # Never infer undo.
        scoped = _replacement_scope(step, tool, texts, history)
        if scoped is not None:
            return _plain_authorization_grant(step, tool, scoped, replacement=True, trace=trace, lookup_done=lookup_done,
                                              lookups=lookups, lookups_pending=lookups_pending, allow_attachment=allow_attachment)
        # Other replacement shapes use the general clause rules, with "instead"
        # read as a replacement marker; the undo guard above still applies.
        return _plain_authorization_grant(step, tool, texts, operations=operations, instead_marker=True, trace=trace,
                                          lookup_done=lookup_done, lookups=lookups, lookups_pending=lookups_pending,
                                          earlier_action=earlier_action, allow_attachment=allow_attachment)
    return _plain_authorization_grant(step, tool, texts, selection=selection, operations=operations, trace=trace,
                                      lookup_done=lookup_done, lookups=lookups, lookups_pending=lookups_pending,
                                      allow_attachment=allow_attachment)


def _plain_authorization_grant(step: dict, tool: dict, texts: list[tuple[int, str]], *, selection=None,
                               replacement=False, operations=(), instead_marker=False, trace=None,
                               lookup_done=False, lookups=(), lookups_pending=False, earlier_action=True,
                               allow_attachment=True) -> str | None:
    """Return the effective request span that authorizes this write, else None.

    The span runs from the cited command clause through the last cited clause in
    original order. A valid citation is evidence, not permission: scope words,
    negated tool verbs, retractions without a later cited restatement, pronoun or
    truncated values, and superseded submitted effects all still reject.
    """
    evidence = step.get("authorization")
    if not isinstance(evidence, dict):
        return _deny(trace, "no authorization evidence")
    source = words(" ".join(text for _, text in texts))
    if not source:
        return _deny(trace, "empty turn")
    clauses = turn_clauses(texts)
    resolved = _cited_clauses(evidence, clauses, source, texts)
    if resolved is None:
        return _deny(trace, "citation does not resolve to current clauses in order")
    cited, quoted = resolved
    # A condition on the user's own later plan ("I'll order more later if I need to")
    # scopes that plan, not an earlier command; it still vetoes if it names this action.
    own_verbs = _tool_verbs(step, tool)
    def own_plan(match):
        if own_verbs and re.search(r"\b(?:" + "|".join(map(re.escape, sorted(own_verbs))) + r")\b", match[0]):
            return match[0]
        return " " * len(match[0])
    language = re.sub(r"\b(?:i'll|i will|we'll|we will|i might|i may)\b[^.!?;,]*?\bif\b[^.!?;,]*",
                      own_plan, _language_only(source))
    # The mirror order ("once you find something I'll check the time") is also the user's own plan.
    language = re.sub(r"\b(?:if|once|when|after)\b[^.!?;,]*?\b(?:i'll|i will|we'll|we will)\b[^.!?;,]*",
                      own_plan, language)
    language = re.sub(r"\binstead of\b", lambda match: " " * len(match[0]), language)
    # Only complete politeness hedges are inert. A prefix such as "if you can"
    # in "if you can get free shipping" still introduces a real condition.
    language = re.sub(r"\bif\s+(?:at\s+all\s+)?(?:possible|you\s+can|you\s+could|you\s+would|you\s+please|"
                      r"you\s+don't\s+mind|that's\s+(?:ok|okay|alright|all\s+right|fine)|it's\s+not\s+too\s+much\s+trouble)\b"
                      r"(?=\s*(?:[,.!?;]|$))",
                      lambda match: " " * len(match[0]), language)
    # A condition scopes its own sentence. A sentence that states its own
    # consequent ("Once you find a flight, book it.") cannot scope this action
    # unless it names this action's verbs or values; a dangling condition ("If the
    # rate is good."), a pro-verb consequent ("If it's cheap, do it.") and any
    # condition in the command's own sentence (which names its verb) still count.
    own_values = [value for _, value in scalar_fields(step.get("args", {}))
                  if isinstance(value, str) and len(value.strip()) > 1]
    own_pattern = (r"\b(?:" + "|".join(map(re.escape, sorted(own_verbs))) + r")\b") if own_verbs else None
    sentences = {}
    for row in clauses:
        start, end = sentences.get(row["sentence"], (row["start"], row["end"]))
        sentences[row["sentence"]] = (min(start, row["start"]), max(end, row["end"]))
    for start, end in sentences.values():
        text = language[start:end]
        condition = re.search(_SCOPE, text)
        # A hedge ("I might change my mind") is not a condition with its own
        # consequent; only the different-item rule below can set it aside.
        if (condition is None or condition[0] in {"maybe", "might", "perhaps"}
                or (own_pattern and re.search(own_pattern, text))
                or any(contains_value(value, text) or contains_identifier(value, text) for value in own_values)
                or not _has_consequent(text[condition.end():], own_verbs)):
            continue
        language = language[:start] + " " * (end - start) + language[end:]
    own_ids = {re.sub(r"[^a-z0-9]", "", value.casefold()) for value in own_values}
    for start, end in sentences.values():
        text = language[start:end]
        hedge = re.search(r"\b(?:maybe|might|perhaps)\b", text)
        own_command = own_pattern and re.search(own_pattern, text)
        if (not re.search(_SCOPE, text) or (hedge and own_command) or (not hedge and not own_command)
                or any(contains_value(value, text) or contains_identifier(value, text) for value in own_values)):
            continue
        # "Add N6. I might want item N7 later" / "Add four of item S3 only if ...": the
        # hedge or condition names another item with its own request, so it scopes that
        # item only. Pointing back ("that item") or an elliptical "Only if S3 sells out."
        # (no command of its own) still vetoes this write.
        named = spelled_runs(text) | set(re.findall(r"\b[a-z]{1,3}\d+[a-z0-9]*\b|\b\d+[a-z]{1,3}\b", text))
        others = {run for run in named if re.search(r"[a-z]", run) and re.search(r"\d", run)} - own_ids
        if others:
            language = language[:start] + " " * (end - start) + language[end:]
    # "Once you find something, book it": a dependency on this request's own
    # lookup holds once a lookup has succeeded; until then the write waits.
    if own_verbs:
        dependency = _OWN_LOOKUP.replace("{verbs}", "|".join(map(re.escape, sorted(own_verbs))))
        for match in list(re.finditer(dependency, language)):
            if not lookup_done:
                return _deny(trace, f"awaiting own lookup: {match[0]}")
            language = language[:match.start()] + " " * len(match[0]) + language[match.end():]
    if re.search(r"\bif\b", language):
        verified, status, phrase = _verified_price_conditions(language, step, lookups, lookups_pending)
        if status == "pending":
            return _deny(trace, f"awaiting own lookup: {phrase}")
        if status == "false":
            return _deny(trace, f"condition false by returned price: {phrase}")
        if verified is not None:
            language = verified
    conditioned = language
    language = _verified_conditions(language, selection)
    if language is None:
        match = re.search(r"\bif\b[^.!?;]{0,60}", conditioned)
        return _deny(trace, "unverified condition: " + (match[0].strip() if match else "if"))
    if replacement:
        # Keep original source and character positions. Only a previously
        # validated trailing scope marker is inert for command interpretation.
        language = re.sub(r"\binstead(?=\.?$)", lambda match: " " * len(match[0]), language)
    # "Make that two of that product, not four" / "move it to savings, not checking": a bare
    # negated fragment right after a clause that restates this write's value contrasts the
    # old value; it does not retract the command. Never when it names this write's own value.
    for previous, row in zip(clauses, clauses[1:]):
        fragment = language[row["start"]:row["end"]]
        if (previous["sentence"] == row["sentence"]
                and re.fullmatch(r"(?:but\s+)?not\s+(?!\w*ly\b)[\w'-]+[.!?;,]?\s*", fragment)
                # Only a value contrast is inert. Time/permission restrictions
                # and negated commands still withdraw immediate authority.
                and not re.search(r"\b(?:now|yet|today|tomorrow|tonight|ever|anymore|until|unless|before|after|"
                                  r"without|when|while|once|if|currently|immediately|time|moment|really|real|"
                                  r"actually|necessarily|soon|approved|authorized|allowed|permitted|confirmed|"
                                  r"requested|wanted|ready|sure|certain|okay|ok|right|necessary|"
                                  + "|".join(_IMPERATIVES) + r")\b", fragment)
                and _restated_after(step, tool, language[previous["start"]:previous["end"]])
                and not _names_own_value(step, fragment)):
            language = language[:row["start"]] + " " * (row["end"] - row["start"]) + language[row["end"]:]
    replacements = [match.start() for match in re.finditer(r"\binstead\b(?!\s+of\b)", language)]
    unblanked = language
    if instead_marker and not replacements:
        instead_marker = False  # Every "instead" sat in a sentence that cannot scope this action.
    if instead_marker:
        language = re.sub(r"\binstead\b", lambda match: " " * len(match[0]), language)
    scope = re.search(_SCOPE, language)
    if scope or '"' in language or "“" in language or "”" in language:
        return _deny(trace, f"scope qualifier in turn: {scope[0] if scope else 'quotation'}")
    verbs = _tool_verbs(step, tool)
    if not verbs:
        return _deny(trace, "no command verbs for this tool")
    verb = "(?:" + "|".join(re.escape(item) for item in sorted(verbs)) + ")"
    retract = _retraction_pattern(verbs)
    # "Don't forget to X" is a reminder to X, not a negation or retraction; blank
    # it in place so every other check keeps original character positions.
    language = re.sub(r"\b(?:don't|dont|do not)\s+forget\s+to\b", lambda match: " " * len(match[0]), language)
    cancel = r"\b(?:" + "|".join(re.escape(item) for item in _CANCEL_WORDS if item not in verbs) + r")\b"
    fillers = (r"(?:(?:please|yes|okay|ok|now|so|well|um|uh|hmm|mm|like|just|also|yeah|and|then|first|but|anyway|actually|"
               r"for now|right now|oh|hey|alright|all right|you know|by the way|real quick|in the meantime|"
               r"while you're at it|while you are at it)\s*,?\s+)*")
    polite = (r"(?:(?:can|could|would|will)\s+you\s+(?:(?:please|just|also|quickly|kindly|first|now)\s+)*|"
              r"(?:i(?:'d| would)?\s+like\s+you\s+to|"
              r"i\s+want\s+you\s+to|i\s+need\s+you\s+to|let's|"
              # A first-person request to an assistant ("I want to change my autopay").
              r"i\s+(?:just\s+|really\s+|also\s+)?(?:want|need)\s+to|i(?:'d| would)\s+like\s+to)\s+)?"
              r"(?:(?:like|um|uh|just|also|really|please|kinda|basically)\s*,?\s+)*(?:go\s+ahead\s+and\s+)?")
    command_pattern = r"(?:^|[.!?;,]\s*|\band\s+|\bthen\s+)\s*" + fillers + polite + "(" + verb + r")(?=[\s,]|$)"
    def commands_in(start, end):
        return list(re.finditer(command_pattern, language[start:end]))
    if quoted is None and not commands_in(cited[0]["start"], cited[-1]["end"]):
        # Re-citation repairs provenance, not intent. A value found in a status
        # question or statement cannot borrow another clause's command.
        if not allow_attachment:
            return _deny(trace, "re-cited clause has no command of its own")
        # Cited clauses only refine an action ("make it one"): attach the single
        # nearest preceding command clause of this action, then check everything
        # exactly as if it had been cited. Never for quotes, never across a cancel.
        before = [row for row in clauses if row["end"] <= cited[0]["start"]
                  and commands_in(row["start"], row["end"])]
        # The value first, then a command that only points back at it ("My new license
        # number is D468." / "Can you put that on my profile?"): attach that command.
        after = [row for row in clauses if row["start"] >= cited[-1]["end"]
                 and any(_anaphoric(language[row["start"] + item.end(1):row["end"]])
                         or re.match(r"[\s,]*(?:it|that|this|them)\b", language[row["start"] + item.end(1):row["end"]])
                         for item in commands_in(row["start"], row["end"]))]
        if before:
            cited = [before[-1], *cited]
        elif after:
            cited = [*cited, after[0]]
        else:
            return _deny(trace, "no command verb in or before the cited clauses")
    region_start, span_end = cited[0]["start"], cited[-1]["end"]
    commands = commands_in(region_start, span_end)
    primary = [item for item in commands if not _anaphoric(language[region_start + item.end(1):span_end])]
    if len(commands) > 1 and len(primary) == 1:
        commands = primary
    if len(commands) > 1:
        # Several commands in one span ("set the filter so pets are allowed and set the max
        # price to 3,000"): the one whose own stretch, up to the next command, states every
        # value of this write. Anything else stays ambiguous and is refused below.
        stated = [value for value in own_values if value.strip().casefold() not in {"true", "false", "yes", "no"}]
        def stretch(position):
            start = region_start + commands[position].start(1)
            end = region_start + commands[position + 1].start(1) if position + 1 < len(commands) else span_end
            # A later sentence may ask about a different object. It is not part
            # of this command merely because it precedes the next imperative.
            text = re.split(r"[.!?;](?=\s|$)", language[start:end], maxsplit=1)[0]
            return re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)
        def states(value, text):
            return (contains_value(value, text) or contains_identifier(value, text)
                    or ("_" in value and all(re.search(r"\b" + re.escape(part), text) for part in value.casefold().split("_") if part)))
        matching = [item for position, item in enumerate(commands)
                    if stated and all(states(value, stretch(position)) for value in stated)]
        if len(matching) == 1:
            commands = matching
    if len(commands) != 1:
        # Exactly one command for this action in the cited region.
        return _deny(trace, f"{len(commands)} commands for this action in the cited region")
    verb_at = region_start + commands[0].start(1)
    # The command must sit in a cited clause (earlier cited clauses are context),
    # and a quote must actually contain the imperative verb it relies on.
    command_clause = next((row for row in cited if row["start"] <= verb_at < row["end"]), None)
    if command_clause is None and quoted is None:
        # The citation spans this clause (cited clauses on both sides); every check
        # below already inspects the whole span, so treat it as cited.
        command_clause = next((row for row in clauses if row["start"] <= verb_at < row["end"]), None)
        if command_clause is not None:
            cited = sorted([*cited, command_clause], key=lambda row: row["start"])
    if command_clause is None or (quoted is not None and not quoted[0] <= verb_at < quoted[1]):
        return _deny(trace, "command verb outside the cited clauses")
    command_sentence_end = sentences[command_clause["sentence"]][1]
    command_sentence = language[verb_at:command_sentence_end]
    # "Add it to my cart so I can buy it later": "later" belongs to a subordinate clause with its
    # own subject, not to this command.
    subordinate = re.search(r"\b(?:so(?:\s+that)?|because|since|until|in\s+order\s+to|when|once)\s+"
                            r"(?:i|we|you|they|he|she)\b", command_sentence)
    main_clause = command_sentence[:subordinate.start()] if subordinate else command_sentence
    if (re.search(r"\blater\s*(?:[.!?;,]|$)", main_clause.rstrip() + ("," if subordinate else ""))
            and not re.search(r"\b(?:about|saying)\b", command_sentence)):
        return _deny(trace, "command is deferred, not authorized for immediate dispatch")
    # Interrogatives are not extra commands. Polite action requests still match
    # commands_in; status questions cannot donate values to a preceding action.
    questions = (r"(?:^|[.!?;,]\s*|\band\s+)\s*((?:is|are|was|were|do|does|did|has|have|had|"
                 r"can|could|would|will|should|what|which|where|why|how)\b[^.!?;]*)")
    for question in re.finditer(questions, language[verb_at:span_end]):
        start, end = verb_at + question.start(1), verb_at + question.end(1)
        if (not commands_in(start, end)
                and any(contains_value(value, question[1]) or contains_identifier(value, question[1]) for value in own_values)):
            return _deny(trace, "question does not authorize the proposed value")
    span_start = command_clause["start"]
    # Citing a cancellation cannot make it inert. A quantity/value correction
    # after "forget it" never revives the old command; only a fresh command can.
    cancelled = re.search(cancel, language[verb_at:span_end])
    if cancelled:
        return _deny(trace, f"cancellation after command: {cancelled[0]}")
    # Resolve the complete effective region first, including an attached or
    # uncited command. Skipping a citation never hides an intervening correction.
    markers = [(row, match) for row in clauses if region_start <= row["start"] < span_end
               for match in re.finditer(retract, language[row["start"]:row["end"]])]
    if markers:
        row, match = markers[-1]
        after_start = row["start"] + match.end()
        if match[0] in {"not", "don't", "dont", "do not", "never"}:
            # A negator scopes the phrase it introduces ("not for John, for Jane").
            stop = re.search(r"[,.!?;]|\bbut\b", language[after_start:span_end])
            after_start = after_start + stop.start() if stop else span_end
        after = language[after_start:span_end]
        if re.search(cancel, after) or not _restated_after(step, tool, after):
            first_row, first = markers[0]
            return _deny(trace, f"retraction inside cited clause {first_row['clause_id']}: {first[0]}")
        # "Add four of QT51. Sorry, make that two of ZK20": a correction naming a different
        # identifier supersedes this one unless it is restated there too.
        descriptors = tool.get("args", {}) if isinstance(tool.get("args"), dict) else {}
        named = spelled_runs(after) | set(re.findall(r"\b(?=[a-z0-9-]*[a-z])(?=[a-z0-9-]*\d)[a-z0-9-]+\b", after))
        for path, value in scalar_fields(step.get("args", {})):
            field = path.split(".")[0]
            # A declared identifier can be a word, a long code, or digits.
            # Its field noun supplies the role; do not assume a short SKU shape.
            noun = re.sub(r"_(?:id|number|code)$", "", field).replace("_", " ")
            explicit = re.findall(r"\b" + re.escape(noun) + r"\s+(?:(?:id|number|code)\s+)?"
                                  r"(?:is\s+|to\s+|=\s*)?([\w-]+)", after)
            explicit = [item for item in explicit if item not in {"it", "this", "that", "same", "one"}]
            if (isinstance(value, str) and identifier_field(field, descriptors.get(field))
                    and not contains_identifier(value, after) and not contains_value(value, after)
                    and (explicit or any(run.casefold() != value.casefold() for run in named
                                         if re.search(r"[a-z]", run) and re.search(r"\d", run)))):
                return _deny(trace, f"correction names a different {field}")
        # Repeating an unchanged target ("for my mortgage") cannot rescue the
        # value just corrected ("to checking, no wait, use savings"). Check the
        # most recent value-setting phrase separately from the rest of the args.
        before = language[region_start:row["start"] + match.start()]
        setters = list(re.finditer(r"\b(?:to|from|for)\b", before))
        if setters:
            previous_value = before[setters[-1].start():]
            for path, value in scalar_fields(step.get("args", {})):
                single = {**step, "args": {path: value}}
                # "Make that two of that same product": the correction keeps this field's object.
                noun = re.split(r"[_.]", path)[0]
                if (identifier_field(path.split(".")[0], descriptors.get(path.split(".")[0]))
                        and re.search(r"\bsame\s+(?:one|" + re.escape(noun) + r")s?\b", after)):
                    continue
                if _restated_after(single, tool, previous_value) and not _restated_after(single, tool, after):
                    return _deny(trace, f"superseded value before correction: {path}")
    # "Instead" is a same-turn replacement only when this turn itself states the
    # correction between the command and "instead" ("... from checking, no wait,
    # make it savings instead"); otherwise it replaces an earlier turn.
    same_turn = bool(replacements) and all(
        verb_at < position < span_end
        and re.search(_retraction_pattern(verbs | {"instead"}), unblanked[verb_at:position]) is not None
        for position in replacements)
    if instead_marker and earlier_action and not commands_in(0, span_start) and not same_turn:
        # "Instead" replacing an earlier turn stays on the strict history-checked path.
        return _deny(trace, "instead replaces an earlier turn")
    # Negating this action vetoes it when the negation is the command or follows
    # it, or when it names this step's own target. A negated *different* object
    # before the command is a retracted alternative ("don't add celery ... add
    # spinach instead"); it never lends authority to the negated object.
    targets = [value for _, value in scalar_fields(step.get("args", {})) if isinstance(value, str) and len(value.strip()) > 1]
    for negation in re.finditer(_NEGATION + r"(?:[\w']+\s+){0,2}?" + verb + r"\b", language):
        if negation.start() >= span_start or not targets:
            return _deny(trace, f"negated command: {negation[0].strip()}")
        negated_end = next((row["end"] for row in clauses if row["start"] <= negation.end() <= row["end"]), span_start)
        negated = language[negation.start():negated_end]
        if any(contains_value(value, negated) or contains_identifier(value, negated) for value in targets):
            return _deny(trace, "negation names this target")
    cited_ids = {row["clause_id"] for row in cited}
    for row in clauses:
        if row["start"] > span_start and row["clause_id"] not in cited_ids:
            text = language[row["start"]:row["end"]]
            later = re.search(cancel, text)
            if later:
                # A later cancellation withdraws the command; only a fresh command revives it.
                return _deny(trace, f"later cancellation in clause {row['clause_id']}: {later[0]}")
            later = re.search(retract, text)
            if later and not any(other["start"] > row["start"] for other in cited):
                correction = " ".join(language[other["start"]:other["end"]] for other in clauses
                                      if other["sentence"] == row["sentence"] and other["start"] >= row["start"])
                commands = commands_in(region_start, span_end)
                stretches = [(region_start + item.start(1),
                              region_start + commands[index + 1].start(1) if index + 1 < len(commands) else span_end)
                             for index, item in enumerate(commands)]
                own = next((language[start:end] for start, end in stretches if start == verb_at), "")
                others = " ".join(language[start:end] for start, end in stretches if start != verb_at)
                if _corrects_other_target(step, correction, others, own):
                    continue
                # A later correction marker with nothing cited after it voids the command.
                return _deny(trace, f"later correction in clause {row['clause_id']} with nothing cited after: {later[0]}")
    command = language[verb_at:span_end].rstrip(".!?;, ")
    # A superseded same-turn command must not hide an effect already submitted.
    earlier = language[:span_start]
    if re.search(retract, earlier) and re.search(r"\b" + verb + r"\b", earlier):
        for op in operations:
            if op.get("kind") == "state_modifying" and op.get("status") != "not_submitted" and any(
                    isinstance(value, str) and len(value.strip()) > 1
                    and (contains_value(value, earlier) or contains_identifier(value, earlier))
                    for _, value in scalar_fields(op.get("args", {}))):
                return _deny(trace, "superseded command already submitted an effect")
    bound = set(step.get("result_bindings", {}) or {}) | set(step.get("bindings", {}) or {})
    descriptors = tool.get("args", {}) if isinstance(tool.get("args"), dict) else {}
    for path, value in scalar_fields(step.get("args", {})):
        if isinstance(value, str) and path not in bound:
            if words(value) in _PRONOUN_VALUES or _truncated_value(
                    value, command, _schema_words(dict(tool, name=str(step.get("api_name", "")).replace("_", " ")))):
                return _deny(trace, f"pronoun or truncated value for {path}: {value}")
            field = path.split(".")[0]
            if identifier_field(field, descriptors.get(field)) and truncated_identifier(value, source):
                return _deny(trace, f"truncated identifier for {path}: {value}")
            # A "<thing>_number" with no digit is not a number ("DL" when the digits were
            # not heard); ask rather than write it. Letters-only IDs ("KLM") stay valid.
            if field.endswith("_number") and not re.search(r"\d", value):
                return _deny(trace, f"number without digits for {path}: {value}")
    # A tool cannot borrow permission for a different named object. Pronouns and
    # selected options are resolved by the planner and checked by result binding.
    tail = re.sub(r"^\w+\s+", "", command)
    # A back-reference ("update that", "swap out the old one") points to a thing the
    # user described in the cited clauses; its values are checked against those clauses.
    if re.match(r"(?:(?:out|up|over|in|back|on|off)\s+)?(?:it|this|that|them|the\s+(?:selected|chosen|first|second|third|\d)|"
                r"(?:the|this|that)\s+(?:(?:old|new|same|other)\s+)?one)\b", tail):
        return command
    if step.get("result_bindings") and re.match(
            r"(?:(?:with|using|via)\s+)?(?:the|this|that)\s+[^.!?;]*\b(?:option|offer|one|result|selection)\b", tail):
        return command
    target = re.split(r"\b(?:for|to)\b", tail, maxsplit=1)[0]
    for path, value in scalar_fields(step.get("args", {})):
        field = path.split(".")[0]
        if isinstance(value, str) and ((len(value.strip()) > 2 and (contains_value(value, target) or (
                "_" in value and contains_value(value.replace("_", " "), target)))) or (
                identifier_field(field, descriptors.get(field)) and contains_identifier(value, target))):
            return command
    if selection and any(isinstance(value, str) and contains_value(value, target) for value in selection.values()):
        return command
    description = str(tool.get("description", ""))
    name = str(step.get("api_name", "")).rsplit(".", 1)[-1]
    ignored = {"a", "an", "the", "to", "of", "for", "from", "with", "and", "by", "in", "on", "as", "specific", "existing", "new", "current", "selected", "one", "tool", "request"}
    nouns = {item.casefold().rstrip("s") for item in re.findall(r"[a-zA-Z]+", description + " " + name.replace("_", " "))
             if item.casefold() not in ignored | verbs}
    spoken = re.findall(r"[a-zA-Z]+", tail)
    # ASR may split a compound ("auto pay" for "autopay"): also try adjacent pairs joined.
    supplied = {item.rstrip("s") for item in spoken + [a + b for a, b in zip(spoken, spoken[1:])]}
    return command if nouns & supplied else _deny(trace, "command names no target of this tool")


def authorized(step: dict, tool: dict, texts: list[tuple[int, str]]) -> bool:
    return bool(authorization_grant(step, tool, texts))
