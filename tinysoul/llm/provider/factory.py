"""Provider adapter factory."""

from __future__ import annotations

from collections.abc import Mapping

from tinysoul.llm.config import ProviderApiStyle, ProviderSpec

from .base import ProviderAdapter, ProviderError, ProviderErrorKind
from .deepseek import DeepSeekProviderAdapter
from .kimi import KimiProviderAdapter
from .open_ai import OpenAIProviderAdapter
from .openai_sdk import OpenAICompatibleChatAdapter, OpenAIResponsesAdapter
from .registry import ProviderRegistry


def build_provider_registry(
    providers: tuple[ProviderSpec, ...],
    *,
    env: Mapping[str, str],
) -> ProviderRegistry:
    adapters: list[ProviderAdapter] = []
    for provider in providers:
        api_key = provider.resolve_api_key(env)
        if provider.id == "openai":
            adapters.append(
                OpenAIProviderAdapter(
                    provider=provider,
                    api_key=api_key,
                )
            )
            continue
        if provider.id == "kimi":
            adapters.append(
                KimiProviderAdapter(
                    provider=provider,
                    api_key=api_key,
                )
            )
            continue
        if provider.id == "deepseek":
            adapters.append(
                DeepSeekProviderAdapter(
                    provider=provider,
                    api_key=api_key,
                )
            )
            continue
        if provider.api_style is ProviderApiStyle.OPENAI_RESPONSES:
            adapters.append(
                OpenAIResponsesAdapter(
                    provider=provider,
                    api_key=api_key,
                )
            )
            continue
        if provider.api_style is ProviderApiStyle.OPENAI_CHAT:
            adapters.append(
                OpenAICompatibleChatAdapter(
                    provider=provider,
                    api_key=api_key,
                )
            )
            continue
        raise ProviderError(
            f"Unsupported provider API style: {provider.api_style}",
            kind=ProviderErrorKind.CONFIG,
        )
    return ProviderRegistry(adapters)
