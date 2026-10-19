"""LLM configuration domain types."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from tinysoul.infra.config import ConfigError

from ..errors import LLMContractError
from ..adapter.catalog import adapter_spec
from ..protocol.adapter_types import AdapterKind, ApiMode
from ..execution.model_chain import TaskSpecTable
from ..execution.registry import ModelRegistry


class ProviderCredentialState(StrEnum):
    """Whether a configured provider credential can be resolved."""

    CONFIGURED = "configured"
    MISSING = "missing"


@dataclass(frozen=True)
class ProviderCredentialStatus:
    """Secret-free provider credential readiness for one Runtime Generation."""

    provider_id: str
    state: ProviderCredentialState
    api_key_envs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id:
            raise LLMContractError(
                "ProviderCredentialStatus.provider_id must be non-empty"
            )
        if not isinstance(self.state, ProviderCredentialState):
            raise LLMContractError(
                "ProviderCredentialStatus.state must be a ProviderCredentialState"
            )
        try:
            names = tuple(self.api_key_envs)
        except TypeError as exc:
            raise LLMContractError(
                "ProviderCredentialStatus.api_key_envs must be an iterable of strings"
            ) from exc
        if not names or any(not isinstance(name, str) or not name for name in names):
            raise LLMContractError(
                "ProviderCredentialStatus.api_key_envs must contain non-empty strings"
            )
        object.__setattr__(self, "api_key_envs", names)


@dataclass(frozen=True)
class ProviderEndpoint:
    """One provider endpoint for one API mode."""

    api_mode: ApiMode
    base_url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    header_refs: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.api_mode, ApiMode)
            or not isinstance(self.base_url, str)
            or not self.base_url
        ):
            raise LLMContractError("ProviderEndpoint requires an API mode and base URL")
        if any(
            not isinstance(name, str)
            or not name
            or not isinstance(value, str)
            or not value
            for name, value in (*self.headers.items(), *self.header_refs.items())
        ):
            raise LLMContractError(
                "Provider endpoint headers must be non-empty strings"
            )
        if set(self.headers) & set(self.header_refs):
            raise LLMContractError(
                "Provider endpoint header cannot be literal and referenced"
            )

    def resolved_headers(self, values: Mapping[str, str]) -> dict[str, str]:
        result = dict(self.headers)
        for header, env_name in self.header_refs.items():
            if values.get(env_name):
                result[header] = values[env_name]
        return result


@dataclass(frozen=True)
class ProviderSpec:
    """Configured provider credentials shared by API-mode endpoints."""

    id: str
    endpoints: tuple[ProviderEndpoint, ...]
    api_key_envs: tuple[str, ...]
    enabled: bool = True
    headers: Mapping[str, str] = field(default_factory=dict)
    header_refs: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise LLMContractError("ProviderSpec.id must be non-empty")
        endpoints = tuple(self.endpoints)
        if not endpoints or any(
            not isinstance(item, ProviderEndpoint) for item in endpoints
        ):
            raise LLMContractError(
                "ProviderSpec.endpoints must contain ProviderEndpoint values"
            )
        if len({item.api_mode for item in endpoints}) != len(endpoints):
            raise LLMContractError("ProviderSpec.endpoints must use unique API modes")
        object.__setattr__(self, "endpoints", endpoints)
        if not isinstance(self.enabled, bool):
            raise LLMContractError("ProviderSpec.enabled must be a boolean")
        if any(
            not isinstance(name, str)
            or not name
            or not isinstance(value, str)
            or not value
            for name, value in (*self.headers.items(), *self.header_refs.items())
        ):
            raise LLMContractError("Provider headers must be non-empty strings")
        if set(self.headers) & set(self.header_refs):
            raise LLMContractError("Provider header cannot be literal and referenced")
        api_key_envs = tuple(self.api_key_envs)
        if not api_key_envs or any(
            not isinstance(name, str) or not name for name in api_key_envs
        ):
            raise LLMContractError(
                "ProviderSpec.api_key_envs must contain non-empty strings"
            )
        object.__setattr__(self, "api_key_envs", api_key_envs)

    def endpoint(self, api_mode: ApiMode) -> ProviderEndpoint:
        for endpoint in self.endpoints:
            if endpoint.api_mode is api_mode:
                return endpoint
        raise ConfigError(
            f"Provider '{self.id}' does not expose '{api_mode.value}'",
            key=f"llm.providers.{self.id}.endpoints",
            value=api_mode.value,
        )

    def supports_adapter(self, adapter: AdapterKind) -> bool:
        return adapter_spec(adapter).api_mode in {
            endpoint.api_mode for endpoint in self.endpoints
        }

    def configured_api_key(self, values: Mapping[str, str]) -> str | None:
        for name in self.api_key_envs:
            value = values.get(name)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def credential_status(self, values: Mapping[str, str]) -> ProviderCredentialStatus:
        return ProviderCredentialStatus(
            provider_id=self.id,
            state=(
                ProviderCredentialState.CONFIGURED
                if self.configured_api_key(values) is not None
                else ProviderCredentialState.MISSING
            ),
            api_key_envs=self.api_key_envs,
        )

    def resolve_api_key(self, values: Mapping[str, str]) -> str:
        value = self.configured_api_key(values)
        if value is not None:
            return value
        names = ", ".join(self.api_key_envs)
        raise ConfigError(
            f"Provider '{self.id}' cannot be enabled until one of its credentials is configured: {names}",
            key=f"llm.providers.{self.id}.api_key_envs",
            expected="at least one non-empty runtime environment variable",
        )

    def resolved_headers(
        self, api_mode: ApiMode, values: Mapping[str, str]
    ) -> dict[str, str]:
        result = dict(self.headers)
        for header, env_name in self.header_refs.items():
            if values.get(env_name):
                result[header] = values[env_name]
        result.update(self.endpoint(api_mode).resolved_headers(values))
        return result


@dataclass(frozen=True)
class LLMConfig:
    """Parsed LLM configuration."""

    providers: tuple[ProviderSpec, ...]
    models: ModelRegistry
    tasks: TaskSpecTable

    def __post_init__(self) -> None:
        try:
            providers = tuple(self.providers)
        except TypeError as exc:
            raise LLMContractError(
                "LLMConfig.providers must be an iterable of ProviderSpec values"
            ) from exc
        for provider in providers:
            if not isinstance(provider, ProviderSpec):
                raise LLMContractError(
                    "LLMConfig.providers must contain ProviderSpec values"
                )
        object.__setattr__(self, "providers", providers)
        if not isinstance(self.models, ModelRegistry):
            raise LLMContractError("LLMConfig.models must be a ModelRegistry")
        if not isinstance(self.tasks, TaskSpecTable):
            raise LLMContractError("LLMConfig.tasks must be a TaskSpecTable")

    def provider(self, provider_id: str) -> ProviderSpec:
        for provider in self.providers:
            if provider.id == provider_id:
                return provider
        raise ConfigError(
            "Unknown provider",
            key="llm.providers",
            value=provider_id,
        )

    def validate_enabled_provider_credentials(
        self,
        values: Mapping[str, str],
    ) -> None:
        """Require every enabled provider to be locally ready for assembly."""

        for provider in self.providers:
            if provider.enabled:
                provider.resolve_api_key(values)

    def provider_credential_statuses(
        self,
        values: Mapping[str, str],
    ) -> tuple[ProviderCredentialStatus, ...]:
        """Return stable, secret-free credential readiness in configuration order."""

        return tuple(provider.credential_status(values) for provider in self.providers)
