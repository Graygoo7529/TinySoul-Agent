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
    Message,
    MessageStack,
    SystemMessage,
    TextPart,
    ToolResultMessage,
    UserMessage,
)
from tinysoul.llm.models import ModelCapability, ModelSpec
from tinysoul.llm.provider import (
    ProviderAdapter,
    ProviderError,
    ProviderErrorKind,
    ProviderRequest,
)
from tinysoul.llm.provider.factory import build_provider_registry
from tinysoul.llm.responses import AnswerFormat, RawResponse
from tinysoul.llm.tools import (
    ToolCallRecord,
    ToolKind,
    ToolScope,
    ToolSelection,
    ToolSpec,
    ToolUse,
)


pytestmark = [
    pytest.mark.external,
    pytest.mark.skipif(
        os.environ.get("TINYSOUL_RUN_REAL_LLM_API") != "1",
        reason="real LLM API integration test is disabled",
    ),
]

PRIMARY_MODEL_IDS = (
    "gpt_5_6_sol",
    "gpt_5_6_terra",
    "gpt_5_6_luna",
    "gpt_5_5",
    "kimi_k3",
    "kimi_k2_7",
    "deepseek_v4",
    "glm_5_1",
    "minimax_m3",
)

TOOL_MODEL_IDS = (
    "gpt_5_6_sol",
    "gpt_5_6_terra",
    "gpt_5_6_luna",
    "gpt_5_5",
    "kimi_k3",
    "kimi_k2_7",
    "deepseek_v4",
    "glm_5_1",
    "minimax_m3",
)


