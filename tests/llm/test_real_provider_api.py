from __future__ import annotations

import os
import struct
import zlib
from pathlib import Path

import pytest

from tinysoul.infra.config import ConfigEnvironment, ConfigError
from tinysoul.llm.cache import PromptCache
from tinysoul.llm.config import LLMConfigParser, ProviderSpec
from tinysoul.llm.messages import (
    AssistantMessage,
    ImagePart,
    JsonPart,
    MessageStack,
    SystemMessage,
    TextPart,
    UserMessage,
)
from tinysoul.llm.models import ModelCapability, ModelSpec
from tinysoul.llm.provider import ProviderAdapter, ProviderRequest
from tinysoul.llm.provider.factory import build_provider_registry
from tinysoul.llm.responses import ResponseContract


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
    messages = MessageStack.of(
        SystemMessage.from_text("Return only a compact JSON object. Do not include markdown.",
        ),
        _first_user_message(model),
    )
    prompt_cache = PromptCache(key=f"real-api:{model.id}:stable-context")
    max_output_tokens = _test_max_output_tokens(model)
    _print_run_header(model, provider)

    first_response = adapter.invoke(
        ProviderRequest(
            model=model,
            messages=messages,
            response_contract=ResponseContract.JSON_OBJECT,
            prompt_cache=prompt_cache,
            temperature=0.2,
            max_output_tokens=max_output_tokens,
            provider_options=dict(model.provider_options.values),
        )
    )
    _assert_provider_returned(
        first_response.answer,
        provider_id=provider.id,
        model_id=model.id,
        round_number=1,
    )
    _print_response_summary(round_number=1, answer=first_response.answer, response=first_response)

    messages = messages.append(
        AssistantMessage.from_text(first_response.answer,
            reasoning=first_response.reasoning,
        )
    ).append(
        UserMessage.from_parts(
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
            max_output_tokens=max_output_tokens,
            provider_options=dict(model.provider_options.values),
        )
    )
    _assert_provider_returned(
        second_response.answer,
        provider_id=provider.id,
        model_id=model.id,
        round_number=2,
    )
    _print_response_summary(round_number=2, answer=second_response.answer, response=second_response)


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
        return UserMessage.from_parts(
            text,
            ImagePart(data=_sample_png(), mime_type="image/png"),
            payload,
        )
    return UserMessage.from_parts( text, payload)


def _test_max_output_tokens(model: ModelSpec) -> int:
    if model.provider_id in {"glm", "minimax"}:
        return 2048
    return 512


def _sample_png() -> bytes:
    width = 64
    height = 64
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            rows.extend(((x * 4) % 256, (y * 4) % 256, 160))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(bytes(rows)))
        + _png_chunk(b"IEND", b"")
    )


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def _assert_provider_returned(
    answer: str,
    *,
    provider_id: str,
    model_id: str,
    round_number: int,
) -> None:
    assert isinstance(answer, str), (
        f"{provider_id}/{model_id} round {round_number} returned non-string answer"
    )


def _print_run_header(model: ModelSpec, provider: ProviderSpec) -> None:
    capabilities = ", ".join(sorted(capability.value for capability in model.capabilities))
    print(
        "\n"
        f"[real-llm] provider={provider.id} api_style={provider.api_style.value} "
        f"model_id={model.id} provider_model={model.provider_model}"
    )
    print(f"[real-llm] capabilities={capabilities}")
    print(f"[real-llm] provider_options={dict(model.provider_options.values)}")


def _print_response_summary(
    *,
    round_number: int,
    answer: str,
    response: object,
) -> None:
    reasoning = getattr(response, "reasoning", None)
    usage = getattr(response, "usage", {})
    metadata = getattr(response, "metadata", {})
    print(
        f"[real-llm] round={round_number} answer_len={len(answer)} "
        f"answer_preview={_preview(answer)!r}"
    )
    print(
        f"[real-llm] round={round_number} reasoning={_reasoning_summary(reasoning)}"
    )
    print(f"[real-llm] round={round_number} usage={usage}")
    print(f"[real-llm] round={round_number} metadata={metadata}")


def _preview(text: str, limit: int = 180) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def _reasoning_summary(reasoning: object) -> dict[str, object]:
    if reasoning is None:
        return {"present": False}
    content = getattr(reasoning, "content", None)
    summary = getattr(reasoning, "summary", None)
    encrypted_items = getattr(reasoning, "encrypted_items", ())
    return {
        "present": True,
        "content_len": len(content) if isinstance(content, str) else 0,
        "summary_len": len(summary) if isinstance(summary, str) else 0,
        "encrypted_items": len(encrypted_items),
    }

