"""LLM configuration domain types."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from tinysoul.infra.config import ConfigError

from .errors import LLMContractError
from .adapter_types import AdapterKind
from .model_chain import TaskSpecTable
from .models import ModelRegistry


class ProviderApiStyle(StrEnum):
    """Supported provider API styles."""

    OPENAI_CHAT = "openai_chat"
    OPENAI_RESPONSES = "openai_responses"


@dataclass(frozen=True)
class ProviderSpec:
    """Configured provider API endpoint."""

    id: str
    api_style: ProviderApiStyle
    base_url: str
    api_key_envs: tuple[str, ...]
    adapter: AdapterKind = AdapterKind.GENERIC
    enabled: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise LLMContractError("ProviderSpec.id must be non-empty")
        if not isinstance(self.api_style, ProviderApiStyle):
            raise LLMContractError("ProviderSpec.api_style must be a ProviderApiStyle")
        if not isinstance(self.adapter, AdapterKind):
            raise LLMContractError("ProviderSpec.adapter must be an AdapterKind")
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
        expected_style = {
            AdapterKind.OPENAI: ProviderApiStyle.OPENAI_RESPONSES,
            AdapterKind.KIMI: ProviderApiStyle.OPENAI_CHAT,
            AdapterKind.DEEPSEEK: ProviderApiStyle.OPENAI_CHAT,
            AdapterKind.GLM: ProviderApiStyle.OPENAI_CHAT,
            AdapterKind.MINIMAX: ProviderApiStyle.OPENAI_CHAT,
        }.get(self.adapter)
        if expected_style is not None and self.api_style is not expected_style:
            raise LLMContractError(
                f"Provider adapter '{self.adapter.value}' requires "
                f"API style '{expected_style.value}'"
            )

    def resolve_api_key(self, values: Mapping[str, str]) -> str:
        for name in self.api_key_envs:
            value = values.get(name)
            if value:
                return value
        names = ", ".join(self.api_key_envs)
        raise ConfigError(
            "Provider API key is not configured",
            key=f"llm.providers.{self.id}.api_key_envs",
            value=names,
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
