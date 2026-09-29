"""Our provisional thread.v1 protocol; not Samsung's unpublished adapter."""
from __future__ import annotations

from typing import Any, Literal

from .models import BaseModel, ClosedModel, Field
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError


class Change(BaseModel):
    slot: str
    value: Any = Field(..., description='Native JSON value matching this slot schema. Legacy JSON-encoded strings for non-string values are also accepted.')
    source: Literal['input', 'user', 'frame'] = Field(default='input', description='frame only for visibly observed values; user for spoken/typed reports. Never classify a reported symptom as visually observed.')


class Interpretation(ClosedModel):
    intent: Literal['revise', 'select', 'commit', 'additional_action', 'cancel', 'stop_work', 'pause',
                    'speech_only', 'status', 'acknowledge', 'clarify', 'compare',
                    'resume', 'retry', 'unsupported', 'observe', 'end']
    domain: str = ''
    changes: list[Change] = Field(default_factory=list)
    remove: list[str] = Field(default_factory=list)
    selection: str = Field(default='', description='Exact current returned option ID, never invented.')
    action_id: str = Field(default='', description='For cancellation, exact submitted action call_id from the current state. Required if more than one could be cancelled.')
    question: str = Field(default='', description='A question YOU need to ask for unresolved ambiguity. Empty when the user has supplied the requested detail; use revise in that case.')
    transcript: str = ''
    observation: str = Field(default='', description='Only visible facts; never temporal claims from a still.')


class ToolSpec(ClosedModel):
    name: str = Field(pattern=r'^[a-zA-Z][a-zA-Z0-9_.-]{0,79}$')
    description: str = Field(min_length=12, max_length=3000)
    purpose: Literal['lookup', 'create', 'cancel', 'status']
    effect: Literal['read', 'write']
    parameters: dict[str, Any]
    cancellable: bool = True
    bindings: dict[str, Literal['call_id', 'reference', 'option_id']] = Field(default_factory=dict,
        description='Explicit argument bindings for action selection and reconciliation. Never guess identifiers from field names.')
    result_schema: dict[str, Any] | None = None
    authorization_verbs: list[str] = Field(default_factory=list, description='Imperative verbs from the supported action vocabulary, such as allocate or issue.')
    authorization_objects: list[str] = Field(default_factory=list, description='Names of this action object, such as flight, reservation, note or permit. Unfamiliar tools without these can use Submit the selected action.')


class Manifest(ClosedModel):
    id: str = Field(pattern=r'^[a-z][a-z0-9_-]{0,39}$')
    title: str
    description: str
    slots: dict[str, Any]
    defaults: dict[str, Any] = Field(default_factory=dict)
    tools: list[ToolSpec]
    frame_slots: list[str] = Field(default_factory=list, description='Slots whose inferred image values must be cleared when the image is replaced.')

    def check(self) -> 'Manifest':
        try:
            return self._check()
        except (SchemaError, ValidationError) as exc:
            raise ValueError('Manifest schema or defaults are invalid.') from exc

    def _check(self) -> 'Manifest':
        def local_references(value):
            if isinstance(value, dict):
                if any(key in value for key in ('$ref', '$dynamicRef', '$recursiveRef')):
                    raise ValueError('This adapter requires inline schemas; local, dynamic and external references are unsupported. Expand references before registration.')
                for child in value.values(): local_references(child)
            elif isinstance(value, list):
                for child in value: local_references(child)
        local_references(self.model_dump())
        Draft202012Validator.check_schema(self.slots)
        if self.slots.get('type') != 'object' or self.slots.get('additionalProperties') is not False:
            raise ValueError('Slot schema must be a closed JSON object.')
        properties = self.slots.get('properties', {})
        if any(not isinstance(schema, dict) for schema in properties.values()):
            raise ValueError('This adapter requires object schemas for individual slots; boolean slot schemas are unsupported.')
        if not set(self.frame_slots) <= properties.keys():
            raise ValueError('Frame dependencies must name declared slots.')
        for name, value in self.defaults.items():
            if name not in properties:
                raise ValueError('A default must name a declared slot.')
            Draft202012Validator(properties[name], format_checker=FormatChecker()).validate(value)
        names = set()
        roles = set()
        for tool in self.tools:
            Draft202012Validator.check_schema(tool.parameters)
            if tool.name in names or tool.purpose in roles:
                raise ValueError('Each tool name and purpose must be unique within a manifest.')
            names.add(tool.name)
            roles.add(tool.purpose)
            if tool.parameters.get('type') != 'object' or tool.parameters.get('additionalProperties') is not False:
                raise ValueError('Tool parameters must be a closed JSON object.')
            if (tool.purpose in ('create', 'cancel')) != (tool.effect == 'write'):
                raise ValueError('Tool purpose and declared side effects disagree.')
            if not tool.bindings.keys() <= tool.parameters.get('properties', {}).keys():
                raise ValueError('A binding must name a declared tool parameter.')
            if tool.purpose == 'lookup' and tool.bindings:
                raise ValueError('Lookup arguments come from declared session slots.')
            from .authorization import ACTION_VERBS
            if not set(tool.authorization_verbs) <= ACTION_VERBS:
                raise ValueError('Authorization verbs must come from the supported imperative vocabulary; acknowledgments cannot authorize actions.')
            if any(not noun.strip() or len(noun) > 60 or not all(c.isalpha() or c == ' ' for c in noun) for noun in tool.authorization_objects):
                raise ValueError('Authorization objects must be nonempty noun phrases, at most 60 characters.')
            if tool.result_schema is not None:
                Draft202012Validator.check_schema(tool.result_schema)
        if 'lookup' not in roles:
            raise ValueError('This adapter requires one described lookup capability.')
        return self

    def tool(self, purpose: str) -> ToolSpec | None:
        return next((t for t in self.tools if t.purpose == purpose), None)


class InputEvent(ClosedModel):
    id: str = Field(min_length=1, max_length=100)
    type: Literal['text', 'partial', 'transcript', 'audio', 'frame', 'interrupt', 'control',
                  'tool_result', 'manifest', 'speech_status']
    text: str = Field(default='', max_length=12000)
    timestamp: str | None = None
    utterance_id: str | None = None
    end_of_turn: bool | None = None
    seen_results: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
