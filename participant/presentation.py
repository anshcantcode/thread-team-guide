"""Mechanical field binding for quantitative result templates.

A delivered number is not evidence for an arbitrary claim containing that number.
For quantities, accept explicit field labels; otherwise let the controller speak
the actual result with its own labels. This is deliberately not an English
entailment classifier and does not infer units or arithmetic from tool names.
"""
from __future__ import annotations

import re
import unicodedata

from .schema import at_path, scalar_fields


_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")
_SEPARATOR = re.compile(r"\s*(?:[,;.]\s*(?:(?:and|with)\s+)?|(?:and|with)\s+)", re.I)


def _words(text):
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    text = unicodedata.normalize("NFKC", text).casefold()
    # Normalize separators only inside field names. A trailing '-' or '.' next
    # to the placeholder would change the spoken value (23 -> -23 or .23).
    return tuple(re.sub(r"(?<=\w)[_.-]+(?=\w)", " ", text).split())


def _quantity(value):
    if type(value) in (int, float, bool):
        return True
    if not isinstance(value, str):
        return False
    # Detect formatted numeric data without interpreting its locale, units, or
    # value. Grouping, decimal, sign, currency and exponent notation stay intact.
    value = unicodedata.normalize("NFKC", value)
    return any(char.isnumeric() for char in value) and all(
        char.isnumeric() or char.isspace() or unicodedata.category(char) == "Sc"
        or char in "+-−.,'’%‰eE" for char in value)


def quantitative_template_is_bound(template, result):
    """Keep each quantity attached to its field, never merely to a matching value.

    An exact returned prose string needs no generated field label, even when
    sibling fields contain quantities. Otherwise, a result containing quantities
    requires field-label/placeholder pairs and separators. Checking only the immediate
    vicinity of a quantity leaves room for invented comparisons and unit claims
    elsewhere. Numeric descendants count even when a container is selected.
    Other results retain the existing natural prose path.
    """
    placeholders = list(_PLACEHOLDER.finditer(template))
    exact = _PLACEHOLDER.fullmatch(template.strip())
    if exact is not None:
        value = at_path(result, exact[1])
        # Pure projection adds no claim, unit, arithmetic or relation. Bare
        # numbers and containers still require their actual field labels.
        if isinstance(value, str) and value.strip() and not _quantity(value):
            return True
    fields = list(scalar_fields(result))
    if not any(_quantity(value) for _, value in fields):
        return not any(char.isdigit() for char in _PLACEHOLDER.sub("", template))
    if not placeholders:
        return False
    previous_end = 0
    for index, match in enumerate(placeholders):
        path = match[1]
        at_path(result, path)  # Missing paths use the controller's fallback.
        prefix = template[previous_end:match.start()]
        if index:
            separator = _SEPARATOR.match(prefix)
            if separator is None:
                return False
            prefix = prefix[separator.end():]
        label = re.sub(r"^(?:(?:the|your|returned)\s+)+", "", prefix.strip(), flags=re.I)
        label = re.sub(r"\s*(?::|=|\b(?:is|equals)\b)\s*$", "", label, flags=re.I)
        aliases = {_words(path)}
        leaf = _words(path.rsplit(".", 1)[-1])
        # The last name alone is insufficient when several records own it.
        if sum(_words(other.rsplit(".", 1)[-1]) == leaf for other, _ in fields) == 1:
            aliases.add(leaf)
        if not leaf or _words(label) not in aliases:
            return False
        previous_end = match.end()
    return re.fullmatch(r"\s*\.?\s*", template[previous_end:]) is not None
