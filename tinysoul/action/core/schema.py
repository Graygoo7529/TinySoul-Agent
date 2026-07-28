"""TinySoul action tool schema validation."""

from __future__ import annotations

from collections.abc import Mapping

from tinysoul.infra.config import ConfigError
from tinysoul.infra.json import JsonObject, JsonValue

SUPPORTED_SCHEMA_KEYS = {
    "additionalProperties",
    "default",
    "description",
    "enum",
    "items",
    "maximum",
    "minimum",
    "properties",
    "required",
    "type",
}
SUPPORTED_TYPES = {
    "array",
    "boolean",
    "integer",
    "null",
    "number",
    "object",
    "string",
}


class ActionSchemaValidationError(ValueError):
    """Raised when action parameters do not match an action schema."""


class ActionSchemaDefinitionError(ValueError):
    """Raised when an action schema does not match TinySoul's supported subset."""

    def __init__(
        self,
        message: str,
        *,
        key: str = "",
        value: object = None,
        expected: str = "",
    ) -> None:
        super().__init__(message)
        self.message = message
        self.key = key
        self.value = value
        self.expected = expected

    def __str__(self) -> str:
        parts = [self.message]
        if self.key:
            parts.append(f"key={self.key}")
        if self.expected:
            parts.append(f"expected={self.expected}")
        if self.value is not None:
            parts.append(f"value={self.value!r}")
        return " | ".join(parts)


def check_action_schema(schema: JsonObject, *, key: str) -> None:
    """Check a TOML-loaded action schema and report configuration errors."""

    try:
        validate_action_schema_definition(schema, key=key)
    except ActionSchemaDefinitionError as exc:
        raise ConfigError(
            exc.message,
            key=exc.key,
            value=exc.value,
            expected=exc.expected,
        ) from exc


def validate_action_schema_definition(schema: JsonObject, *, key: str) -> None:
    """Check that an action schema uses the supported TinySoul subset."""

    _check_schema_node(schema, key=key, root=True)


def validate_action_params(params: JsonObject, *, schema: JsonObject) -> None:
    """Validate action parameters against the supported TinySoul schema subset."""

    _validate_value(params, schema=schema, path="params")


def _check_schema_node(schema: JsonObject, *, key: str, root: bool = False) -> None:
    for name in schema:
        if name not in SUPPORTED_SCHEMA_KEYS:
            raise ActionSchemaDefinitionError(
                "Action tool schema keyword is not supported",
                key=f"{key}.{name}",
                value=name,
                expected=", ".join(sorted(SUPPORTED_SCHEMA_KEYS)),
            )

    schema_type = schema.get("type")
    if root and schema_type != "object":
        raise ActionSchemaDefinitionError(
            "Action tool schema root type must be object",
            key=f"{key}.type",
            value=schema_type,
            expected="object",
        )
    if schema_type is not None:
        if not isinstance(schema_type, str) or schema_type not in SUPPORTED_TYPES:
            raise ActionSchemaDefinitionError(
                "Action tool schema type is not supported",
                key=f"{key}.type",
                value=schema_type,
                expected=", ".join(sorted(SUPPORTED_TYPES)),
            )

    description = schema.get("description")
    if description is not None and not isinstance(description, str):
        raise ActionSchemaDefinitionError(
            "Action tool schema description must be a string",
            key=f"{key}.description",
            value=description,
            expected="str",
        )

    enum_values = schema.get("enum")
    if enum_values is not None and not isinstance(enum_values, list):
        raise ActionSchemaDefinitionError(
            "Action tool schema enum must be a list",
            key=f"{key}.enum",
            value=enum_values,
            expected="list",
        )

    _check_numeric_boundaries(schema, key=key)

    if schema_type == "object" or root:
        _check_object_schema(schema, key=key)
    elif schema_type == "array":
        _check_array_schema(schema, key=key)
    else:
        _reject_keys(
            schema,
            {"properties", "required", "additionalProperties", "items"},
            key=key,
        )

    if "default" in schema:
        try:
            _validate_value(schema["default"], schema=schema, path=f"{key}.default")
        except ActionSchemaValidationError as exc:
            raise ActionSchemaDefinitionError(
                "Action tool schema default does not satisfy its schema",
                key=f"{key}.default",
                value=schema["default"],
                expected="value accepted by the containing schema",
            ) from exc


def _check_numeric_boundaries(schema: JsonObject, *, key: str) -> None:
    present = tuple(name for name in ("minimum", "maximum") if name in schema)
    if not present:
        return
    schema_type = schema.get("type")
    if schema_type not in {"integer", "number"}:
        raise ActionSchemaDefinitionError(
            "Action tool schema numeric boundary requires a numeric type",
            key=f"{key}.{present[0]}",
            value=schema[present[0]],
            expected="integer or number schema",
        )
    for name in present:
        value = schema[name]
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ActionSchemaDefinitionError(
                "Action tool schema numeric boundary must be a number",
                key=f"{key}.{name}",
                value=value,
                expected="int or float",
            )
    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    if (
        isinstance(minimum, int | float)
        and not isinstance(minimum, bool)
        and isinstance(maximum, int | float)
        and not isinstance(maximum, bool)
        and minimum > maximum
    ):
        raise ActionSchemaDefinitionError(
            "Action tool schema numeric boundaries are inconsistent",
            key=f"{key}.minimum",
            value=minimum,
            expected=f"<= {maximum}",
        )


