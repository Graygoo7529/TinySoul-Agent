from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from tinysoul.llm.adapter import ProviderRequest as ProviderRequestModel
from tinysoul.llm.adapter.replay import message_fingerprint
from tinysoul.llm.config.loader import (
    AdapterKind,
    ApiMode,
    ProviderEndpoint,
    ProviderSpec,
)
from tinysoul.llm.protocol.cache import PromptCache
from tinysoul.llm.protocol.messages import AssistantMessage, MessageStack
from tinysoul.llm.protocol.models import (
    AdapterOptions,
    ModelCapability,
    ModelProviderBinding,
    ModelSpec,
    RequestOverrides,
)
from tinysoul.llm.protocol.reasoning import NativeReplay, NativeReplayMode, Reasoning
from tinysoul.llm.protocol.responses import AnswerFormat
from tinysoul.llm.protocol.tools import ToolKind, ToolScope, ToolSpec, ToolUse


def ProviderRequest(
    *,
    model: ModelSpec,
    messages: MessageStack,
    answer_format: AnswerFormat,
    tool_use: ToolUse = ToolUse.DISABLED,
    tool_scope: ToolScope | None = None,
    prompt_cache: PromptCache | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    reasoning_effort: str | None = None,
    max_output_tokens: int | None = None,
    adapter_options: Mapping[str, object] | None = None,
    timeout_seconds: float | None = None,
) -> ProviderRequestModel:
    """Build direct adapter fixtures with options owned by ModelSpec."""

    if adapter_options is not None:
        model = ModelSpec(
            id=model.id,
            providers=model.providers,
            context_window_tokens=model.context_window_tokens,
            adapter=model.adapter,
            capabilities=model.capabilities,
            adapter_options=AdapterOptions(
                {
                    **({"variant": "k2"} if model.adapter is AdapterKind.KIMI else {}),
                    **adapter_options,
                }
            ),
            reasoning_effort=reasoning_effort,
            request_overrides=model.request_overrides,
        )
    # These adapter fixtures provide a native chat trace from the configured route.
    native_messages = []
    for message in messages.messages:
        if (
            isinstance(message, AssistantMessage)
            and message.reasoning is not None
            and message.reasoning.summary
            and message.reasoning.native_replay is None
            and model.adapter not in {AdapterKind.GPT, AdapterKind.OPENAI_RESPONSES}
        ):
            fingerprint = message_fingerprint(message)
            if fingerprint is not None:
                message = replace(
                    message,
                    reasoning=Reasoning(
                        summary=message.reasoning.summary,
                        native_replay=NativeReplay(
                            mode=NativeReplayMode.CONTENT,
                            api_mode=ApiMode.OPENAI_CHAT,
                            adapter=model.adapter,
                            provider_id=model.providers[0].provider_id,
                            provider_model=model.providers[0].provider_model,
                            variant=model.adapter_options.variant,
                            message_fingerprint=fingerprint,
                            ordered_items=(
                                {"reasoning_content": message.reasoning.summary},
                            ),
                        ),
                    ),
                )
        native_messages.append(message)
    messages = MessageStack.of(*native_messages)
    return ProviderRequestModel(
        model=model,
        binding=model.providers[0],
        messages=messages,
        answer_format=answer_format,
        tool_use=tool_use,
        tool_scope=tool_scope or ToolScope(),
        prompt_cache=prompt_cache,
        temperature=temperature,
        top_p=top_p,
        max_output_tokens=max_output_tokens,
        timeout_seconds=timeout_seconds,
    )


@dataclass
class FakeCreateClient:
    response: object
    calls: list[dict[str, object]] = field(default_factory=list)

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.response


def _provider(provider_id: str) -> ProviderSpec:
    adapter = {
        "kimi": AdapterKind.KIMI,
        "kimi_coding": AdapterKind.KIMI,
        "deepseek": AdapterKind.DEEPSEEK,
        "glm": AdapterKind.GLM,
        "minimax": AdapterKind.MINIMAX,
        "openai": AdapterKind.GPT,
    }.get(provider_id, AdapterKind.OPENAI_CHAT)
    return ProviderSpec(
        id=provider_id,
        endpoints=(
            ProviderEndpoint(
                ApiMode.OPENAI_RESPONSES
                if adapter is AdapterKind.GPT
                else ApiMode.OPENAI_CHAT,
                "https://example.test/v1",
            ),
        ),
        api_key_envs=("API_KEY",),
    )


def _model(
    *,
    provider_id: str,
    provider_model: str,
    options: dict[str, object] | None = None,
    reasoning_effort: str | None = None,
    top_p: float | None = None,
) -> ModelSpec:
    adapter = {
        "kimi": AdapterKind.KIMI,
        "kimi_coding": AdapterKind.KIMI,
        "deepseek": AdapterKind.DEEPSEEK,
        "glm": AdapterKind.GLM,
        "minimax": AdapterKind.MINIMAX,
        "openai": AdapterKind.GPT,
    }.get(provider_id, AdapterKind.OPENAI_CHAT)
    return ModelSpec(
        id=provider_model.replace(".", "_"),
        providers=(ModelProviderBinding(provider_id, provider_model),),
        context_window_tokens=262_144,
        capabilities=frozenset(
            {
                ModelCapability.TEXT_INPUT,
                ModelCapability.IMAGE_INPUT,
                ModelCapability.IMAGE_REMOTE_URL,
                ModelCapability.JSON_OBJECT_OUTPUT,
                ModelCapability.PROMPT_CACHE,
            }
        ),
        adapter_options=AdapterOptions(
            {
                **({"variant": "k2"} if adapter is AdapterKind.KIMI else {}),
                **(options or {}),
            }
        ),
        reasoning_effort=reasoning_effort,
        request_overrides=RequestOverrides(top_p=top_p),
        adapter=adapter,
    )


def _tool() -> ToolSpec:
    return ToolSpec(
        name="read_file",
        description="Read a workspace file",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        kind=ToolKind.ACTION,
    )


def _provider_tool_payload() -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a workspace file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        },
    }


def _write_provider_tool_payload() -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write a workspace file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        },
    }


def _responses_tool_payload() -> dict[str, object]:
    return {
        "type": "function",
        "name": "read_file",
        "description": "Read a workspace file",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
        },
    }


def _message_payloads(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise AssertionError("Expected list of message payloads")
    result: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise AssertionError("Expected message payload mapping")
        result.append({str(key): payload for key, payload in item.items()})
    return result


def _mapping_payload(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise AssertionError("Expected nested mapping payload")
    return {str(key): payload for key, payload in value.items()}
