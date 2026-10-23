"""Explicit API-mode client and model adapter assembly."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from anthropic import DEFAULT_CONNECTION_LIMITS as ANTHROPIC_LIMITS
from anthropic import AsyncAnthropic
from anthropic import DefaultAsyncHttpxClient as AnthropicHttpClient
from openai import DEFAULT_CONNECTION_LIMITS as OPENAI_LIMITS
from openai import AsyncOpenAI
from openai import DefaultAsyncHttpxClient as OpenAIHttpClient

from tinysoul.infra.http import httpx2_mounts
from tinysoul.infra.network import ResolvedNetwork
from tinysoul.llm.config.types import ProviderSpec
from tinysoul.llm.execution.registry import ModelRegistry
from tinysoul.llm.protocol.adapter_types import AdapterKind, ApiMode

from .anthropic.messages import AnthropicMessagesAdapter, MessagesClient
from .base import ProviderAdapter
from .catalog import adapter_spec
from .google.client import GoogleClient
from .google.generate_content import GoogleGenerateContentAdapter
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
    return frozenset(
        (
            *_CHAT_FACTORIES,
            *_RESPONSE_FACTORIES,
            AdapterKind.ANTHROPIC_MESSAGES,
            AdapterKind.GOOGLE_GENERATE_CONTENT,
        )
    )


async def build_provider_registry(
    providers: tuple[ProviderSpec, ...],
    *,
    models: ModelRegistry,
    env: Mapping[str, str],
    network: ResolvedNetwork = ResolvedNetwork(),
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
                connection = provider.resolved_network(mode, network)
                if kind is AdapterKind.ANTHROPIC_MESSAGES:
                    anthropic_client = AsyncAnthropic(
                        http_client=AnthropicHttpClient(
                            trust_env=False,
                            mounts=httpx2_mounts(connection, limits=ANTHROPIC_LIMITS),
                        ),
                        api_key=provider.resolve_api_key(env),
                        base_url=provider.endpoint(mode).base_url,
                        default_headers=provider.resolved_headers(mode, env),
                        max_retries=0,
                    )
                    registry.own_client(
                        f"llm.client.{provider.id}.{mode.value}", anthropic_client
                    )
                    registry.register(
                        AnthropicMessagesAdapter(
                            provider=provider,
                            messages=cast(MessagesClient, anthropic_client.messages),
                        )
                    )
                    continue
                if kind is AdapterKind.GOOGLE_GENERATE_CONTENT:
                    endpoint = provider.endpoint(mode)
                    google_client = GoogleClient(
                        network=connection,
                        api_key=provider.resolve_api_key(env),
                        base_url=endpoint.base_url,
                        api_version=endpoint.api_version,
                        headers=provider.resolved_headers(mode, env),
                    )
                    registry.own_client(
                        f"llm.client.{provider.id}.{mode.value}", google_client
                    )
                    registry.register(
                        GoogleGenerateContentAdapter(
                            provider=provider, client=google_client.sdk.aio
                        )
                    )
                    continue
                if mode not in clients:
                    client = AsyncOpenAI(
                        http_client=OpenAIHttpClient(
                            trust_env=False,
                            mounts=httpx2_mounts(connection, limits=OPENAI_LIMITS),
                        ),
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
