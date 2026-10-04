"""Validation for the supplied manifest's recursive argument descriptors."""
from __future__ import annotations

import json
import math
import re


def selected_printed_label(observation: object, frame_index: object) -> str | None:
    """Read a provider's scoped attestation; never infer category or confidence."""
    if (type(frame_index) is not int or frame_index < 0 or not isinstance(observation, dict) or
            observation.get("type") != "image" or type(observation.get("message_index")) is not int or
            observation["message_index"] != frame_index or type(observation.get("uncertain")) is not bool):
        return None
    selected, labels = observation.get("selected_label"), observation.get("visible_text")
    if (not isinstance(selected, dict) or selected.get("recognition") != "clear" or
            selected.get("referent") != "ambiguous" or not isinstance(labels, list) or
            any(not isinstance(label, str) for label in labels)):
        return None
    label = selected.get("text")
    return label if isinstance(label, str) and any(char.isalnum() for char in label) and label in labels else None


def validate_args(tool: dict, args: object) -> list[str]:
    """Fail closed on unknown effects, fields, malformed schemas and bad values."""
    return [message for _, _, message in argument_problems(tool, args)]


def argument_problems(tool: dict, args: object) -> list[tuple[str, str, str]]:
    """validate_args's problems as (path, kind, message).

    kind is "missing" (a declared argument is absent or null), "invalid" (a declared
    argument has the wrong type or an undeclared enum value) or "internal" (the tool,
    a descriptor or an undeclared argument: nothing the user can say repairs it).
    """
    errors: list[tuple[str, str, str]] = []
    if not isinstance(tool, dict) or not isinstance(tool.get("kind"), str) or tool["kind"] not in {"read_only", "state_modifying"}:
        return [("", "internal", "The tool must declare a known kind.")]
    properties = tool.get("args")
    if not isinstance(properties, dict):
        return [("", "internal", "The tool must declare an args mapping.")]
    _validate({"type": "object", "properties": properties}, args, "args", errors, 0)
    return errors


_NOT_A_NOUN = {"whether", "if", "when", "set", "use", "true", "false", "must", "should", "can", "is", "are",
               "default", "defaults", "see"}


def _argument_words(key: str, spec: object) -> str | None:
    """Plain words for one declared argument: its description, else its name.

    "Maximum monthly rent budget" -> "the maximum monthly rent budget"; "The card type,
    e.g. 'platinum'" -> "the card type"; max_price without a description -> "the max
    price". Never an underscore, dotted path or example value.
    """
    description = spec.get("description") if isinstance(spec, dict) else None
    words = ""
    if isinstance(description, str):
        words = re.split(r"[(,;:]|\s-\s|\.(?:\s|$)|\b(?:e\.g|i\.e|for example|such as|defaults? to)\b",
                         description, maxsplit=1, flags=re.I)[0]
        words = " ".join(re.sub(r"^\s*optional\s+", "", words, flags=re.I).split())
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9' -]*", words) or len(words.split()) > 8
            or words.split()[0].casefold() in _NOT_A_NOUN):
        parts = re.findall(r"[A-Za-z]+|\d+", re.sub(r"(?<=[a-z])(?=[A-Z])", " ", key))
        words = " ".join("ID" if part.casefold() == "id" else part.lower() for part in parts)
    if not words:
        return None
    first = words.split()[0]
    if first[0].isupper() and (len(first) == 1 or first[1:].islower()):  # Keep "ID" and "USD".
        words = words[0].lower() + words[1:]
    return words if first.casefold() in {"the", "a", "an", "your"} else "the " + words


def _declared_words(tool: dict, path: str) -> str | None:
    """Plain words for a declared argument path; None for anything undeclared."""
    parts = path.split(".")
    if parts[0] != "args" or len(parts) < 2 or not isinstance(tool.get("args"), dict):
        return None
    spec, key, named, siblings = {"type": "object", "properties": tool["args"]}, None, None, {}
    for part in parts[1:]:
        if isinstance(spec, str):
            spec = {"type": spec}
        if not isinstance(spec, dict):
            return None
        if part.isdigit():
            spec = spec.get("items")
        else:
            properties = spec.get("properties")
            if not isinstance(properties, dict) or part not in properties:
                return None
            spec = named = properties[part]
            key, siblings = part, properties
    if key is None:
        return None
    words = _argument_words(key, named)
    # Arguments described alike (from and to currency: "3-letter currency code")
    # are told apart by their names.
    if any(other != key and isinstance(other, str) and _argument_words(other, other_spec) == words
           for other, other_spec in siblings.items()):
        words = _argument_words(key, {})
    return words


def _spoken_list(items: list[str]) -> str:
    if len(items) < 3:
        return " and ".join(items)
    return ", ".join(items[:-1]) + ", and " + items[-1]


def argument_question(tool: dict, args: object, *, skip: object = ()) -> str:
    """A short spoken request for the values validation found missing or unusable.

    Asks, in the declared contract's words, for each missing or ill-typed declared
    argument. It never suggests a value, and never speaks the validator's messages
    or dotted paths; those stay in the controller's evidence.
    """
    asked, invalid = [], []
    for path, kind, _ in argument_problems(tool, args):
        if path in skip:  # Filters the search may leave unspecified.
            continue
        phrase = _declared_words(tool, path) if kind in {"missing", "invalid"} else None
        if phrase is not None and phrase not in asked:
            asked.append(phrase)
        if phrase is not None and kind == "invalid" and phrase not in invalid:
            invalid.append(phrase)
    if not asked:
        return "I could not prepare that request with details I can use. Could you say it another way?"
    question = "Could you tell me " + _spoken_list(asked[:3] + ["the other details it needs"] * (len(asked) > 3)) + "?"
    if not invalid:
        return question
    unusable = ("I could not use the value I had for "
                + _spoken_list(invalid[:3] + ["some other details"] * (len(invalid) > 3)) + ".")
    if len(asked) == len(invalid):
        return unusable + (" Could you say it again?" if len(invalid) == 1 else " Could you say them again?")
    return unusable + " " + question


