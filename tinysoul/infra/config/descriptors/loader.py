"""Package-owned configuration presentation catalog."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import field
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import cast
import tomllib

from tinysoul.infra.json import JsonObject, to_json_value

from ..errors import ConfigCatalogError


from .models import (
    ConfigFieldImportance,
    ConfigCollectionDeletePolicy,
    ConfigValueKind,
    ConfigChoiceDescriptor,
    ConfigReferenceDescriptor,
    ConfigCollectionIdentityDescriptor,
    ConfigFieldGroupDescriptor,
    ConfigFieldDescriptor,
    ConfigDocumentFieldDescriptor,
    ConfigSurfaceDescriptor,
    ConfigCollectionDescriptor,
    ConfigCatalog,
)


def load_config_catalog() -> ConfigCatalog:
    """Load the complete package-owned configuration presentation catalog."""

    root = files("tinysoul.infra.config").joinpath("catalog")
    if not root.is_dir():
        raise ConfigCatalogError("Configuration catalog directory is missing")
    surfaces: list[ConfigSurfaceDescriptor] = []
    field_groups: list[ConfigFieldGroupDescriptor] = []
    collections: list[ConfigCollectionDescriptor] = []
    fields_: list[ConfigFieldDescriptor] = []
    document_fields: list[ConfigDocumentFieldDescriptor] = []
    resources = sorted(
        (
            item
            for item in root.iterdir()
            if item.is_file() and item.name.endswith(".toml")
        ),
        key=lambda item: item.name,
    )
    if not resources:
        raise ConfigCatalogError("Configuration catalog has no TOML resources")
    for resource in resources:
        document = _load_document(resource)
        _reject_unknown(
            document,
            {"surface", "field_group", "collection", "field", "document_field"},
            resource.name,
        )
        surfaces.extend(_parse_surfaces(document.get("surface", []), resource.name))
        field_groups.extend(
            _parse_field_groups(document.get("field_group", []), resource.name)
        )
        collections.extend(
            _parse_collections(document.get("collection", []), resource.name)
        )
        fields_.extend(_parse_fields(document.get("field", []), resource.name))
        document_fields.extend(
            _parse_document_fields(
                document.get("document_field", []),
                resource.name,
            )
        )
    return ConfigCatalog(
        surfaces=tuple(surfaces),
        field_groups=tuple(field_groups),
        collections=tuple(collections),
        fields=tuple(fields_),
        document_fields=tuple(document_fields),
    )


def _load_document(resource: Traversable) -> dict[str, object]:
    try:
        return _string_mapping(
            cast(
                Mapping[object, object],
                tomllib.loads(resource.read_text(encoding="utf-8")),
            )
        )
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigCatalogError(
            f"Configuration catalog cannot be loaded: {resource.name}: {exc}"
        ) from exc


def _parse_surfaces(value: object, source: str) -> list[ConfigSurfaceDescriptor]:
    result: list[ConfigSurfaceDescriptor] = []
    for item in _table_list(value, "surface", source):
        _reject_unknown(item, {"id", "title", "description"}, source)
        result.append(
            ConfigSurfaceDescriptor(
                id=_string(item, "id", source),
                title=_string(item, "title", source),
                description=_string(item, "description", source),
            )
        )
    return result


def _parse_field_groups(
    value: object,
    source: str,
) -> list[ConfigFieldGroupDescriptor]:
    result: list[ConfigFieldGroupDescriptor] = []
    for item in _table_list(value, "field_group", source):
        _reject_unknown(item, {"id", "surface", "title", "description"}, source)
        result.append(
            ConfigFieldGroupDescriptor(
                id=_string(item, "id", source),
                surface=_string(item, "surface", source),
                title=_string(item, "title", source),
                description=_string(item, "description", source),
            )
        )
    return result


def _parse_collections(value: object, source: str) -> list[ConfigCollectionDescriptor]:
    result: list[ConfigCollectionDescriptor] = []
    allowed = {
        "id",
        "surface",
        "root",
        "title",
        "description",
        "identity",
        "create_source",
        "create_template",
        "allow_create",
        "delete_policy",
    }
    for item in _table_list(value, "collection", source):
        _reject_unknown(item, allowed, source)
        template = item.get("create_template", {})
        if not isinstance(template, Mapping):
            raise ConfigCatalogError(
                f"Configuration collection template must be a table: {source}"
            )
        try:
            delete_policy = ConfigCollectionDeletePolicy(
                _optional_string(
                    item,
                    "delete_policy",
                    ConfigCollectionDeletePolicy.ALL.value,
                    source,
                )
            )
        except ValueError as exc:
            raise ConfigCatalogError(
                f"Configuration collection delete policy is invalid: {source}"
            ) from exc
        result.append(
            ConfigCollectionDescriptor(
                id=_string(item, "id", source),
                surface=_string(item, "surface", source),
                root=_string(item, "root", source),
                title=_string(item, "title", source),
                description=_string(item, "description", source),
                identity=_parse_collection_identity(item.get("identity"), source),
                create_source=_string(item, "create_source", source),
                create_template=cast(JsonObject, to_json_value(template)),
                allow_create=_boolean(item, "allow_create", True, source),
                delete_policy=delete_policy,
            )
        )
    return result


def _parse_collection_identity(
    value: object,
    source: str,
) -> ConfigCollectionIdentityDescriptor:
    if not isinstance(value, Mapping):
        raise ConfigCatalogError(
            f"Configuration collection identity must be a table: {source}"
        )
    table = _string_mapping(cast(Mapping[object, object], value))
    _reject_unknown(table, {"title", "description"}, source)
    return ConfigCollectionIdentityDescriptor(
        title=_string(table, "title", source),
        description=_string(table, "description", source),
    )


def _parse_fields(value: object, source: str) -> list[ConfigFieldDescriptor]:
    result: list[ConfigFieldDescriptor] = []
    allowed = {
        "path",
        "surface",
        "group",
        "title",
        "description",
        "value_kind",
        "importance",
        "choices",
        "reference",
        "credential_reference",
    }
    for item in _table_list(value, "field", source):
        _reject_unknown(item, allowed, source)
        try:
            kind = ConfigValueKind(_string(item, "value_kind", source))
            importance = ConfigFieldImportance(
                _optional_string(
                    item, "importance", ConfigFieldImportance.PRIMARY.value, source
                )
            )
        except ValueError as exc:
            raise ConfigCatalogError(
                f"Configuration field enum is invalid: {source}"
            ) from exc
        result.append(
            ConfigFieldDescriptor(
                path=_string(item, "path", source),
                surface=_string(item, "surface", source),
                group=_string(item, "group", source),
                title=_string(item, "title", source),
                description=_string(item, "description", source),
                value_kind=kind,
                importance=importance,
                choices=_parse_choices(item.get("choices", []), source),
                reference=_parse_reference(item.get("reference"), source),
                credential_reference=_boolean(
                    item, "credential_reference", False, source
                ),
            )
        )
    return result


def _parse_document_fields(
    value: object,
    source: str,
) -> list[ConfigDocumentFieldDescriptor]:
    result: list[ConfigDocumentFieldDescriptor] = []
    allowed = {
        "document_set",
        "document_kind",
        "path",
        "surface",
        "group",
        "title",
        "description",
        "value_kind",
        "importance",
        "choices",
    }
    for item in _table_list(value, "document_field", source):
        _reject_unknown(item, allowed, source)
        try:
            kind = ConfigValueKind(_string(item, "value_kind", source))
            importance = ConfigFieldImportance(
                _optional_string(
                    item,
                    "importance",
                    ConfigFieldImportance.PRIMARY.value,
                    source,
                )
            )
        except ValueError as exc:
            raise ConfigCatalogError(
                f"Configuration document field enum is invalid: {source}"
            ) from exc
        result.append(
            ConfigDocumentFieldDescriptor(
                document_set=_string(item, "document_set", source),
                document_kind=_string(item, "document_kind", source),
                path=_string(item, "path", source),
                surface=_string(item, "surface", source),
                group=_string(item, "group", source),
                title=_string(item, "title", source),
                description=_string(item, "description", source),
                value_kind=kind,
                importance=importance,
                choices=_parse_choices(item.get("choices", []), source),
            )
        )
    return result


def _parse_choices(value: object, source: str) -> tuple[ConfigChoiceDescriptor, ...]:
    result: list[ConfigChoiceDescriptor] = []
    for item in _table_list(value, "choices", source):
        _reject_unknown(item, {"value", "label"}, source)
        result.append(
            ConfigChoiceDescriptor(
                value=_string(item, "value", source),
                label=_string(item, "label", source),
            )
        )
    return tuple(result)


def _parse_reference(value: object, source: str) -> ConfigReferenceDescriptor | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ConfigCatalogError(f"Configuration reference must be a table: {source}")
    table = _string_mapping(cast(Mapping[object, object], value))
    _reject_unknown(table, {"collection", "multiple"}, source)
    return ConfigReferenceDescriptor(
        collection=_string(table, "collection", source),
        multiple=_boolean(table, "multiple", False, source),
    )


def _table_list(value: object, key: str, source: str) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ConfigCatalogError(
            f"Configuration catalog {key} must be a list: {source}"
        )
    result: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ConfigCatalogError(
                f"Configuration catalog {key} items must be tables: {source}"
            )
        result.append(_string_mapping(cast(Mapping[object, object], item)))
    return result


def _string(table: Mapping[str, object], key: str, source: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigCatalogError(
            f"Configuration catalog {key} must be a non-empty string: {source}"
        )
    return value


def _optional_string(
    table: Mapping[str, object], key: str, default: str, source: str
) -> str:
    value = table.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise ConfigCatalogError(
            f"Configuration catalog {key} must be a non-empty string: {source}"
        )
    return value


def _boolean(table: Mapping[str, object], key: str, default: bool, source: str) -> bool:
    value = table.get(key, default)
    if not isinstance(value, bool):
        raise ConfigCatalogError(
            f"Configuration catalog {key} must be a boolean: {source}"
        )
    return value


def _string_mapping(value: Mapping[object, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ConfigCatalogError("Configuration catalog keys must be strings")
        result[key] = item
    return result


def _reject_unknown(
    table: Mapping[str, object], allowed: set[str], source: str
) -> None:
    unknown = sorted(key for key in table if key not in allowed)
    if unknown:
        raise ConfigCatalogError(
            f"Configuration catalog has unknown keys in {source}: {', '.join(unknown)}"
        )
