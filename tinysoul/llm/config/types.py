"""LLM configuration domain types."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from tinysoul.infra.config import ConfigError

from ..errors import LLMContractError
from ..protocol.adapter_types import AdapterKind
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
class ProviderSpec:
    """Configured provider API endpoint."""

    id: str
    adapters: tuple[AdapterKind, ...]
    base_url: str
    api_key_envs: tuple[str, ...]
    enabled: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise LLMContractError("ProviderSpec.id must be non-empty")
        try:
            adapters = tuple(self.adapters)
        except TypeError as exc:
            raise LLMContractError(
                "ProviderSpec.adapters must be an iterable of AdapterKind values"
            ) from exc
        if not adapters:
            raise LLMContractError("ProviderSpec.adapters must be non-empty")
        if any(not isinstance(adapter, AdapterKind) for adapter in adapters):
            raise LLMContractError(
                "ProviderSpec.adapters must contain AdapterKind values"
            )
        if len(set(adapters)) != len(adapters):
            raise LLMContractError("ProviderSpec.adapters must be unique")
        object.__setattr__(self, "adapters", adapters)
        if not isinstance(self.enabled, bool):
            raise LLMContractError("ProviderSpec.enabled must be a boolean")
        if not isinstance(self.base_url, str) or not self.base_url:
            raise LLMContractError("ProviderSpec.base_url must be non-empty")
        try:
            api_key_envs = tuple(self.api_key_envs)
        except TypeError as exc:
            raise LLMContractError(
                "ProviderSpec.api_key_envs must be an iterable of strings"
            ) from exc
        if not api_key_envs:
            raise LLMContractError("ProviderSpec.api_key_envs must be non-empty")
        for name in api_key_envs:
            if not isinstance(name, str) or not name:
                raise LLMContractError(
                    "ProviderSpec.api_key_envs must contain non-empty strings"
                )
        object.__setattr__(self, "api_key_envs", api_key_envs)

    def configured_api_key(self, values: Mapping[str, str]) -> str | None:
        """Return the first configured key without retaining its source name."""

        for name in self.api_key_envs:
            value = values.get(name)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def credential_status(
        self,
        values: Mapping[str, str],
    ) -> ProviderCredentialStatus:
        """Project credential readiness without exposing credential values."""

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
            f"Provider '{self.id}' cannot be enabled until one of its credentials "
            f"is configured: {names}",
            key=f"llm.providers.{self.id}.api_key_envs",
            expected="at least one non-empty runtime environment variable",
        )


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
