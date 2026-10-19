"""Explicit API-mode client and model adapter assembly."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from openai import AsyncOpenAI

from tinysoul.llm.config.types import ProviderSpec
from tinysoul.llm.execution.registry import ModelRegistry
from tinysoul.llm.protocol.adapter_types import AdapterKind, ApiMode

from .base import ProviderAdapter
from .catalog import adapter_spec
from .models.deepseek import DeepSeekAdapter
from .models.glm import GlmAdapter
from .models.gpt import GptAdapter
from .models.kimi import KimiAdapter
from .models.minimax import MiniMaxAdapter
from .openai.chat import OpenAIChatAdapter
from .openai.clients import OpenAIChatCompletionsClient, OpenAIResponsesClient
from .openai.responses import OpenAIResponsesAdapter
from .registry import ProviderRegistry

_CHAT_FACTORIES = {
    AdapterKind.OPENAI_CHAT: OpenAIChatAdapter,
    AdapterKind.KIMI: KimiAdapter,
    AdapterKind.DEEPSEEK: DeepSeekAdapter,
    AdapterKind.GLM: GlmAdapter,
    AdapterKind.MINIMAX: MiniMaxAdapter,
}
_RESPONSE_FACTORIES = {
    AdapterKind.OPENAI_RESPONSES: OpenAIResponsesAdapter,
    AdapterKind.GPT: GptAdapter,
}


def runtime_adapter_kinds() -> frozenset[AdapterKind]:
    return frozenset((*_CHAT_FACTORIES, *_RESPONSE_FACTORIES))


async def build_provider_registry(
    providers: tuple[ProviderSpec, ...],
    *,
    models: ModelRegistry,
    env: Mapping[str, str],
) -> ProviderRegistry:
    registry = ProviderRegistry()
    referenced = {
        (binding.provider_id, model.adapter)
        for model in (models.get(id) for id in models.ids())
        for binding in model.providers
    }
    try:
        for provider in providers:
            if not provider.enabled:
                continue
            kinds = tuple(
                kind
                for kind in runtime_adapter_kinds()
                if (provider.id, kind) in referenced
            )
            clients: dict[ApiMode, AsyncOpenAI] = {}
            for kind in sorted(kinds, key=lambda item: item.value):
                mode = adapter_spec(kind).api_mode
                if mode not in clients:
                    client = AsyncOpenAI(
                        api_key=provider.resolve_api_key(env),
                        base_url=provider.endpoint(mode).base_url,
                        default_headers=provider.resolved_headers(mode, env),
                        max_retries=0,
                    )
                    registry.own_client(
                        f"llm.client.{provider.id}.{mode.value}", client
                    )
                    clients[mode] = client
                client = clients[mode]
                adapter: ProviderAdapter
                if kind in _CHAT_FACTORIES:
                    adapter = _CHAT_FACTORIES[kind](
                        provider=provider,
                        completions=cast(
                            OpenAIChatCompletionsClient, client.chat.completions
                        ),
                    )
                else:
                    adapter = _RESPONSE_FACTORIES[kind](
                        provider=provider,
                        responses=cast(OpenAIResponsesClient, client.responses),
                    )
                registry.register(adapter)
        return registry
    except BaseException:
        await registry.close()
        raise
