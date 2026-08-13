"""Shared helpers for parsing LLM configuration."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import TypeVar, cast

from tinysoul.infra.config import ConfigError, reject_unknown_keys

from .errors import LLMContractError
from .models import AdapterOptions, ModelCapability, RequestOverrides

E = TypeVar("E", bound=StrEnum)


def required_table(
    table: Mapping[str, object],
    name: str,
    *,
    key: str,
) -> Mapping[str, object]:
    value = table.get(name)
    if value is None:
        raise ConfigError("Missing configuration table", key=f"{key}.{name}")
    return as_table(value, key=f"{key}.{name}")


def as_table(value: object, *, key: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ConfigError(
            "Configuration value must be a table",
            key=key,
            value=value,
            expected="table",
        )
    return cast(Mapping[str, object], value)


def required_str(table: Mapping[str, object], name: str, *, key: str) -> str:
    value = table.get(name)
    if not isinstance(value, str) or not value:
        raise ConfigError(
            "Configuration value must be a non-empty string",
            key=f"{key}.{name}",
            value=value,
            expected="str",
        )
    return value


def required_bool(table: Mapping[str, object], name: str, *, key: str) -> bool:
    value = table.get(name)
    if not isinstance(value, bool):
        raise ConfigError(
            "Configuration value must be a boolean",
            key=f"{key}.{name}",
            value=value,
            expected="bool",
        )
    return value


def required_int(table: Mapping[str, object], name: str, *, key: str) -> int:
    value = table.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            "Configuration value must be an integer",
            key=f"{key}.{name}",
            value=value,
            expected="int",
        )
    return value


def optional_str(
    table: Mapping[str, object],
    name: str,
    *,
    default: str,
    key: str,
) -> str:
    value = table.get(name, default)
    if not isinstance(value, str) or not value:
        raise ConfigError(
            "Configuration value must be a non-empty string",
            key=f"{key}.{name}",
            value=value,
            expected="str",
        )
    return value


def required_str_list(
    table: Mapping[str, object],
    name: str,
    *,
    key: str,
    non_empty: bool = False,
) -> list[str]:
    value = table.get(name)
    if not isinstance(value, list):
        raise ConfigError(
            "Configuration value must be a list of strings",
            key=f"{key}.{name}",
            value=value,
            expected="list[str]",
        )
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ConfigError(
                "Configuration value must be a list of non-empty strings",
                key=f"{key}.{name}",
                value=value,
                expected="list[str]",
            )
        result.append(item)
    if non_empty and not result:
        raise ConfigError(
            "Configuration value must contain at least one item",
            key=f"{key}.{name}",
            value=value,
            expected="non-empty list[str]",
        )
    return result


def optional_adapter_options(
    table: Mapping[str, object],
    *,
    key: str,
) -> AdapterOptions:
    value = table.get("adapter_options")
    if value is None:
        return AdapterOptions()
    if not isinstance(value, Mapping):
        raise ConfigError(
            "Configuration value must be a table",
            key=f"{key}.adapter_options",
            value=value,
            expected="table",
        )
    options_table = cast(Mapping[str, object], value)
    options = AdapterOptions(options_table)
    try:
        options.reasoning_keep()
    except LLMContractError as exc:
        raise ConfigError(
            str(exc),
            key=f"{key}.adapter_options.reasoning_keep",
            value=options_table.get("reasoning_keep"),
            expected="none | content | encrypted",
        ) from exc
    return options


def optional_request_overrides(
    table: Mapping[str, object],
    *,
    key: str,
) -> RequestOverrides:
    value = table.get("request_overrides")
    if value is None:
        return RequestOverrides()
    overrides_table = as_table(value, key=f"{key}.request_overrides")
    reject_unknown_keys(
        overrides_table,
        {"temperature", "max_output_tokens"},
        key=f"{key}.request_overrides",
    )
    try:
        return RequestOverrides(
            temperature=optional_float_or_none(
                overrides_table,
                "temperature",
                default=None,
                key=f"{key}.request_overrides",
            ),
            max_output_tokens=optional_int_or_none(
                overrides_table,
                "max_output_tokens",
                default=None,
                key=f"{key}.request_overrides",
            ),
        )
    except LLMContractError as exc:
        raise ConfigError(str(exc), key=f"{key}.request_overrides") from exc


def optional_capability_set(
    table: Mapping[str, object],
    name: str,
    *,
    key: str,
) -> frozenset[ModelCapability]:
    value = table.get(name)
    if value is None:
        return frozenset()
    capabilities = required_str_list(table, name, key=key)
    return frozenset(
        enum_value(ModelCapability, capability, key=f"{key}.{name}")
        for capability in capabilities
    )


def required_capability_set(
    table: Mapping[str, object],
    name: str,
    *,
    key: str,
) -> frozenset[ModelCapability]:
    capabilities = required_str_list(table, name, key=key, non_empty=True)
    return frozenset(
        enum_value(ModelCapability, capability, key=f"{key}.{name}")
        for capability in capabilities
    )


def enum_value(enum_type: type[E], value: str, *, key: str) -> E:
    try:
        return enum_type(value)
    except ValueError as exc:
        expected = ", ".join(item.value for item in enum_type)
        raise ConfigError(
            "Configuration value is not supported",
            key=key,
            value=value,
            expected=expected,
        ) from exc


def optional_int(
    table: Mapping[str, object],
    name: str,
    *,
    default: int,
    key: str,
) -> int:
    value = table.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            "Configuration value must be an integer",
            key=f"{key}.{name}",
            value=value,
            expected="int",
        )
    return value


def optional_int_or_none(
    table: Mapping[str, object],
    name: str,
    *,
    default: int | None,
    key: str,
) -> int | None:
    value = table.get(name, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            "Configuration value must be an integer or null",
            key=f"{key}.{name}",
            value=value,
            expected="int | null",
        )
    return value


def optional_float(
    table: Mapping[str, object],
    name: str,
    *,
    default: float,
    key: str,
) -> float:
    value = table.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(
            "Configuration value must be a number",
            key=f"{key}.{name}",
            value=value,
            expected="float",
        )
    return float(value)


def optional_float_or_none(
    table: Mapping[str, object],
    name: str,
    *,
    default: float | None,
    key: str,
) -> float | None:
    value = table.get(name, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(
            "Configuration value must be a number or null",
            key=f"{key}.{name}",
            value=value,
            expected="float | null",
        )
    return float(value)