def unstated_search_filters(name: object, tool: dict, args: object, *, majority: bool = True) -> list[str]:
    """Required filters a search leaves unstated, to run unspecified rather than invented.

    "Places in Austin under 2000" is a complete search even though the contract
    also requires bedrooms: the user did not narrow by it, so it runs with that
    filter unspecified (None) instead of a guessed number or a blocking question.
    Only read-only tools named as searches (their arguments narrow results rather
    than parameterize a computation), only scalar non-identifier filters, and only
    when the user stated at least as many required filters as are left unstated: a
    search narrowed by one of three filters is too vague to be the one asked for (and
    is how a stray proposal looks), so it is asked about instead. Writes never qualify.
    majority=False answers only which filters are of a kind that may stay unstated (used to
    strip a guessed value, which is never sent whether or not the search then runs).
    """
    if (not isinstance(name, str) or not name.startswith("search") or not isinstance(tool, dict)
            or tool.get("kind") != "read_only" or not isinstance(args, dict)
            or not isinstance(tool.get("args"), dict)):
        return []
    properties = tool["args"]
    required = [key for key, spec in properties.items()
                if isinstance(spec, dict) and spec.get("required") and "default" not in spec]
    missing = [key for key in required if key not in args]
    from .authorization import identifier_field
    if (not missing or not any(key in args for key in required)
            or majority and len(missing) > len(required) - len(missing)
            or any(key == "id" or identifier_field(key, properties[key]) for key in missing)
            or any(properties[key].get("type") not in {"string", "number", "integer"} for key in missing)):
        return []
    return missing


def _validate(spec: object, value: object, path: str, errors: list[tuple[str, str, str]], depth: int) -> None:
    if isinstance(spec, str):
        spec = {"type": spec}
    if not isinstance(spec, dict) or depth > 20:
        errors.append((path, "internal", f"{path}: invalid or too deeply nested descriptor"))
        return
    kind = spec.get("type")
    valid = {
        "string": isinstance(value, str),
        "number": type(value) is int or type(value) is float and math.isfinite(value),
        "integer": type(value) is int,
        "boolean": type(value) is bool,
        "array": isinstance(value, list),
        "object": isinstance(value, dict),
    }
    if not isinstance(kind, str) or kind not in valid or not valid[kind]:
        # A null is an omitted value, not a wrong one.
        problem = ("internal" if not isinstance(kind, str) or kind not in valid
                   else "missing" if value is None else "invalid")
        errors.append((path, problem, f"{path}: expected {kind!r}"))
        return
    if "enum" in spec and (not isinstance(spec["enum"], list) or
                           not any((type(value) is type(item) or kind == "number" and type(item) in (int, float))
                                   and value == item for item in spec["enum"])):
        errors.append((path, "invalid" if isinstance(spec["enum"], list) else "internal",
                       f"{path}: value is outside the declared enum"))
    if kind == "object":
        properties = spec.get("properties", {})
        if not isinstance(properties, dict):
            errors.append((path, "internal", f"{path}: invalid properties mapping"))
            return
        for key, child in properties.items():
            if not isinstance(key, str) or not isinstance(child, dict):
                errors.append((path, "internal", f"{path}: invalid property descriptor"))
                continue
            if child.get("required") and key not in value:
                errors.append((f"{path}.{key}", "missing", f"{path}.{key}: missing required argument"))
            elif key in value:
                _validate(child, value[key], f"{path}.{key}", errors, depth + 1)
        for key in value:
            if key not in properties:
                errors.append((f"{path}.{key}", "internal", f"{path}.{key}: undeclared argument"))
    elif kind == "array":
        if "items" not in spec:
            errors.append((path, "internal", f"{path}: array descriptor needs an items type"))
        else:
            for index, item in enumerate(value):
                _validate(spec["items"], item, f"{path}.{index}", errors, depth + 1)


def call_key(api_name: str, args: dict, *, write: bool = False) -> str:
    def normalize(value):
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, str):
            return value.strip().casefold()
        if type(value) is float and value.is_integer():
            return int(value)
        return value
    return json.dumps([api_name, normalize(args) if write else args], sort_keys=True, separators=(",", ":"), allow_nan=False)


def with_declared_defaults(args: dict, descriptor: dict) -> dict:
    """Fill absent top-level arguments from the tool's declared defaults.

    Used only for effect identity: sending an argument with its declared default
    and omitting it request the same effect. The dispatched arguments are unchanged.
    """
    filled = dict(args)
    for name, spec in (descriptor.get("args") or {}).items():
        if name not in filled and isinstance(spec, dict) and "default" in spec:
            filled[name] = spec["default"]
    return filled


def at_path(value: object, path: str) -> object:
    """Resolve a dotted dictionary/list path, without evaluating expressions."""
    if not isinstance(path, str):
        raise ValueError("A result path must be a string")
    for part in path.split(".") if path else []:
        if isinstance(value, dict):
            value = value[part]
        elif isinstance(value, list) and part.isdigit():
            value = value[int(part)]
        else:
            raise ValueError(f"Invalid result path: {path}")
    return value


def scalar_fields(value: object, prefix: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from scalar_fields(item, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from scalar_fields(item, f"{prefix}.{index}")
    else:
        yield prefix, value
