"""LLM configuration domain types."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from tinysoul.infra.config import ConfigError

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

    def provider(self, provider_id: str) -> ProviderSpec:
        for provider in self.providers:
            if provider.id == provider_id:
                return provider
        raise ConfigError(
            "Unknown provider",
            key="llm.providers",
            value=provider_id,
        )

