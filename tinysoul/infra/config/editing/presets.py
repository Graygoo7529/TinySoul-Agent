"""Named, source-independent snapshots of the configured model/routing scopes."""

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

_GROUPS = ("llm.models", "llm.tasks", "action.models.bindings")
_ROUTING = ("loop.cycle.phase1_task_profile", "loop.cycle.phase2_task_profile")
_BUDGETS = (
    "loop.user.max_cycles",
    "reflection.home.max_cycles",
    "reflection.memory.max_cycles",
    "session.background_max_chars",
    "context.budget_max_image_bytes",
    "context.compression_trigger_ratio",
    "context.compression_target_ratio",
    "context.trace_chunk_max_chars",
    "context.trace_branch_factor",
    "context.trace_min_hot_entries",
    "context.trace_inspect_max_chars",
)
_RETRIEVAL_BUDGETS = (
    "max_steps",
    "snapshot_max_chars",
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


@dataclass(frozen=True)
class PresetSnapshot:
    """Null represents the owner default, never a TOML null assignment."""

    values: JsonObject
    retrieval: JsonObject
    include_budgets: bool = True

    def __post_init__(self) -> None:
        expected = {*_GROUPS, *_ROUTING, *(_BUDGETS if self.include_budgets else ())}
        if set(self.values) != expected:
            raise ConfigError("Preset scopes are invalid", key="preset.snapshot")
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
                        "select.input_max_chars",
                        "rerank.input_max_chars",
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
    ) -> PresetSnapshot:
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
                        paths.append(f"{op}.input_max_chars")
            retrieval[consumer] = {path: _get(policy, path) for path in paths}
        return cls(values, retrieval, include_budgets)

    def replacements(self, environment: ConfigEnvironment) -> JsonObject:
        result = to_json_object(self.values)
        policies = to_json_object(environment.section_tree("action")).get(
            "retrieval", {}
        )
        if not isinstance(policies, dict) or set(policies) != set(self.retrieval):
            raise ConfigError(
                "Preset retrieval consumers differ from current capabilities",
                key="action.retrieval",
            )
        for consumer, fields in self.retrieval.items():
            policy = policies[consumer]
            assert isinstance(fields, dict)
            if not isinstance(policy, dict):
                raise ConfigError("Retrieval policy is invalid", key=consumer)
            for path, value in fields.items():
                operation = path.partition(".")[0]
                if operation in {"select", "rerank"}:
                    operations = policy.get("operations", [])
                    if not isinstance(operations, list) or operation not in operations:
                        raise ConfigError(
                            "Preset operation is no longer available", key=consumer
                        )
                _set(policy, path, value)
        result["action.retrieval"] = policies
        return result

    def to_json(self) -> JsonObject:
        return {
            "values": self.values,
            "retrieval": self.retrieval,
            "include_budgets": self.include_budgets,
        }

    @classmethod
    def from_json(cls, value: JsonValue) -> PresetSnapshot:
        if not isinstance(value, dict) or set(value) != {
            "values",
            "retrieval",
            "include_budgets",
        }:
            raise ConfigError("Preset snapshot is invalid", key="preset.snapshot")
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
            raise ConfigError("Preset snapshot is invalid", key="preset.snapshot")
        return cls(values, retrieval, budgets)


@dataclass(frozen=True)
class ConfigPreset:
    id: str
    name: str
    description: str
    snapshot: PresetSnapshot
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
            "schema_version": 1,
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "included_scopes": ["models", "tasks", "routing", "retrieval"]
            + (["budgets"] if self.snapshot.include_budgets else []),
            "snapshot": self.snapshot.to_json(),
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
                value.get("schema_version") != 1
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
                PresetSnapshot.from_json(value.get("snapshot")),
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
        snapshot: PresetSnapshot,
        previous: ConfigPreset | None = None,
    ) -> ConfigPreset:
        now = datetime.now(timezone.utc).isoformat()
        record = ConfigPreset(
            previous.id if previous else uuid4().hex,
            name,
            description,
            snapshot,
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
