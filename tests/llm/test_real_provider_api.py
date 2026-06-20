from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest

from tinysoul.infra.config import ConfigEnvironment, ConfigError
from tinysoul.llm.cache import PromptCache
from tinysoul.llm.config import LLMConfigParser, ProviderSpec
from tinysoul.llm.messages import (
    ImagePart,
    JsonPart,
    Message,
    MessagePart,
    MessageRole,
    MessageStack,
    TextPart,
)
from tinysoul.llm.models import ModelCapability, ModelSpec
from tinysoul.llm.provider import ProviderAdapter, ProviderRequest
from tinysoul.llm.provider.factory import build_provider_registry
from tinysoul.llm.reasoning import Reasoning
from tinysoul.llm.responses import (
    JsonObjectTaskOutput,
    ResponseContract,
    ResponseInterpreter,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("TINYSOUL_RUN_REAL_LLM_API") != "1",
    reason="real LLM API integration test is disabled",
)

PRIMARY_MODEL_IDS = (
    "gpt_5_5",
    "kimi_k2_7",
    "deepseek_v4",
    "glm_5_1",
    "minimax_m3",
)


@pytest.mark.parametrize("model_id", PRIMARY_MODEL_IDS)
def test_real_provider_primary_model_two_rounds(model_id: str) -> None:
    model, provider, adapter = _load_model_adapter(model_id)
    interpreter = ResponseInterpreter()
    messages = MessageStack.of(
        Message.from_text(
            MessageRole.SYSTEM,
            "Return only a compact JSON object. Do not include markdown.",
        ),
        _first_user_message(model),
    )
    prompt_cache = PromptCache(key=f"real-api:{model.id}:stable-context")

    first_response = adapter.invoke(
        ProviderRequest(
            model=model,
            messages=messages,
            response_contract=ResponseContract.JSON_OBJECT,
            prompt_cache=prompt_cache,
            temperature=0.2,
            max_output_tokens=512,
            provider_options=dict(model.provider_options.values),
        )
    )
    first_result = interpreter.interpret(
        first_response,
        ResponseContract.JSON_OBJECT,
    )
    assert isinstance(first_result.output, JsonObjectTaskOutput)

    messages = messages.append(
        Message.from_text(
            MessageRole.ASSISTANT,
            first_response.answer,
            reasoning=first_response.reasoning,
        )
    ).append(
        Message.from_parts(
            MessageRole.USER,
            TextPart("Continue the same task and return only JSON."),
            JsonPart(
                {
                    "provider": provider.id,
                    "model": model.id,
                    "round": 2,
                    "must_return_json_object": True,
                    "uses_previous_reasoning_when_available": (
                        first_response.reasoning is not None
                    ),
                }
            ),
        )
    )

    second_response = adapter.invoke(
        ProviderRequest(
            model=model,
            messages=messages,
            response_contract=ResponseContract.JSON_OBJECT,
            prompt_cache=prompt_cache,
            temperature=0.2,
            max_output_tokens=512,
            provider_options=dict(model.provider_options.values),
        )
    )
    second_result = interpreter.interpret(
        second_response,
        ResponseContract.JSON_OBJECT,
    )
    assert isinstance(second_result.output, JsonObjectTaskOutput)


def _load_model_adapter(model_id: str) -> tuple[ModelSpec, ProviderSpec, ProviderAdapter]:
    environment = ConfigEnvironment.from_project_root(Path("."))
    config = LLMConfigParser().parse(environment.section_tree("llm"))
    model = config.models.get(model_id)
    provider = config.provider(model.provider_id)
    try:
        registry = build_provider_registry((provider,), env=environment.runtime_env)
    except ConfigError as exc:
        pytest.skip(f"{provider.id} API key is not configured: {exc}")
    return model, provider, registry.get(provider.id)


def _first_user_message(model: ModelSpec) -> Message:
    text = TextPart(
        "Inspect the supplied TinySoul test input and return only a JSON object."
    )
    payload = JsonPart(
        {
            "model": model.id,
            "round": 1,
            "must_return_json_object": True,
            "contains_json_part": True,
            "contains_image_part": model.supports(ModelCapability.IMAGE_INPUT),
        }
    )
    if model.supports(ModelCapability.IMAGE_INPUT):
        return Message.from_parts(
            MessageRole.USER,
            text,
            ImagePart(data=_tiny_png(), mime_type="image/png"),
            payload,
        )
    return Message.from_parts(MessageRole.USER, text, payload)


def _tiny_png() -> bytes:
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
        "/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    )
