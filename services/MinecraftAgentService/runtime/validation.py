"""Detailed tool argument errors for Minecraft agents."""

import math


def validate(value, schema, path='argument'):
    supported = {'type', 'properties', 'required', 'additionalProperties', 'items',
                 'description', 'enum', 'minimum', 'maximum', 'minLength', 'maxLength'}
    if set(schema) - supported:
        raise ValueError(f'{path}: unsupported tool schema keywords: {sorted(set(schema) - supported)}')
    kind = schema.get('type')
    matches = {'object': isinstance(value, dict), 'array': isinstance(value, list),
               'string': isinstance(value, str), 'integer': type(value) is int,
               'number': type(value) in (int, float), 'boolean': type(value) is bool,
               'null': value is None}
    if kind not in matches or not matches[kind]:
        raise ValueError(f'{path}: expected type {kind}, got {type(value).__name__}. '
                         'Use the type specified in the tool schema.')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(f'{path}: value is not an allowed option. Choose one of {schema["enum"]!r}.')
    if kind == 'object':
        props = schema.get('properties', {})
        missing = set(schema.get('required', [])) - set(value)
        if missing:
            raise ValueError(f'{path}: missing required fields {sorted(missing)}. '
                             'Supply these fields before retrying.')
        if not schema.get('additionalProperties', False) and set(value) - set(props):
            raise ValueError(f'{path}: unknown fields {sorted(set(value) - set(props))}. '
                             f'Allowed fields: {sorted(props)}. Remove or rename the unknown fields.')
        for key, item in value.items():
            if key in props:
                validate(item, props[key], f'{path}.{key}')
    if kind == 'array':
        for index, item in enumerate(value):
            validate(item, schema['items'], f'{path}[{index}]')
    if kind in ('number', 'integer'):
        if type(value) is float and not math.isfinite(value):
            raise ValueError(f'{path}: got {value}; expected a finite number, not NaN or infinity.')
        if value < schema.get('minimum', value) or value > schema.get('maximum', value):
            minimum = schema.get('minimum', '-infinity')
            maximum = schema.get('maximum', 'infinity')
            raise ValueError(f'{path}: got {value}; allowed range is {minimum} to {maximum} inclusive. '
                             'Retry with a value within this range.')
    if kind == 'string':
        if len(value) < schema.get('minLength', 0) or len(value) > schema.get('maxLength', len(value)):
            minimum = schema.get('minLength', 0)
            maximum = schema.get('maxLength', 'unbounded')
            raise ValueError(f'{path} length is {len(value)}; allowed range is {minimum}–{maximum} characters. '
                             'Adjust this argument to fit the allowed range.')

