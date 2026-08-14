"""Package-owned configuration presentation catalog."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import cast
import tomllib

from tinysoul.infra.json import JsonObject, JsonValue, to_json_value

from .errors import ConfigCatalogError


class ConfigFieldImportance(StrEnum):
    PRIMARY = "primary"
    ADVANCED = "advanced"


class ConfigCollectionDeletePolicy(StrEnum):
    ALL = "all"
    CREATE_SOURCE_ONLY = "create_source_only"
    NONE = "none"


class ConfigValueKind(StrEnum):
    BOOLEAN = "boolean"
    INTEGER = "integer"
    NUMBER = "number"
    STRING = "string"
    ENUM = "enum"
    ENUM_LIST = "enum_list"
    STRING_LIST = "string_list"
    REFERENCE = "reference"
    REFERENCE_LIST = "reference_list"
    OBJECT = "object"
    OBJECT_LIST = "object_list"


@dataclass(frozen=True)
class ConfigChoiceDescriptor:
    value: str
    label: str

    def __post_init__(self) -> None:
        _require_identifier(self.value, "choice.value")
        _require_text(self.label, "choice.label")

    def to_json(self) -> JsonObject:
        return {"value": self.value, "label": self.label}


@dataclass(frozen=True)
class ConfigReferenceDescriptor:
    collection: str
    multiple: bool = False

    def __post_init__(self) -> None:
        _require_identifier(self.collection, "reference.collection")

    def to_json(self) -> JsonObject:
        return {"collection": self.collection, "multiple": self.multiple}


@dataclass(frozen=True)
class ConfigCollectionIdentityDescriptor:
    title: str
    description: str

    def __post_init__(self) -> None:
        _require_text(self.title, "collection.identity.title")
        _require_text(self.description, "collection.identity.description")

    def to_json(self) -> JsonObject:
        return {"title": self.title, "description": self.description}


@dataclass(frozen=True)
class ConfigFieldGroupDescriptor:
    id: str
    surface: str
    title: str
    description: str

    def __post_init__(self) -> None:
        _require_identifier(self.id, "field_group.id")
        _require_identifier(self.surface, "field_group.surface")
        _require_text(self.title, "field_group.title")
        _require_text(self.description, "field_group.description")

    def to_json(self) -> JsonObject:
        return {
            "id": self.id,
            "surface": self.surface,
            "title": self.title,
            "description": self.description,
        }


@dataclass(frozen=True)
class ConfigFieldDescriptor:
    path: str
    surface: str
    group: str
    title: str
    description: str
    value_kind: ConfigValueKind
    importance: ConfigFieldImportance = ConfigFieldImportance.PRIMARY
    choices: tuple[ConfigChoiceDescriptor, ...] = field(default_factory=tuple)
    reference: ConfigReferenceDescriptor | None = None
    credential_reference: bool = False

    def __post_init__(self) -> None:
        _validate_pattern(self.path, "field.path")
        _require_identifier(self.surface, "field.surface")
        _require_identifier(self.group, "field.group")
        _require_text(self.title, "field.title")
        _require_text(self.description, "field.description")
        if not isinstance(self.value_kind, ConfigValueKind):
            raise ConfigCatalogError("Configuration field kind is invalid")
        if not isinstance(self.importance, ConfigFieldImportance):
            raise ConfigCatalogError("Configuration field importance is invalid")
        choices = tuple(self.choices)
        if len({choice.value for choice in choices}) != len(choices):
            raise ConfigCatalogError(f"Configuration field choices are duplicated: {self.path}")
        if choices and self.value_kind not in {
            ConfigValueKind.ENUM,
            ConfigValueKind.ENUM_LIST,
        }:
            raise ConfigCatalogError(
                f"Configuration choices require enum kind: {self.path}"
            )
        if self.reference is not None and self.value_kind not in {
            ConfigValueKind.REFERENCE,
            ConfigValueKind.REFERENCE_LIST,
        }:
            raise ConfigCatalogError(
                f"Configuration reference requires reference kind: {self.path}"
            )
        object.__setattr__(self, "choices", choices)

    def matches(self, path: str) -> bool:
        return _matches_pattern(self.path, path)

    def to_json(self) -> JsonObject:
        result: JsonObject = {
            "path": self.path,
            "surface": self.surface,
            "group": self.group,
            "title": self.title,
            "description": self.description,
            "value_kind": self.value_kind.value,
            "importance": self.importance.value,
            "credential_reference": self.credential_reference,
        }
        if self.choices:
            result["choices"] = [choice.to_json() for choice in self.choices]
        if self.reference is not None:
            result["reference"] = self.reference.to_json()
        return result


@dataclass(frozen=True)
class ConfigDocumentFieldDescriptor:
    """Presentation metadata for one owner-managed document-local field."""

    document_set: str
    document_kind: str
    path: str
    surface: str
    group: str
    title: str
    description: str
    value_kind: ConfigValueKind
    importance: ConfigFieldImportance = ConfigFieldImportance.PRIMARY
    choices: tuple[ConfigChoiceDescriptor, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _require_identifier(self.document_set, "document_field.document_set")
        _require_identifier(self.document_kind, "document_field.document_kind")
        _validate_pattern(self.path, "document_field.path")
        _require_identifier(self.surface, "document_field.surface")
        _require_identifier(self.group, "document_field.group")
        _require_text(self.title, "document_field.title")
        _require_text(self.description, "document_field.description")
        if not isinstance(self.value_kind, ConfigValueKind):
            raise ConfigCatalogError("Configuration document field kind is invalid")
        if not isinstance(self.importance, ConfigFieldImportance):
            raise ConfigCatalogError(
                "Configuration document field importance is invalid"
            )
        choices = tuple(self.choices)
        if len({choice.value for choice in choices}) != len(choices):
            raise ConfigCatalogError(
                "Configuration document field choices are duplicated: "
                f"{self.document_set}:{self.document_kind}:{self.path}"
            )
        if choices and self.value_kind not in {
            ConfigValueKind.ENUM,
            ConfigValueKind.ENUM_LIST,
        }:
            raise ConfigCatalogError(
                "Configuration document choices require enum kind: "
                f"{self.document_set}:{self.document_kind}:{self.path}"
            )
        object.__setattr__(self, "choices", choices)

    def to_json(self) -> JsonObject:
        result: JsonObject = {
            "document_set": self.document_set,
            "document_kind": self.document_kind,
            "path": self.path,
            "surface": self.surface,
            "group": self.group,
            "title": self.title,
            "description": self.description,
            "value_kind": self.value_kind.value,
            "importance": self.importance.value,
        }
        if self.choices:
            result["choices"] = [choice.to_json() for choice in self.choices]
        return result


@dataclass(frozen=True)
class ConfigSurfaceDescriptor:
    id: str
    title: str
    description: str

    def __post_init__(self) -> None:
        _require_identifier(self.id, "surface.id")
        _require_text(self.title, "surface.title")
        _require_text(self.description, "surface.description")

    def to_json(self) -> JsonObject:
        return {"id": self.id, "title": self.title, "description": self.description}


@dataclass(frozen=True)
class ConfigCollectionDescriptor:
    id: str
    surface: str
    root: str
    title: str
    description: str
    identity: ConfigCollectionIdentityDescriptor
    create_source: str
    create_template: JsonObject
    allow_create: bool = True
    delete_policy: ConfigCollectionDeletePolicy = ConfigCollectionDeletePolicy.ALL

    def __post_init__(self) -> None:
        _require_identifier(self.id, "collection.id")
        _require_identifier(self.surface, "collection.surface")
        _validate_pattern(self.root, "collection.root")
        if "*" in self.root:
            raise ConfigCatalogError(
                f"Configuration collection root cannot contain wildcard: {self.root}"
            )
        _require_text(self.title, "collection.title")
        _require_text(self.description, "collection.description")
        if not isinstance(self.identity, ConfigCollectionIdentityDescriptor):
            raise ConfigCatalogError("Configuration collection identity is invalid")
        _require_identifier(self.create_source, "collection.create_source")
        if not isinstance(self.allow_create, bool):
            raise ConfigCatalogError("Configuration collection allow_create must be boolean")
        if not isinstance(self.delete_policy, ConfigCollectionDeletePolicy):
            raise ConfigCatalogError("Configuration collection delete policy is invalid")
        object.__setattr__(self, "create_template", dict(self.create_template))

    def to_json(self) -> JsonObject:
        return {
            "id": self.id,
            "surface": self.surface,
            "root": self.root,
            "title": self.title,
            "description": self.description,
            "identity": self.identity.to_json(),
            "create_source": self.create_source,
            "create_template": dict(self.create_template),
            "allow_create": self.allow_create,
            "delete_policy": self.delete_policy.value,
        }


@dataclass(frozen=True)
class ConfigCatalog:
    surfaces: tuple[ConfigSurfaceDescriptor, ...]
    field_groups: tuple[ConfigFieldGroupDescriptor, ...]
    collections: tuple[ConfigCollectionDescriptor, ...]
    fields: tuple[ConfigFieldDescriptor, ...]
    document_fields: tuple[ConfigDocumentFieldDescriptor, ...] = field(
        default_factory=tuple
    )
    rules: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        surfaces = tuple(self.surfaces)
        field_groups = tuple(self.field_groups)
        collections = tuple(self.collections)
        fields = tuple(self.fields)
        document_fields = tuple(self.document_fields)
        _require_unique((item.id for item in surfaces), "surface")
        _require_unique((item.id for item in field_groups), "field group")
        _require_unique((item.id for item in collections), "collection")
        _require_unique((item.path for item in fields), "field path")
        _require_unique(
            (
                f"{item.document_set}:{item.document_kind}:{item.path}"
                for item in document_fields
            ),
            "document field",
        )
        surface_ids = {item.id for item in surfaces}
        collection_ids = {item.id for item in collections}
        group_by_id = {item.id: item for item in field_groups}
        for item in (*field_groups, *collections, *fields, *document_fields):
            if item.surface not in surface_ids:
                raise ConfigCatalogError(
                    f"Configuration catalog references unknown surface: {item.surface}"
                )
        for item in fields:
            group = group_by_id.get(item.group)
            if group is None:
                raise ConfigCatalogError(
                    f"Configuration field references unknown group: {item.group}"
                )
            if group.surface != item.surface:
                raise ConfigCatalogError(
                    "Configuration field group belongs to another surface: "
                    f"{item.path}: {item.group}"
                )
            if item.reference is not None and item.reference.collection not in collection_ids:
                raise ConfigCatalogError(
                    "Configuration field references unknown collection: "
                    f"{item.reference.collection}"
                )
        for item in document_fields:
            group = group_by_id.get(item.group)
            if group is None:
                raise ConfigCatalogError(
                    "Configuration document field references unknown group: "
                    f"{item.document_set}:{item.document_kind}:{item.path}"
                )
            if group.surface != item.surface:
                raise ConfigCatalogError(
                    "Configuration document field group belongs to another surface: "
                    f"{item.document_set}:{item.document_kind}:{item.path}"
                )
        object.__setattr__(self, "surfaces", surfaces)
        object.__setattr__(self, "field_groups", field_groups)
        object.__setattr__(self, "collections", collections)
        object.__setattr__(self, "fields", fields)
        object.__setattr__(self, "document_fields", document_fields)
        object.__setattr__(self, "rules", dict(self.rules))

    def with_rules(self, rules: Mapping[str, object]) -> "ConfigCatalog":
        """Return this catalog with runtime-owned machine rules attached."""

        return ConfigCatalog(
            surfaces=self.surfaces,
            field_groups=self.field_groups,
            collections=self.collections,
            fields=self.fields,
            document_fields=self.document_fields,
            rules=cast(JsonObject, to_json_value(rules)),
        )

    def match(self, path: str) -> ConfigFieldDescriptor | None:
        matches = tuple(item for item in self.fields if item.matches(path))
        if len(matches) > 1:
            raise ConfigCatalogError(
                f"Configuration path matches multiple catalog fields: {path}"
            )
        return matches[0] if matches else None

    def to_json(self) -> JsonObject:
        return {
            "surfaces": [item.to_json() for item in self.surfaces],
            "field_groups": [item.to_json() for item in self.field_groups],
            "collections": [item.to_json() for item in self.collections],
            "fields": [item.to_json() for item in self.fields],
            "document_fields": [item.to_json() for item in self.document_fields],
            "rules": dict(self.rules),
        }


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
        (item for item in root.iterdir() if item.is_file() and item.name.endswith(".toml")),
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
                _optional_string(item, "importance", ConfigFieldImportance.PRIMARY.value, source)
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
        raise ConfigCatalogError(f"Configuration catalog {key} must be a list: {source}")
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


def _boolean(
    table: Mapping[str, object], key: str, default: bool, source: str
) -> bool:
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


def _require_identifier(value: str, key: str) -> None:
    _require_text(value, key)
    if any(character.isspace() for character in value):
        raise ConfigCatalogError(f"Configuration catalog {key} cannot contain whitespace")


def _require_text(value: str, key: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ConfigCatalogError(f"Configuration catalog {key} must be non-empty")


def _validate_pattern(value: str, key: str) -> None:
    _require_identifier(value, key)
    parts = value.split(".")
    if any(not part or ("*" in part and part != "*") for part in parts):
        raise ConfigCatalogError(f"Configuration catalog {key} is invalid: {value}")


def _matches_pattern(pattern: str, path: str) -> bool:
    expected = pattern.split(".")
    actual = path.split(".")
    return len(expected) == len(actual) and all(
        left == "*" or left == right for left, right in zip(expected, actual)
    )


def _require_unique(values: Iterable[str], kind: str) -> None:
    items = tuple(values)
    if len(items) != len(set(items)):
        raise ConfigCatalogError(f"Configuration catalog {kind} values must be unique")
