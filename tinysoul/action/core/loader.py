"""Load action catalog definitions from TOML files."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Protocol, TypeVar, cast

from tinysoul.infra.config import ConfigError
from tinysoul.infra.config.toml_file import ConfigFileToml
from tinysoul.infra.json import JsonObject, to_json_object

from .catalog import ActionCatalog
from .schema import check_action_schema
from .specs import (
    ActionBackendKind,
    ActionBackendSpec,
    ActionDomainSpec,
    ActionEnvironmentEffect,
    ActionHookSpec,
    ActionParallelPolicy,
    ActionResultRuntimeSpec,
    ActionRuntimeSpec,
    ActionSemanticSpec,
    ActionSpec,
    ActionToolSpec,
)
from .result import ActionTraceMode

E = TypeVar("E", bound=StrEnum)


class ActionBackendOptionsValidator(Protocol):
    """Validate backend-specific options at catalog loading time."""

    def validate(self, backend: ActionBackendSpec, *, key: str) -> None:
        """Raise ConfigError if backend options are not valid for this backend."""
        ...


class ActionCatalogLoader:
    """Load domain packages from a catalog root directory."""

    def __init__(
        self,
        parser: "ActionTomlParser | None" = None,
        *,
        backend_options_validators: Mapping[str, ActionBackendOptionsValidator] | None = None,
    ) -> None:
        self._parser = parser or ActionTomlParser()
        self._backend_options_validators = dict(backend_options_validators or {})

    def load(self, root_path: Path) -> ActionCatalog:
        if not root_path.exists():
            raise ConfigError(
                "Action catalog root does not exist",
                key=str(root_path),
                expected="directory",
            )
        if not root_path.is_dir():
            raise ConfigError(
                "Action catalog root must be a directory",
                key=str(root_path),
                expected="directory",
            )
        domains: list[ActionDomainSpec] = []
        actions: list[ActionSpec] = []
        domain_dirs = sorted(
            (path for path in root_path.iterdir() if path.is_dir()),
            key=lambda path: path.name,
        )
        for domain_dir in domain_dirs:
            domain_path = domain_dir / "domain.toml"
            if not domain_path.exists():
                continue
            domain_data = ConfigFileToml(domain_path).data
            domain = self._parser.parse_domain(
                _as_table(domain_data, key=str(domain_path)),
                source=str(domain_path),
            )
            domains.append(domain)

            default_runtime = self._parser.parse_runtime(
                _optional_table(domain_data, "runtime", key=str(domain_path)),
                key=f"{domain_path}.runtime",
            )
            action_dir = domain_dir / "actions"
            if not action_dir.exists():
                continue
            for action_path in sorted(action_dir.glob("*.toml"), key=lambda path: path.name):
                action_data = ConfigFileToml(action_path).data
                action = self._parser.parse_action(
                    _as_table(action_data, key=str(action_path)),
                    source=str(action_path),
                    default_runtime=default_runtime,
                )
                self._validate_backend_options(
                    action.backend,
                    key=f"{action_path}.backend.options",
                )
                actions.append(action)
        return ActionCatalog(domains=domains, actions=actions)

    def _validate_backend_options(self, backend: ActionBackendSpec, *, key: str) -> None:
        validator = self._backend_options_validators.get(backend.handler)
        if validator is not None:
            validator.validate(backend, key=key)


class ActionTomlParser:
    """Parse TOML mappings into explicit action spec objects."""

    def parse_domain(
        self,
        table: Mapping[str, object],
        *,
        source: str,
    ) -> ActionDomainSpec:
        return ActionDomainSpec(
            name=_required_str(table, "name", key=source),
            description=_required_str(table, "description", key=source),
            selection_hint=_optional_str(table, "selection_hint", default="", key=source),
        )

    def parse_action(
        self,
        table: Mapping[str, object],
        *,
        source: str,
        default_runtime: ActionRuntimeSpec | None = None,
    ) -> ActionSpec:
        name = _required_str(table, "name", key=source)
        domain = _required_str(table, "domain", key=source)
        tool = self.parse_tool(
            _required_table(table, "tool", key=source),
            action_name=name,
            key=f"{source}.tool",
        )
        semantic = self.parse_semantic(
            _optional_table(table, "semantic", key=source),
            key=f"{source}.semantic",
        )
        runtime = self.parse_runtime(
            _optional_table(table, "runtime", key=source),
            key=f"{source}.runtime",
            base=default_runtime,
        )
        backend = self.parse_backend(
            _required_table(table, "backend", key=source),
            key=f"{source}.backend",
        )
        return ActionSpec(
            name=name,
            domain=domain,
            tool=tool,
            semantic=semantic,
            runtime=runtime,
            backend=backend,
        )

    def parse_tool(
        self,
        table: Mapping[str, object],
        *,
        action_name: str,
        key: str,
    ) -> ActionToolSpec:
        schema = _required_table(table, "schema", key=key)
        schema_object = to_json_object(schema)
        check_action_schema(schema_object, key=f"{key}.schema")
        return ActionToolSpec(
            name=action_name,
            description=_required_str(table, "description", key=key),
            schema=schema_object,
        )

    def parse_semantic(
        self,
        table: Mapping[str, object],
        *,
        key: str,
    ) -> ActionSemanticSpec:
        effects = tuple(
            _enum_value(ActionEnvironmentEffect, value, key=f"{key}.effects")
            for value in _optional_str_list(table, "effects", key=key)
        )
        return ActionSemanticSpec(
            use_when=tuple(_optional_str_list(table, "use_when", key=key)),
            avoid_when=tuple(_optional_str_list(table, "avoid_when", key=key)),
            effects=effects,
            examples=tuple(_optional_str_list(table, "examples", key=key)),
        )

    def parse_runtime(
        self,
        table: Mapping[str, object],
        *,
        key: str,
        base: ActionRuntimeSpec | None = None,
    ) -> ActionRuntimeSpec:
        timeout_seconds = (
            base.timeout_seconds
            if base is not None and "timeout_seconds" not in table
            else _optional_float_or_none(table, "timeout_seconds", key=key)
        )
        parallel_default = (
            base.parallel_policy.value
            if base is not None
            else ActionParallelPolicy.ALLOWED.value
        )
        base_hooks = base.hooks if base is not None else ActionHookSpec()
        base_result = base.result if base is not None else ActionResultRuntimeSpec()
        hook_table = _optional_table(table, "hooks", key=key)
        result_table = _optional_table(table, "result", key=key)
        return ActionRuntimeSpec(
            timeout_seconds=timeout_seconds,
            parallel_policy=_enum_value(
                ActionParallelPolicy,
                _optional_str(
                    table,
                    "parallel_policy",
                    default=parallel_default,
                    key=key,
                ),
                key=f"{key}.parallel_policy",
            ),
            hooks=ActionHookSpec(
                normalize_hooks=(
                    *base_hooks.normalize_hooks,
                    *_optional_str_list(hook_table, "normalize", key=f"{key}.hooks"),
                ),
                execution_hooks=(
                    *base_hooks.execution_hooks,
                    *_optional_str_list(hook_table, "execute", key=f"{key}.hooks"),
                ),
            ),
            result=ActionResultRuntimeSpec(
                trace_mode=_enum_value(
                    ActionTraceMode,
                    _optional_str(
                        result_table,
                        "trace_mode",
                        default=base_result.trace_mode.value,
                        key=f"{key}.result",
                    ),
                    key=f"{key}.result.trace_mode",
                )
            ),
        )

    def parse_backend(
        self,
        table: Mapping[str, object],
        *,
        key: str,
    ) -> ActionBackendSpec:
        return ActionBackendSpec(
            kind=_enum_value(
                ActionBackendKind,
                _required_str(table, "kind", key=key),
                key=f"{key}.kind",
            ),
            handler=_required_str(table, "handler", key=key),
            options=_optional_json_object(table, "options", key=key),
        )


def _required_table(
    table: Mapping[str, object],
    name: str,
    *,
    key: str,
) -> Mapping[str, object]:
    value = table.get(name)
    if value is None:
        raise ConfigError("Missing action configuration table", key=f"{key}.{name}")
    return _as_table(value, key=f"{key}.{name}")


def _optional_table(
    table: Mapping[str, object],
    name: str,
    *,
    key: str,
) -> Mapping[str, object]:
    value = table.get(name)
    if value is None:
        return {}
    return _as_table(value, key=f"{key}.{name}")


def _as_table(value: object, *, key: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ConfigError(
            "Action configuration value must be a table",
            key=key,
            value=value,
            expected="table",
        )
    return cast(Mapping[str, object], value)


def _required_str(table: Mapping[str, object], name: str, *, key: str) -> str:
    value = table.get(name)
    if not isinstance(value, str) or not value:
        raise ConfigError(
            "Action configuration value must be a non-empty string",
            key=f"{key}.{name}",
            value=value,
            expected="str",
        )
    return value


def _optional_str(
    table: Mapping[str, object],
    name: str,
    *,
    default: str,
    key: str,
) -> str:
    value = table.get(name, default)
    if not isinstance(value, str):
        raise ConfigError(
            "Action configuration value must be a string",
            key=f"{key}.{name}",
            value=value,
            expected="str",
        )
    return value


def _enum_value(enum_type: type[E], value: str, *, key: str) -> E:
    try:
        return enum_type(value)
    except ValueError as exc:
        expected = ", ".join(item.value for item in enum_type)
        raise ConfigError(
            "Action configuration value must be one of the supported enum values",
            key=key,
            value=value,
            expected=expected,
        ) from exc


def _optional_str_list(
    table: Mapping[str, object],
    name: str,
    *,
    key: str,
) -> list[str]:
    value = table.get(name)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError(
            "Action configuration value must be a list of strings",
            key=f"{key}.{name}",
            value=value,
            expected="list[str]",
        )
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ConfigError(
                "Action configuration value must be a list of non-empty strings",
                key=f"{key}.{name}",
                value=value,
                expected="list[str]",
            )
        result.append(item)
    return result


def _optional_float_or_none(
    table: Mapping[str, object],
    name: str,
    *,
    key: str,
) -> float | None:
    value = table.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(
            "Action configuration value must be a number or null",
            key=f"{key}.{name}",
            value=value,
            expected="float | null",
        )
    return float(value)


def _optional_json_object(
    table: Mapping[str, object],
    name: str,
    *,
    key: str,
) -> JsonObject:
    value = table.get(name)
    if value is None:
        return {}
    try:
        return to_json_object(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(
            str(exc),
            key=f"{key}.{name}",
            value=value,
            expected="json object",
        ) from exc
