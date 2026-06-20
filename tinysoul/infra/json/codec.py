"""JSON validation and serialization helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping

from .types import JsonObject, JsonValue


class JsonTypeError(TypeError):
    """Raised when a value cannot be represented as JSON."""


def to_json_value(value: object) -> JsonValue:
    """Convert a dynamic value into a JSON value."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [to_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [to_json_value(item) for item in value]
    if isinstance(value, Mapping):
        result: JsonObject = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise JsonTypeError("JSON object keys must be strings")
            result[key] = to_json_value(item)
        return result
    raise JsonTypeError(f"Value is not JSON serializable: {type(value).__name__}")


def to_json_object(value: object) -> JsonObject:
    """Convert a dynamic value into a JSON object."""

    converted = to_json_value(value)
    if not isinstance(converted, dict):
        raise JsonTypeError("JSON value must be an object")
    return converted


def dumps_json(value: JsonValue) -> str:
    """Serialize a JSON value with stable formatting."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