def _check_object_schema(schema: JsonObject, *, key: str) -> None:
    _reject_keys(schema, {"items"}, key=key)
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise ActionSchemaDefinitionError(
            "Action tool schema properties must be an object",
            key=f"{key}.properties",
            value=properties,
            expected="object",
        )
    for property_name, property_schema in properties.items():
        if not isinstance(property_schema, dict):
            raise ActionSchemaDefinitionError(
                "Action tool property schema must be an object",
                key=f"{key}.properties.{property_name}",
                value=property_schema,
                expected="object",
            )
        _check_schema_node(property_schema, key=f"{key}.properties.{property_name}")

    required = schema.get("required", [])
    if not isinstance(required, list):
        raise ActionSchemaDefinitionError(
            "Action tool schema required must be a list of strings",
            key=f"{key}.required",
            value=required,
            expected="list[str]",
        )
    for item in required:
        if not isinstance(item, str) or not item:
            raise ActionSchemaDefinitionError(
                "Action tool schema required must contain non-empty strings",
                key=f"{key}.required",
                value=required,
                expected="list[str]",
            )
        if item not in properties:
            raise ActionSchemaDefinitionError(
                "Action tool schema required field must be declared in properties",
                key=f"{key}.required",
                value=item,
                expected="declared property name",
            )

    additional = schema.get("additionalProperties", True)
    if not isinstance(additional, bool):
        raise ActionSchemaDefinitionError(
            "Action tool schema additionalProperties must be boolean",
            key=f"{key}.additionalProperties",
            value=additional,
            expected="bool",
        )


def _check_array_schema(schema: JsonObject, *, key: str) -> None:
    _reject_keys(schema, {"properties", "required", "additionalProperties"}, key=key)
    items = schema.get("items")
    if items is None:
        return
    if not isinstance(items, dict):
        raise ActionSchemaDefinitionError(
            "Action tool schema items must be an object",
            key=f"{key}.items",
            value=items,
            expected="object",
        )
    _check_schema_node(items, key=f"{key}.items")


def _reject_keys(schema: Mapping[str, JsonValue], names: set[str], *, key: str) -> None:
    for name in names:
        if name in schema:
            raise ActionSchemaDefinitionError(
                "Action tool schema keyword is not valid for this type",
                key=f"{key}.{name}",
                value=name,
                expected="keyword compatible with schema type",
            )


def _validate_value(value: JsonValue, *, schema: JsonObject, path: str) -> None:
    expected_type = schema.get("type")
    if expected_type is not None:
        if not isinstance(expected_type, str):
            raise ActionSchemaValidationError(f"Action parameter schema type for {path} is invalid")
        if not _matches_json_type(value, expected_type):
            raise ActionSchemaValidationError(f"Action parameter {path} must be {expected_type}")

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and value not in enum_values:
        raise ActionSchemaValidationError(f"Action parameter {path} must be one of the allowed values")

    if isinstance(value, int | float) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, int | float) and value < minimum:
            raise ActionSchemaValidationError(
                f"Action parameter {path} must be >= {minimum}"
            )
        if isinstance(maximum, int | float) and value > maximum:
            raise ActionSchemaValidationError(
                f"Action parameter {path} must be <= {maximum}"
            )

    if expected_type == "object":
        if not isinstance(value, dict):
            raise ActionSchemaValidationError(f"Action parameter {path} must be object")
        _validate_object(value, schema=schema, path=path)
    elif expected_type == "array":
        if not isinstance(value, list):
            raise ActionSchemaValidationError(f"Action parameter {path} must be array")
        items_schema = schema.get("items")
        if isinstance(items_schema, dict):
            for index, item in enumerate(value):
                _validate_value(item, schema=items_schema, path=f"{path}[{index}]")


def _validate_object(value: JsonObject, *, schema: JsonObject, path: str) -> None:
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise ActionSchemaValidationError(f"Action parameter schema properties for {path} is invalid")

    required = schema.get("required", [])
    if not isinstance(required, list):
        raise ActionSchemaValidationError(f"Action parameter schema required for {path} is invalid")
    for name in required:
        if isinstance(name, str) and name not in value:
            raise ActionSchemaValidationError(f"Missing required action parameter: {name}")

    if schema.get("additionalProperties") is False:
        for name in value:
            if name not in properties:
                raise ActionSchemaValidationError(f"Unexpected action parameter: {name}")

    for name, item in value.items():
        property_schema = properties.get(name)
        if isinstance(property_schema, dict):
            _validate_value(item, schema=property_schema, path=f"{path}.{name}")


def _matches_json_type(value: JsonValue, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "null":
        return value is None
    return False
