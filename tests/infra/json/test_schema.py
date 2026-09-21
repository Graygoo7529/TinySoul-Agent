import pytest

from tinysoul.infra.json.schema import (
    JSONSchema,
    JSONSchemaError,
    JSONSchemaValidationError,
)


def test_standard_schema_references_composition_and_literal_data() -> None:
    schema = JSONSchema(
        {
            "$defs": {"integer": {"type": "integer", "minimum": 2}},
            "type": "object",
            "properties": {
                "x": {"$ref": "#/$defs/integer"},
                "literal": {"const": {"$ref": "https://data.example/only-a-value"}},
            },
            "required": ["x"],
            "additionalProperties": False,
        }
    )
    schema.validate({"x": 2, "literal": {"$ref": "https://data.example/only-a-value"}})
    with pytest.raises(JSONSchemaValidationError):
        schema.validate({"x": 1})


@pytest.mark.parametrize(
    "schema",
    [
        {"$ref": "https://example.test/external"},
        {"$ref": "#/$defs/missing"},
        {
            "$vocabulary": {
                "https://json-schema.org/draft/unsupported/vocab/example": True
            }
        },
        {"$schema": "https://unsupported.test/schema"},
    ],
)
def test_unsupported_schema_is_rejected_before_call(schema) -> None:
    with pytest.raises(JSONSchemaError):
        JSONSchema(schema)
