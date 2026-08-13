"""Adapter-owned protocol and option rules."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from tinysoul.infra.config import ConfigError, reject_unknown_keys
from tinysoul.infra.json import JsonObject

from .adapter_types import AdapterKind, ProviderApiStyle
from .errors import LLMContractError


@dataclass(frozen=True)
class AdapterOptionSpec:
    """Machine rule for one adapter-owned model option."""

    id: str
    value_kind: str
    choices: tuple[str, ...] = ()
    validator: str | None = None

    def to_json(self) -> JsonObject:
        result: JsonObject = {"id": self.id, "value_kind": self.value_kind}
        if self.choices:
            result["choices"] = list(self.choices)
        if self.validator is not None:
            result["validator"] = self.validator
        return result


@dataclass(frozen=True)
class AdapterProtocolSpec:
    """One protocol branch exposed by an adapter."""

    id: str
    option_specs: tuple[AdapterOptionSpec, ...]

    @property
    def option_keys(self) -> frozenset[str]:
        return frozenset(option.id for option in self.option_specs)

    def to_json(self) -> JsonObject:
        return {
            "id": self.id,
            "option_keys": list(sorted(self.option_keys)),
            "options": [option.to_json() for option in self.option_specs],
        }


@dataclass(frozen=True)
class AdapterSpec:
    """Machine-readable rules for one provider adapter."""

    kind: AdapterKind
    api_style: ProviderApiStyle | None
    common_options: tuple[AdapterOptionSpec, ...]
    protocols: tuple[AdapterProtocolSpec, ...] = ()

    def __post_init__(self) -> None:
        if len({protocol.id for protocol in self.protocols}) != len(self.protocols):
            raise LLMContractError(f"Duplicate adapter protocol: {self.kind.value}")
        if "protocol" in {option.id for option in self.common_options}:
            raise LLMContractError(
                "Adapter protocol is reserved and cannot be common option"
            )

    @property
    def requires_protocol(self) -> bool:
        return bool(self.protocols)

    def protocol(self, value: str | None, *, key: str) -> AdapterProtocolSpec | None:
        if not self.protocols:
            if value is not None:
                raise ConfigError(
                    "Adapter does not support protocol branches",
                    key=key,
                    value=value,
                )
            return None
        if value is None:
            raise ConfigError(
                "Adapter protocol is required",
                key=key,
                expected=" | ".join(protocol.id for protocol in self.protocols),
            )
        for protocol in self.protocols:
            if protocol.id == value:
                return protocol
        raise ConfigError(
            "Adapter protocol is not supported",
            key=key,
            value=value,
            expected=" | ".join(protocol.id for protocol in self.protocols),
        )

    def validate_option_keys(
        self,
        options: Mapping[str, object],
        *,
        key: str,
    ) -> str | None:
        protocol_value = options.get("protocol")
        if protocol_value is not None and not isinstance(protocol_value, str):
            raise ConfigError(
                "Adapter protocol must be a non-empty string",
                key=f"{key}.protocol",
                value=protocol_value,
                expected="str",
            )
        protocol = self.protocol(
            protocol_value,
            key=f"{key}.protocol",
        )
        allowed = {option.id for option in self.common_options}
        if protocol is not None:
            allowed.update(protocol.option_keys)
        if self.protocols:
            allowed.add("protocol")
        reject_unknown_keys(options, allowed, key=key)
        return protocol.id if protocol is not None else None

    def validate_api_style(self, api_style: ProviderApiStyle) -> None:
        if self.api_style is not None and api_style is not self.api_style:
            raise LLMContractError(
                f"Adapter '{self.kind.value}' requires API style '{self.api_style.value}'"
            )

    def validate_options(self, options: Mapping[str, object], *, key: str) -> None:
        protocol = self.validate_option_keys(options, key=key)
        specs = {option.id: option for option in self.common_options}
        branch = self.protocol(protocol, key=f"{key}.protocol")
        if branch is not None:
            specs.update({option.id: option for option in branch.option_specs})
        for option_key, value in options.items():
            if option_key == "protocol":
                continue
            _validate_option_value(specs[option_key], value, key=f"{key}.{option_key}")

    def to_json(self) -> JsonObject:
        result: JsonObject = {
            "id": self.kind.value,
            "api_style": self.api_style.value if self.api_style is not None else None,
            "common_option_keys": list(sorted(option.id for option in self.common_options)),
            "common_options": [option.to_json() for option in self.common_options],
            "protocols": [protocol.to_json() for protocol in self.protocols],
        }
        return result


_ADAPTER_SPECS: tuple[AdapterSpec, ...] = (
    AdapterSpec(
        kind=AdapterKind.GENERIC,
        api_style=None,
        common_options=(),
    ),
    AdapterSpec(
        kind=AdapterKind.OPENAI,
        api_style=ProviderApiStyle.OPENAI_RESPONSES,
        common_options=tuple(
            AdapterOptionSpec(key, "enum", ("none", "encrypted"))
            if key == "reasoning_keep" else
            AdapterOptionSpec(key, "enum", ("auto", "concise", "detailed"))
            if key == "reasoning_summary" else
            AdapterOptionSpec(key, "boolean") if key == "store" else
            AdapterOptionSpec(key, "number") if key == "top_p" else
            AdapterOptionSpec(key, "string")
            for key in (
                "reasoning_effort",
                "reasoning_summary",
                "reasoning_keep",
                "verbosity",
                "prompt_cache_retention",
                "service_tier",
                "store",
                "top_p",
            )
        ),
    ),
    AdapterSpec(
        kind=AdapterKind.KIMI,
        api_style=ProviderApiStyle.OPENAI_CHAT,
        common_options=(
            AdapterOptionSpec("reasoning_keep", "enum", ("none", "content"), "reasoning_keep"),
            AdapterOptionSpec("top_p", "number"),
        ),
        protocols=(
            AdapterProtocolSpec("k2", (AdapterOptionSpec("thinking", "string", ("enabled", "disabled")),)),
            AdapterProtocolSpec("k3", (AdapterOptionSpec("reasoning_effort", "enum", ("max",)),)),
        ),
    ),
    AdapterSpec(
        kind=AdapterKind.DEEPSEEK,
        api_style=ProviderApiStyle.OPENAI_CHAT,
        common_options=(
            AdapterOptionSpec("thinking", "object", validator="thinking_deepseek"),
            AdapterOptionSpec("reasoning_effort", "enum", ("high", "max")),
            AdapterOptionSpec("reasoning_keep", "enum", ("none", "content")),
        ),
    ),
    AdapterSpec(
        kind=AdapterKind.GLM,
        api_style=ProviderApiStyle.OPENAI_CHAT,
        common_options=tuple(
            AdapterOptionSpec(key, "boolean") if key in {"do_sample"} else
            AdapterOptionSpec(key, "number") if key == "top_p" else
            AdapterOptionSpec(key, "object", validator="thinking_glm") if key == "thinking" else
            AdapterOptionSpec(key, "enum", ("none", "content")) if key == "reasoning_keep" else
            AdapterOptionSpec(key, "string") if key == "reasoning_effort" else
            AdapterOptionSpec(key, "string")
            for key in (
                "thinking",
                "reasoning_effort",
                "reasoning_keep",
                "do_sample",
                "top_p",
                "request_id",
                "user_id",
            )
        ),
    ),
    AdapterSpec(
        kind=AdapterKind.MINIMAX,
        api_style=ProviderApiStyle.OPENAI_CHAT,
        common_options=(
            AdapterOptionSpec("thinking", "enum", ("enabled", "disabled", "adaptive")),
            AdapterOptionSpec("reasoning_split", "boolean"),
            AdapterOptionSpec("reasoning_keep", "enum", ("none", "content")),
            AdapterOptionSpec("top_p", "number"),
        ),
    ),
)

_ADAPTER_SPEC_BY_KIND = {spec.kind: spec for spec in _ADAPTER_SPECS}


def adapter_spec(kind: AdapterKind) -> AdapterSpec:
    """Return the static rules for an adapter kind."""

    return _ADAPTER_SPEC_BY_KIND[kind]


def adapter_specs_json() -> list[JsonObject]:
    """Return adapter rules for the configuration presentation endpoint."""

    return [spec.to_json() for spec in _ADAPTER_SPECS]


def _validate_option_value(spec: AdapterOptionSpec, value: object, *, key: str) -> None:
    if spec.validator == "thinking_deepseek":
        _validate_thinking_object(value, key=key, allowed_types={"enabled", "disabled"}, object_keys={"type"})
        return
    if spec.validator == "thinking_glm":
        _validate_thinking_object(value, key=key, allowed_types={"enabled", "disabled"}, object_keys={"type", "clear_thinking"})
        return
    if spec.choices and value not in spec.choices:
        raise ConfigError("Adapter option value is invalid", key=key, value=value, expected=" | ".join(spec.choices))
    if spec.value_kind == "string" and (not isinstance(value, str) or not value):
        raise ConfigError("Adapter option must be a non-empty string", key=key, value=value, expected="str")
    if spec.value_kind == "boolean" and not isinstance(value, bool):
        raise ConfigError("Adapter option must be a boolean", key=key, value=value, expected="bool")
    if spec.value_kind == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
        raise ConfigError("Adapter option must be a number", key=key, value=value, expected="float")


def _validate_thinking_object(
    value: object,
    *,
    key: str,
    allowed_types: set[str],
    object_keys: set[str],
) -> None:
    if isinstance(value, str):
        if value not in allowed_types:
            raise ConfigError("Adapter thinking type is invalid", key=key, value=value)
        return
    if not isinstance(value, Mapping):
        raise ConfigError("Adapter thinking option has an invalid type", key=key, value=value)
    object_value = {str(name): item for name, item in value.items()}
    raw_type = object_value.get("type")
    if raw_type not in allowed_types:
        raise ConfigError("Adapter thinking type is invalid", key=f"{key}.type", value=raw_type)
    for name, item in object_value.items():
        if name not in object_keys:
            raise ConfigError("Unknown adapter thinking option", key=f"{key}.{name}", value=item)
    if "clear_thinking" in object_value and not isinstance(object_value["clear_thinking"], bool):
        raise ConfigError("Adapter clear_thinking must be a boolean", key=f"{key}.clear_thinking", value=object_value["clear_thinking"])
