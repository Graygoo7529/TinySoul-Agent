"""Adapter-owned protocol and option rules."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from tinysoul.infra.config import ConfigError, reject_unknown_keys
from tinysoul.infra.json import JsonObject

from .adapter_types import AdapterKind
from .config_types import ProviderApiStyle
from .errors import LLMContractError


@dataclass(frozen=True)
class AdapterProtocolSpec:
    """One protocol branch exposed by an adapter."""

    id: str
    option_keys: frozenset[str]

    def to_json(self) -> JsonObject:
        return {"id": self.id, "option_keys": list(sorted(self.option_keys))}


@dataclass(frozen=True)
class AdapterSpec:
    """Machine-readable rules for one provider adapter."""

    kind: AdapterKind
    api_style: ProviderApiStyle | None
    common_option_keys: frozenset[str]
    protocols: tuple[AdapterProtocolSpec, ...] = ()

    def __post_init__(self) -> None:
        if len({protocol.id for protocol in self.protocols}) != len(self.protocols):
            raise LLMContractError(f"Duplicate adapter protocol: {self.kind.value}")
        if "protocol" in self.common_option_keys:
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
        allowed = set(self.common_option_keys)
        if protocol is not None:
            allowed.update(protocol.option_keys)
        if self.protocols:
            allowed.add("protocol")
        reject_unknown_keys(options, allowed, key=key)
        return protocol.id if protocol is not None else None

    def to_json(self) -> JsonObject:
        result: JsonObject = {
            "id": self.kind.value,
            "api_style": self.api_style.value if self.api_style is not None else None,
            "common_option_keys": list(sorted(self.common_option_keys)),
            "protocols": [protocol.to_json() for protocol in self.protocols],
        }
        return result


_ADAPTER_SPECS: tuple[AdapterSpec, ...] = (
    AdapterSpec(
        kind=AdapterKind.GENERIC,
        api_style=None,
        common_option_keys=frozenset(),
    ),
    AdapterSpec(
        kind=AdapterKind.OPENAI,
        api_style=ProviderApiStyle.OPENAI_RESPONSES,
        common_option_keys=frozenset(
            {
                "reasoning_effort",
                "reasoning_summary",
                "reasoning_keep",
                "verbosity",
                "prompt_cache_retention",
                "service_tier",
                "store",
                "top_p",
            }
        ),
    ),
    AdapterSpec(
        kind=AdapterKind.KIMI,
        api_style=ProviderApiStyle.OPENAI_CHAT,
        common_option_keys=frozenset({"reasoning_keep", "top_p"}),
        protocols=(
            AdapterProtocolSpec("k2", frozenset({"thinking"})),
            AdapterProtocolSpec("k3", frozenset({"reasoning_effort"})),
        ),
    ),
    AdapterSpec(
        kind=AdapterKind.DEEPSEEK,
        api_style=ProviderApiStyle.OPENAI_CHAT,
        common_option_keys=frozenset({"thinking", "reasoning_effort", "reasoning_keep"}),
    ),
    AdapterSpec(
        kind=AdapterKind.GLM,
        api_style=ProviderApiStyle.OPENAI_CHAT,
        common_option_keys=frozenset(
            {
                "thinking",
                "reasoning_effort",
                "reasoning_keep",
                "do_sample",
                "top_p",
                "request_id",
                "user_id",
            }
        ),
    ),
    AdapterSpec(
        kind=AdapterKind.MINIMAX,
        api_style=ProviderApiStyle.OPENAI_CHAT,
        common_option_keys=frozenset(
            {"thinking", "reasoning_split", "reasoning_keep", "top_p"}
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
