"""Validation for the supplied manifest's recursive argument descriptors."""
from __future__ import annotations

import json
import math


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
    errors: list[str] = []
    if not isinstance(tool, dict) or not isinstance(tool.get("kind"), str) or tool["kind"] not in {"read_only", "state_modifying"}:
        return ["The tool must declare a known kind."]
    properties = tool.get("args")
    if not isinstance(properties, dict):
        return ["The tool must declare an args mapping."]
    _validate({"type": "object", "properties": properties}, args, "args", errors, 0)
    return errors


def _validate(spec: object, value: object, path: str, errors: list[str], depth: int) -> None:
    if isinstance(spec, str):
        spec = {"type": spec}
    if not isinstance(spec, dict) or depth > 20:
        errors.append(f"{path}: invalid or too deeply nested descriptor")
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
        errors.append(f"{path}: expected {kind!r}")
        return
    if "enum" in spec and (not isinstance(spec["enum"], list) or
                           not any((type(value) is type(item) or kind == "number" and type(item) in (int, float))
                                   and value == item for item in spec["enum"])):
        errors.append(f"{path}: value is outside the declared enum")
    if kind == "object":
        properties = spec.get("properties", {})
        if not isinstance(properties, dict):
            errors.append(f"{path}: invalid properties mapping")
            return
        for key, child in properties.items():
            if not isinstance(key, str) or not isinstance(child, dict):
                errors.append(f"{path}: invalid property descriptor")
                continue
            if child.get("required") and key not in value:
                errors.append(f"{path}.{key}: missing required argument")
            elif key in value:
                _validate(child, value[key], f"{path}.{key}", errors, depth + 1)
        for key in value:
            if key not in properties:
                errors.append(f"{path}.{key}: undeclared argument")
    elif kind == "array":
        if "items" not in spec:
            errors.append(f"{path}: array descriptor needs an items type")
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