@pytest.mark.parametrize("model_id", PRIMARY_MODEL_IDS)
def test_real_provider_primary_model_two_rounds(model_id: str) -> None:
    model, provider, adapter = _load_model_adapter(model_id)
    messages = MessageStack.of(
        SystemMessage.from_text(
            "Return only a compact JSON object. Do not include markdown. "
            "When the user provides an expected JSON object, copy the requested "
            "keys into your answer and do not replace them with a summary."
        ),
        _first_user_message(model),
    )
    prompt_cache = PromptCache(key=f"real-api:{model.id}:stable-context")
    max_output_tokens = _test_max_output_tokens(model)
    _print_run_header(model, provider)

    first_response = _invoke_real_provider(
        adapter,
        ProviderRequest(
            model=model,
            messages=messages,
            answer_format=AnswerFormat.JSON_OBJECT,
            prompt_cache=prompt_cache,
            temperature=0.2,
            max_output_tokens=max_output_tokens,
        ),
        provider_id=provider.id,
        model_id=model.id,
        label="primary round 1",
    )
    _assert_provider_returned(
        first_response.answer_text,
        provider_id=provider.id,
        model_id=model.id,
        round_number=1,
    )
    _print_response_summary(round_number=1, answer=first_response.answer_text, response=first_response)

    messages = messages.append(
        AssistantMessage.from_text(first_response.answer_text,
            reasoning=first_response.reasoning,
        )
    ).append(
        UserMessage.from_parts(
            TextPart(
                "Continue the same task. Return only a JSON object that includes "
                "the keys provider, model, round, must_return_json_object, and "
                "uses_previous_reasoning_when_available."
            ),
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

    second_response = _invoke_real_provider(
        adapter,
        ProviderRequest(
            model=model,
            messages=messages,
            answer_format=AnswerFormat.JSON_OBJECT,
            prompt_cache=prompt_cache,
            temperature=0.2,
            max_output_tokens=max_output_tokens,
        ),
        provider_id=provider.id,
        model_id=model.id,
        label="primary round 2",
    )
    _assert_provider_returned(
        second_response.answer_text,
        provider_id=provider.id,
        model_id=model.id,
        round_number=2,
    )
    _print_response_summary(round_number=2, answer=second_response.answer_text, response=second_response)


@pytest.mark.parametrize("model_id", TOOL_MODEL_IDS)
def test_real_provider_model_two_tool_rounds(model_id: str) -> None:
    model, provider, adapter = _load_model_adapter(model_id)
    if not model.supports(ModelCapability.TOOL_CALLING):
        pytest.skip(f"{model.id} does not declare tool calling capability")
    prompt_cache = PromptCache(key=f"real-api:{model.id}:tool-context")
    max_output_tokens = _test_max_output_tokens(model)
    tool_scope = ToolScope(
        tools=(_lookup_tool(), _summarize_tool()),
        selection=ToolSelection(forced_name="lookup_workspace_note"),
    )
    messages = MessageStack.of(
        SystemMessage.from_text(
            "Use the provided tools. Return concise responses and do not invent tool results."
        ),
        UserMessage.from_parts(
            TextPart(
                "First call lookup_workspace_note for note_id alpha. "
                "Then wait for the tool result."
            ),
            JsonPart({"expected_tool": "lookup_workspace_note", "note_id": "alpha"}),
        ),
    )
    _print_run_header(model, provider)

    first_response = _invoke_real_provider(
        adapter,
        ProviderRequest(
            model=model,
            messages=messages,
            answer_format=AnswerFormat.NONE,
            tool_use=ToolUse.REQUIRED,
            tool_scope=tool_scope,
            prompt_cache=prompt_cache,
            temperature=0.2,
            max_output_tokens=max_output_tokens,
        ),
        provider_id=provider.id,
        model_id=model.id,
        label="tool round 1",
    )
    _assert_tool_call_returned(
        first_response.tool_calls,
        expected_name="lookup_workspace_note",
        provider_id=provider.id,
        model_id=model.id,
        round_number=1,
    )
    first_call = _tool_call_by_name(
        first_response.tool_calls,
        "lookup_workspace_note",
    )
    _print_tool_response_summary(
        round_number=1,
        response=first_response,
        tool_calls=first_response.tool_calls,
    )

    messages = messages.append(
        AssistantMessage.from_parts(
            reasoning=first_response.reasoning,
            tool_calls=(first_call,),
        )
    ).append(
        ToolResultMessage.from_json(
            call_id=first_call.id,
            tool_name="lookup_workspace_note",
            value={
                "note_id": "alpha",
                "workspace_link": "workspace:notes/alpha.md",
                "summary": "Alpha note says the release checklist has three items.",
                "status": "ok",
            },
        )
    ).append(
        UserMessage.from_parts(
            TextPart(
                "Now call summarize_workspace_note using the workspace link "
                "from the tool result."
            ),
            JsonPart(
                {
                    "expected_tool": "summarize_workspace_note",
                    "workspace_link": "workspace:notes/alpha.md",
                }
            ),
        )
    )

    second_response = _invoke_real_provider(
        adapter,
        ProviderRequest(
            model=model,
            messages=messages,
            answer_format=AnswerFormat.NONE,
            tool_use=ToolUse.REQUIRED,
            tool_scope=ToolScope(
                tools=(_lookup_tool(), _summarize_tool()),
                selection=ToolSelection(forced_name="summarize_workspace_note"),
            ),
            prompt_cache=prompt_cache,
            temperature=0.2,
            max_output_tokens=max_output_tokens,
        ),
        provider_id=provider.id,
        model_id=model.id,
        label="tool round 2",
    )
    _assert_tool_call_returned(
        second_response.tool_calls,
        expected_name="summarize_workspace_note",
        provider_id=provider.id,
        model_id=model.id,
        round_number=2,
    )
    _print_tool_response_summary(
        round_number=2,
        response=second_response,
        tool_calls=second_response.tool_calls,
    )


def _load_model_adapter(model_id: str) -> tuple[ModelSpec, ProviderSpec, ProviderAdapter]:
    configured_root = os.environ.get("TINYSOUL_REAL_PROJECT_ROOT", "")
    if not configured_root:
        pytest.fail(
            "TINYSOUL_REAL_PROJECT_ROOT must name an initialized, configured project"
        )
    environment = ConfigEnvironment.from_project_root(
        Path(configured_root).expanduser().resolve()
    )
    config = LLMConfigParser().parse(environment.section_tree("llm"))
    model = config.models.get(model_id)
    provider = config.provider(model.provider_id)
    try:
        registry = build_provider_registry((provider,), env=environment.runtime_env)
    except ConfigError as exc:
        pytest.skip(f"{provider.id} API key is not configured: {exc}")
    return model, provider, registry.get(provider.id)


def _invoke_real_provider(
    adapter: ProviderAdapter,
    request: ProviderRequest,
    *,
    provider_id: str,
    model_id: str,
    label: str,
) -> RawResponse:
    try:
        return adapter.invoke(request)
    except ProviderError as exc:
        if exc.kind is ProviderErrorKind.TRANSIENT:
            pytest.skip(
                f"{provider_id}/{model_id} {label} transient provider failure: {exc}"
            )
        raise


def _first_user_message(model: ModelSpec) -> Message:
    text = TextPart(
        "Return only a JSON object that includes the keys model, round, "
        "must_return_json_object, contains_json_part, and contains_image_part. "
        "Use the values from the supplied JSON object."
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
    if model.provider_id == "glm":
        return 4096
    if model.provider_id in {"deepseek", "minimax"}:
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


def _assert_tool_call_returned(
    tool_calls: tuple[ToolCallRecord, ...],
    *,
    expected_name: str,
    provider_id: str,
    model_id: str,
    round_number: int,
) -> None:
    assert tool_calls, (
        f"{provider_id}/{model_id} round {round_number} returned no tool calls"
    )
    assert any(tool_call.name == expected_name for tool_call in tool_calls), (
        f"{provider_id}/{model_id} round {round_number} did not return "
        f"expected tool {expected_name}; got {[call.name for call in tool_calls]}"
    )


def _tool_call_by_name(
    tool_calls: tuple[ToolCallRecord, ...],
    name: str,
) -> ToolCallRecord:
    for tool_call in tool_calls:
        if tool_call.name == name:
            return tool_call
    raise AssertionError(f"Missing tool call: {name}")


def _lookup_tool() -> ToolSpec:
    return ToolSpec(
        name="lookup_workspace_note",
        description="Look up a TinySoul workspace note by id.",
        parameters={
            "type": "object",
            "properties": {
                "note_id": {
                    "type": "string",
                    "description": "Workspace note id to look up.",
                }
            },
            "required": ["note_id"],
        },
        kind=ToolKind.ACTION,
    )


def _summarize_tool() -> ToolSpec:
    return ToolSpec(
        name="summarize_workspace_note",
        description="Summarize a TinySoul workspace note from a workspace link.",
        parameters={
            "type": "object",
            "properties": {
                "workspace_link": {
                    "type": "string",
                    "description": "Workspace link returned by lookup_workspace_note.",
                },
                "focus": {
                    "type": "string",
                    "description": "Optional summary focus.",
                },
            },
            "required": ["workspace_link"],
        },
        kind=ToolKind.ACTION,
    )


def _print_run_header(model: ModelSpec, provider: ProviderSpec) -> None:
    capabilities = ", ".join(sorted(capability.value for capability in model.capabilities))
    print(
        "\n"
        f"[real-llm] provider={provider.id} api_style={provider.api_style.value} "
        f"model_id={model.id} provider_model={model.provider_model}"
    )
    print(f"[real-llm] capabilities={capabilities}")
    print(f"[real-llm] adapter_options={dict(model.adapter_options.values)}")


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


def _print_tool_response_summary(
    *,
    round_number: int,
    response: object,
    tool_calls: tuple[ToolCallRecord, ...],
) -> None:
    usage = getattr(response, "usage", {})
    metadata = getattr(response, "metadata", {})
    print(
        f"[real-llm] tool_round={round_number} calls="
        f"{[(call.id, call.name, call.arguments) for call in tool_calls]}"
    )
    print(
        f"[real-llm] tool_round={round_number} "
        f"reasoning={_reasoning_summary(getattr(response, 'reasoning', None))}"
    )
    print(f"[real-llm] tool_round={round_number} usage={usage}")
    print(f"[real-llm] tool_round={round_number} metadata={metadata}")


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
