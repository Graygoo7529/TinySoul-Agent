"""Action module project settings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from tinysoul.infra.config import ConfigError, reject_unknown_keys

from .core.catalog import ActionCatalog
from .core.specs import ActionBackendKind


@dataclass(frozen=True)
class LLMActionRoute:
    """One explicit LLM-backed Action to task-profile binding."""

    action_id: str
    task_profile: str

    def __post_init__(self) -> None:
        _require_text(self.action_id, key="action.llm_action.overrides.action_id")
        _require_profile_id(
            self.task_profile,
            key="action.llm_action.overrides.task_profile",
        )


@dataclass(frozen=True)
class LLMActionSettings:
    """Runtime defaults and task-profile routing for LLM-backed Actions."""

    timeout_seconds: float = 600.0
    default_task_profile: str = "llm_action"
    overrides: tuple[LLMActionRoute, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or self.timeout_seconds <= 0
        ):
            raise ConfigError(
                "Action LLM timeout must be positive",
                key="action.llm_action.timeout_seconds",
                value=self.timeout_seconds,
                expected="positive number",
            )
        _require_profile_id(
            self.default_task_profile,
            key="action.llm_action.default_task_profile",
        )
        overrides = tuple(self.overrides)
        action_ids = tuple(item.action_id for item in overrides)
        if len(action_ids) != len(set(action_ids)):
            raise ConfigError(
                "Action LLM overrides must use unique Action IDs",
                key="action.llm_action.overrides",
                expected="unique action_id values",
            )
        object.__setattr__(self, "timeout_seconds", float(self.timeout_seconds))
        object.__setattr__(self, "overrides", overrides)


@dataclass(frozen=True)
class LLMActionProfileResolver:
    """Resolve one LLM-backed Action to its configured task profile."""

    settings: LLMActionSettings = field(default_factory=LLMActionSettings)

    def profile_for(self, action_id: str) -> str:
        for route in self.settings.overrides:
            if route.action_id == action_id:
                return route.task_profile
        return self.settings.default_task_profile


@dataclass(frozen=True)
class ActionSettings:
    """Project-owned Action runtime and routing settings."""

    llm_action: LLMActionSettings = field(default_factory=LLMActionSettings)


def parse_action_settings(tree: Mapping[str, object]) -> ActionSettings:
    """Parse Action settings from a dynamic configuration tree."""

    reject_unknown_keys(tree, {"llm_action"}, key="action")
    value = tree.get("llm_action", {})
    if not isinstance(value, Mapping):
        raise ConfigError(
            "Action LLM settings must be a table",
            key="action.llm_action",
            value=value,
            expected="table",
        )
    llm_action = _string_mapping(
        cast(Mapping[object, object], value),
        key="action.llm_action",
    )
    reject_unknown_keys(
        llm_action,
        {"timeout_seconds", "default_task_profile", "overrides"},
        key="action.llm_action",
    )
    timeout = llm_action.get("timeout_seconds", LLMActionSettings.timeout_seconds)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise ConfigError(
            "Action LLM timeout must be a number",
            key="action.llm_action.timeout_seconds",
            value=timeout,
            expected="positive number",
        )
    default_profile = llm_action.get(
        "default_task_profile",
        LLMActionSettings.default_task_profile,
    )
    if not isinstance(default_profile, str):
        raise ConfigError(
            "Action LLM default task profile must be a string",
            key="action.llm_action.default_task_profile",
            value=default_profile,
            expected="task profile ID",
        )
    return ActionSettings(
        llm_action=LLMActionSettings(
            timeout_seconds=float(timeout),
            default_task_profile=default_profile,
            overrides=_parse_routes(llm_action.get("overrides", [])),
        )
    )


def validate_llm_action_routes(
    settings: LLMActionSettings,
    *,
    catalog: ActionCatalog,
    task_profiles: tuple[str, ...],
) -> None:
    """Validate Action routes against project Action and LLM profile identities."""

    profiles = frozenset(task_profiles)
    _require_known_profile(
        settings.default_task_profile,
        profiles=profiles,
        key="action.llm_action.default_task_profile",
    )
    for index, route in enumerate(settings.overrides):
        key = f"action.llm_action.overrides.{index}"
        if not catalog.has_action(route.action_id):
            raise ConfigError(
                "Action LLM override references an unknown project Action",
                key=f"{key}.action_id",
                value=route.action_id,
            )
        action = catalog.get_action(route.action_id)
        if action.backend.kind is not ActionBackendKind.LLM_ACTION:
            raise ConfigError(
                "Action LLM override requires an llm_action backend",
                key=f"{key}.action_id",
                value=route.action_id,
                expected=ActionBackendKind.LLM_ACTION.value,
            )
        _require_known_profile(
            route.task_profile,
            profiles=profiles,
            key=f"{key}.task_profile",
        )


def _parse_routes(value: object) -> tuple[LLMActionRoute, ...]:
    if not isinstance(value, list):
        raise ConfigError(
            "Action LLM overrides must be a list",
            key="action.llm_action.overrides",
            value=value,
            expected="list of tables",
        )
    routes: list[LLMActionRoute] = []
    for index, item in enumerate(value):
        key = f"action.llm_action.overrides.{index}"
        if not isinstance(item, Mapping):
            raise ConfigError(
                "Action LLM override must be a table",
                key=key,
                value=item,
                expected="table",
            )
        table = _string_mapping(cast(Mapping[object, object], item), key=key)
        reject_unknown_keys(table, {"action_id", "task_profile"}, key=key)
        routes.append(
            LLMActionRoute(
                action_id=_required_string(table, "action_id", key=key),
                task_profile=_required_string(table, "task_profile", key=key),
            )
        )
    return tuple(routes)


def _string_mapping(value: Mapping[object, object], *, key: str) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, item in value.items():
        if not isinstance(name, str):
            raise ConfigError(
                "Action configuration keys must be strings",
                key=key,
                value=name,
                expected="str",
            )
        result[name] = item
    return result


def _required_string(table: Mapping[str, object], name: str, *, key: str) -> str:
    value = table.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(
            "Action LLM route value must be a non-empty string",
            key=f"{key}.{name}",
            value=value,
            expected="non-empty str",
        )
    return value


def _require_text(value: str, *, key: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(
            "Action configuration value must be non-empty",
            key=key,
            value=value,
            expected="non-empty str",
        )


def _require_profile_id(value: str, *, key: str) -> None:
    _require_text(value, key=key)
    if "." in value or value != value.strip():
        raise ConfigError(
            "LLM task profile ID must not contain dots or outer whitespace",
            key=key,
            value=value,
            expected="identifier without '.'",
        )


def _require_known_profile(
    profile: str,
    *,
    profiles: frozenset[str],
    key: str,
) -> None:
    if profile not in profiles:
        raise ConfigError(
            "Action LLM route references an unknown task profile",
            key=key,
            value=profile,
        )
