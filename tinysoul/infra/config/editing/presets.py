"""Named, source-independent definitions of the configured model/routing scopes."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from tinysoul.infra.filesystem import atomic_write_text
from tinysoul.infra.json import JsonObject, JsonValue, to_json_object

from ..environment import ConfigEnvironment
from ..errors import ConfigError

_GROUPS = ("llm.tasks", "action.models.bindings")
_ROUTING = ("loop.cycle.phase1_task_profile", "loop.cycle.phase2_task_profile")
_BUDGETS = (
    "loop.user.max_cycles",
    "reflection.home.max_cycles",
    "reflection.memory.max_cycles",
    "session.max_background_chars",
    "context.max_image_bytes",
    "context.compression_trigger_ratio",
    "context.compression_target_ratio",
    "context.trace_chunk_chars",
    "context.trace_branch_factor",
    "context.trace_min_hot_entries",
    "context.max_trace_inspect_chars",
)
_RETRIEVAL_BUDGETS = (
    "max_steps",
    "max_snapshot_chars",
    "page.max_items",
    "page.max_chars",
)


def _get(tree: JsonObject, path: str) -> JsonValue:
    value: JsonValue = tree
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _set(tree: JsonObject, path: str, value: JsonValue) -> None:
    head, separator, tail = path.partition(".")
    if not separator:
        if value is None:
            tree.pop(head, None)
        else:
            tree[head] = value
        return
    child = tree.get(head)
    if child is None:
        if value is None:
            return
        child = {}
        tree[head] = child
    if not isinstance(child, dict):
        raise ConfigError("Preset target is not an object", key=path)
    _set(child, tail, value)


def _object(value: JsonValue, key: str) -> JsonObject:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError("Preset configuration must be an object", key=key)
    return value


def _bindings(value: JsonValue) -> dict[str, JsonObject]:
    result: dict[str, JsonObject] = {}
    if value is None:
        return result
    if not isinstance(value, list):
        raise ConfigError("Preset bindings must be a list", key="action.models.bindings")
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("consumer"), str):
            raise ConfigError("Preset binding needs a consumer", key="action.models.bindings")
        consumer = item["consumer"]
        assert isinstance(consumer, str)
        if consumer in result:
            raise ConfigError("Preset binding consumer is duplicated", key=consumer)
        result[consumer] = item
    return result


@dataclass(frozen=True)
class PresetChange:
    """A declaration change; path segments keep dotted consumer IDs atomic."""

    path: tuple[str, ...]
    before: JsonValue
    after: JsonValue

    def __post_init__(self) -> None:
        if not self.path or any(not part for part in self.path):
            raise ConfigError("Preset change needs a path", key="preset.changes")

    def to_json(self) -> JsonObject:
        # None means absent/default: TOML configuration cannot contain null.
        return {"path": list(self.path), "before": self.before, "after": self.after}


def _changes(path: tuple[str, ...], before: JsonValue, after: JsonValue) -> list[PresetChange]:
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        return [
            change
            for key in sorted(before.keys() | after.keys())
            for change in _changes((*path, key), before.get(key), after.get(key))
        ]
    return [PresetChange(path, before, after)]


@dataclass(frozen=True)
class PresetDefinition:
    """Null represents the owner default, never a TOML null assignment."""

    values: JsonObject
    retrieval: JsonObject
    include_budgets: bool = True

    def __post_init__(self) -> None:
        expected = {*_GROUPS, *_ROUTING, *(_BUDGETS if self.include_budgets else ())}
        if set(self.values) != expected:
            raise ConfigError("Preset scopes are invalid", key="preset.definition")
        for profile, task in _object(self.values["llm.tasks"], "llm.tasks").items():
            if not profile or "." in profile or not isinstance(task, dict):
                raise ConfigError("Preset task definition is invalid", key=profile)
        _bindings(self.values["action.models.bindings"])
        for consumer, fields in self.retrieval.items():
            if not isinstance(fields, dict):
                raise ConfigError(
                    "Preset retrieval fields must be an object", key=consumer
                )
            allowed = {"query.channels"}
            if self.include_budgets:
                allowed.update(
                    (
                        *_RETRIEVAL_BUDGETS,
                        "select.max_input_chars",
                        "rerank.max_input_chars",
                    )
                )
            if set(fields) - allowed:
                raise ConfigError(
                    "Preset contains unmanaged retrieval fields", key=consumer
                )
        object.__setattr__(self, "values", to_json_object(self.values))
        object.__setattr__(self, "retrieval", to_json_object(self.retrieval))

    @classmethod
    def capture(
        cls, environment: ConfigEnvironment, *, include_budgets: bool = True
    ) -> PresetDefinition:
        sections = {
            key: to_json_object(environment.section_tree(key))
            for key in ("llm", "action", "loop", "reflection", "session", "context")
        }
        values: JsonObject = {}
        for path in (*_GROUPS, *_ROUTING, *(_BUDGETS if include_budgets else ())):
            section, _, tail = path.partition(".")
            values[path] = _get(sections[section], tail)
        policies = _get(sections["action"], "retrieval") or {}
        if not isinstance(policies, dict):
            raise ConfigError(
                "Retrieval configuration is invalid", key="action.retrieval"
            )
        retrieval: JsonObject = {}
        for consumer, policy in policies.items():
            if not isinstance(policy, dict):
                raise ConfigError("Retrieval policy must be an object", key=consumer)
            paths = ["query.channels"]
            if include_budgets:
                paths.extend(_RETRIEVAL_BUDGETS)
                operations = policy.get("operations", [])
                for op in ("select", "rerank"):
                    if isinstance(operations, list) and op in operations:
                        paths.append(f"{op}.max_input_chars")
            retrieval[consumer] = {path: _get(policy, path) for path in paths}
        return cls(values, retrieval, include_budgets)

    def replacements(self, environment: ConfigEnvironment) -> JsonObject:
        """Writable units, preserving every undeclared member of atomic maps/lists."""
        result = {path: value for path, value in self.values.items() if path not in _GROUPS}
        for profile, task in _object(self.values["llm.tasks"], "llm.tasks").items():
            result[f"llm.tasks.{profile}"] = task
        action = to_json_object(environment.section_tree("action"))
        declared_bindings = _bindings(self.values["action.models.bindings"])
        if declared_bindings:
            bindings = _bindings(_get(action, "models.bindings"))
            bindings.update(declared_bindings)
            result["action.models.bindings"] = list(bindings.values())
        policies = _object(action.get("retrieval"), "action.retrieval")
        for consumer, fields in self.retrieval.items():
            policy = policies.get(consumer)
            assert isinstance(fields, dict)
            if not isinstance(policy, dict):
                raise ConfigError("Preset retrieval consumer is unavailable", key=consumer)
            for path, value in fields.items():
                operation = path.partition(".")[0]
                if operation in {"select", "rerank"}:
                    operations = policy.get("operations", [])
                    if not isinstance(operations, list) or operation not in operations:
                        raise ConfigError(
                            "Preset operation is no longer available", key=consumer
                        )
                _set(policy, path, value)
        if self.retrieval:
            result["action.retrieval"] = policies
        return result

    def changes(self, environment: ConfigEnvironment) -> tuple[PresetChange, ...]:
        """Compare only the declared tasks, bindings and fields, without writing."""
        sections = {
            key: to_json_object(environment.section_tree(key))
            for key in ("llm", "action", "loop", "reflection", "session", "context")
        }
        result: list[PresetChange] = []
        tasks = _object(sections["llm"].get("tasks"), "llm.tasks")
        for profile, task in _object(self.values["llm.tasks"], "llm.tasks").items():
            result.extend(_changes(("llm", "tasks", profile), tasks.get(profile), task))
        bindings = _bindings(_get(sections["action"], "models.bindings"))
        for consumer, binding in _bindings(self.values["action.models.bindings"]).items():
            result.extend(_changes(("action", "models", "bindings", consumer), bindings.get(consumer), binding))
        for path, value in self.values.items():
            if path not in _GROUPS:
                section, _, tail = path.partition(".")
                result.extend(_changes(tuple(path.split(".")), _get(sections[section], tail), value))
        policies = _object(sections["action"].get("retrieval"), "action.retrieval")
        for consumer, fields in self.retrieval.items():
            assert isinstance(fields, dict)
            policy = _object(policies.get(consumer), consumer)
            for path, value in fields.items():
                result.extend(_changes(("action", "retrieval", consumer, *path.split(".")), _get(policy, path), value))
        return tuple(result)

    def matches(self, environment: ConfigEnvironment) -> bool:
        return not self.changes(environment)

    def to_json(self) -> JsonObject:
        return {
            "values": self.values,
            "retrieval": self.retrieval,
            "include_budgets": self.include_budgets,
        }

    @classmethod
    def from_json(cls, value: JsonValue) -> PresetDefinition:
        if not isinstance(value, dict) or set(value) != {
            "values",
            "retrieval",
            "include_budgets",
        }:
            raise ConfigError("Preset definition is invalid", key="preset.definition")
        values, retrieval, budgets = (
            value["values"],
            value["retrieval"],
            value["include_budgets"],
        )
        if (
            not isinstance(values, dict)
            or not isinstance(retrieval, dict)
            or type(budgets) is not bool
        ):
            raise ConfigError("Preset definition is invalid", key="preset.definition")
        return cls(values, retrieval, budgets)


@dataclass(frozen=True)
class ConfigPreset:
    id: str
    name: str
    description: str
    definition: PresetDefinition
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"[a-zA-Z0-9_-]{1,96}", self.id) is None:
            raise ConfigError("Preset identity is invalid", key="preset.id")
        if (
            not self.name.strip()
            or len(self.name) > 200
            or len(self.description) > 2000
        ):
            raise ConfigError(
                "Preset name or description is invalid", key="preset.name"
            )

    def to_json(self) -> JsonObject:
        return {
            "schema_version": 2,
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "included_scopes": ["tasks", "routing", "retrieval"]
            + (["budgets"] if self.definition.include_budgets else []),
            "definition": self.definition.to_json(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class ConfigPresetStore:
    """Records outside the TOML source graph, owned by configuration."""

    def __init__(self, root: Path) -> None:
        self._root = root / "configs" / "presets"

    def _path(self, identity: str) -> Path:
        if re.fullmatch(r"[a-zA-Z0-9_-]{1,96}", identity) is None:
            raise ConfigError("Preset identity is invalid", key="preset.id")
        return self._root / f"{identity}.json"

    def get(self, identity: str) -> ConfigPreset:
        path = self._path(identity)
        if not path.is_file():
            raise ConfigError("Preset was not found", key="preset.not_found")
        try:
            value = to_json_object(json.loads(path.read_text(encoding="utf-8")))
            fields = [
                value.get(key)
                for key in ("id", "name", "description", "created_at", "updated_at")
            ]
            if (
                value.get("schema_version") != 2
                or any(not isinstance(item, str) for item in fields)
                or value.get("id") != identity
            ):
                raise ConfigError("Preset record is invalid", key="preset")
            record_id, name, description, created_at, updated_at = fields
            assert (
                isinstance(record_id, str)
                and isinstance(name, str)
                and isinstance(description, str)
            )
            assert isinstance(created_at, str) and isinstance(updated_at, str)
            return ConfigPreset(
                record_id,
                name,
                description,
                PresetDefinition.from_json(value.get("definition")),
                created_at,
                updated_at,
            )
        except (OSError, ValueError, TypeError) as exc:
            raise ConfigError("Preset could not be read", key="preset") from exc

    def list(self) -> tuple[ConfigPreset, ...]:
        return tuple(self.get(path.stem) for path in sorted(self._root.glob("*.json")))

    def save(
        self,
        *,
        name: str,
        description: str,
        definition: PresetDefinition,
        previous: ConfigPreset | None = None,
    ) -> ConfigPreset:
        now = datetime.now(timezone.utc).isoformat()
        record = ConfigPreset(
            previous.id if previous else uuid4().hex,
            name,
            description,
            definition,
            previous.created_at if previous else now,
            now,
        )
        atomic_write_text(
            self._path(record.id),
            json.dumps(record.to_json(), ensure_ascii=False, indent=2),
        )
        return record

    def delete(self, identity: str) -> None:
        self.get(identity)
        self._path(identity).unlink()
