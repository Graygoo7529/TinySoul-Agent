"""JSON support shared by TinySoul modules."""

from .codec import JsonTypeError, dumps_json, to_json_object, to_json_value
from .types import JsonObject, JsonScalar, JsonValue

__all__ = [
    "JsonObject",
    "JsonScalar",
    "JsonTypeError",
    "JsonValue",
    "dumps_json",
    "to_json_object",
    "to_json_value",
]
