"""The small model API shared by desktop Pydantic 2 and Android's pure-Python 1.x."""
from copy import deepcopy
import re

import pydantic

if int(pydantic.VERSION.split('.')[0]) >= 2:
    from pydantic import BaseModel, ConfigDict, Field

    class ClosedModel(BaseModel):
        model_config = ConfigDict(extra='forbid')
else:
    from pydantic import BaseModel as _BaseModel, Field as _Field, root_validator

    def Field(*args, **kwargs):
        if 'pattern' in kwargs: kwargs['regex'] = kwargs.pop('pattern')
        return _Field(*args, **kwargs)

    class BaseModel(_BaseModel):
        class Config:
            smart_union = True

        @root_validator(pre=True)
        def preserve_string_types(cls, values):
            # Keep Pydantic 2's JSON shapes at the authority boundary. V1 would
            # turn numbers into words and arrays of pairs into dictionaries.
            def check(field, value):
                if value is None: return  # Pydantic enforces field nullability.
                if field.key_field is not None:
                    if not isinstance(value, dict): raise ValueError(f'{field.name} must be an object.')
                    for key, child in value.items():
                        check(field.key_field, key)
                        if field.sub_fields: check(field.sub_fields[0], child)
                elif field.shape != 1 and field.sub_fields and isinstance(value, (list, tuple, set, frozenset)):
                    for child in value: check(field.sub_fields[0], child)
                elif field.shape == 1 and isinstance(field.type_, type):
                    if issubclass(field.type_, str):
                        if not isinstance(value, (str, bytes, bytearray)): raise ValueError(f'{field.name} must be text.')
                        pattern = field.field_info.regex
                        if isinstance(value, str) and pattern and not re.fullmatch(pattern, value):
                            raise ValueError(f'{field.name} does not match its complete pattern.')
                    elif issubclass(field.type_, _BaseModel) and not isinstance(value, (dict, field.type_)):
                        raise ValueError(f'{field.name} must be an object.')
            if isinstance(values, dict):
                for name, field in cls.__fields__.items():
                    if name in values: check(field, values[name])
            return values

        @classmethod
        def model_validate(cls, value):
            if not isinstance(value, (dict, cls)): raise ValueError('Expected a JSON object.')
            return cls.parse_obj(value)

        def model_dump(self, **kwargs):
            return self.dict(**kwargs)

        def model_copy(self, **kwargs):
            return self.copy(**kwargs)

        @classmethod
        def model_json_schema(cls):
            def convert(value):
                if isinstance(value, dict):
                    return {('$defs' if k == 'definitions' else k): convert(v) for k, v in value.items()}
                if isinstance(value, list): return [convert(v) for v in value]
                if isinstance(value, str) and value.startswith('#/definitions/'):
                    return value.replace('#/definitions/', '#/$defs/', 1)
                return value
            return convert(deepcopy(cls.schema()))

    class ClosedModel(BaseModel):
        class Config(BaseModel.Config):
            extra = 'forbid'
