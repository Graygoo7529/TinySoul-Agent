"""Provider adapter factory."""

from __future__ import annotations

from collections.abc import Mapping

from tinysoul.llm.adapter_types import AdapterKind
from tinysoul.llm.config import ProviderSpec

from .base import ProviderAdapter, ProviderError, ProviderErrorKind
from .deepseek import DeepSeekProviderAdapter
from .glm import GlmProviderAdapter
from .kimi import KimiProviderAdapter
from .minimax import MiniMaxProviderAdapter
from .open_ai import OpenAIProviderAdapter
from .openai_sdk import OpenAICompatibleChatAdapter
from .registry import ProviderRegistry


def build_provider_registry(
    providers: tuple[ProviderSpec, ...],
    *,
    env: Mapping[str, str],
) -> ProviderRegistry:
    adapters: list[ProviderAdapter] = []
    for provider in providers:
        if not provider.enabled:
            continue
        api_key = provider.resolve_api_key(env)
        for adapter_kind in provider.adapters:
            adapters.append(
                _build_provider_adapter(
                    provider,
                    adapter_kind=adapter_kind,
                    api_key=api_key,
                )
            )
    return ProviderRegistry(adapters)


def _build_provider_adapter(
    provider: ProviderSpec,
    *,
    adapter_kind: AdapterKind,
    api_key: str,
) -> ProviderAdapter:
    if adapter_kind is AdapterKind.OPENAI:
        return OpenAIProviderAdapter(provider=provider, api_key=api_key)
    if adapter_kind is AdapterKind.KIMI:
        return KimiProviderAdapter(provider=provider, api_key=api_key)
    if adapter_kind is AdapterKind.DEEPSEEK:
        return DeepSeekProviderAdapter(provider=provider, api_key=api_key)
    if adapter_kind is AdapterKind.GLM:
        return GlmProviderAdapter(provider=provider, api_key=api_key)
    if adapter_kind is AdapterKind.MINIMAX:
        return MiniMaxProviderAdapter(provider=provider, api_key=api_key)
    if adapter_kind is AdapterKind.OPENAI_COMPATIBLE_CHAT:
        return OpenAICompatibleChatAdapter(
            provider=provider,
            adapter_kind=adapter_kind,
            api_key=api_key,
        )
    raise ProviderError(
        f"Unsupported provider adapter: {adapter_kind.value}",
        kind=ProviderErrorKind.CONFIG,
    )
