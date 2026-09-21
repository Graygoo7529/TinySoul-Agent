"""Full JSON Schema validation without network reference resolution."""

from jsonschema import Draft7Validator, Draft201909Validator, Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT7, DRAFT201909, DRAFT202012
from tinysoul.infra.json import JsonObject, JsonValue


class JSONSchemaError(Exception):
    """Unsupported or invalid schema, without exposing source data."""


class JSONSchemaValidationError(JSONSchemaError):
    """The instance does not satisfy the validated schema."""


class JSONSchema:
    def __init__(self, schema: JsonObject) -> None:
        dialect = schema.get("$schema", "https://json-schema.org/draft/2020-12/schema")
        validators = {
            "https://json-schema.org/draft/2020-12/schema": (
                Draft202012Validator,
                DRAFT202012,
            ),
            "https://json-schema.org/draft/2019-09/schema": (
                Draft201909Validator,
                DRAFT201909,
            ),
            "http://json-schema.org/draft-07/schema#": (Draft7Validator, DRAFT7),
            "https://json-schema.org/draft-07/schema": (Draft7Validator, DRAFT7),
        }
        if not isinstance(dialect, str) or dialect not in validators:
            raise JSONSchemaError("Schema dialect is unsupported.")
        validator, specification = validators[dialect]
        try:
            validator.check_schema(schema)
            resource = Resource.from_contents(
                schema, default_specification=specification
            )
            registry = Registry().with_resource("", resource)
            resolver = registry.resolver()
            supported = set(validator.META_SCHEMA.get("$vocabulary", {}))
            pending = [(resource, resolver)]
            while pending:
                current, local = pending.pop()
                contents = current.contents
                if isinstance(contents, dict):
                    vocabulary = contents.get("$vocabulary", {})
                    if isinstance(vocabulary, dict) and any(
                        required is True and uri not in supported
                        for uri, required in vocabulary.items()
                    ):
                        raise JSONSchemaError(
                            "Schema requires an unsupported vocabulary."
                        )
                    for name in ("$ref", "$dynamicRef", "$recursiveRef"):
                        reference = contents.get(name)
                        if reference is None:
                            continue
                        if not isinstance(reference, str) or not reference.startswith(
                            "#"
                        ):
                            raise JSONSchemaError(
                                "Schema requires an external reference."
                            )
                        local.lookup(reference)
                pending.extend(
                    (child, local.in_subresource(child))
                    for child in current.subresources()
                )
            self._validator = validator(schema, registry=registry)
        except (SchemaError, Unresolvable) as exc:
            raise JSONSchemaError(
                "Schema is invalid or has an unresolved reference."
            ) from exc

    def validate(self, value: JsonValue) -> None:
        try:
            error = next(iter(self._validator.iter_errors(value)), None)
        except Unresolvable as exc:
            raise JSONSchemaError("Schema reference could not be resolved.") from exc
        if error is not None:
            raise JSONSchemaValidationError("Value does not match its schema.")
