"""Complete tool exchange selection and readable fallback shared by API adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass

from tinysoul.llm.execution.message_rendering import (
    MessageContentRenderer,
    RenderedText,
)
from tinysoul.llm.protocol.messages import (
    AssistantMessage,
    Message,
    MessagePart,
    TextPart,
    ToolResultMessage,
)
from tinysoul.llm.protocol.tools import ToolCallRecord, ToolResultStatus
from tinysoul.prompts import llm as prompt_text

from .base import ProviderError, ProviderErrorKind


def tool_result_content(
    message: ToolResultMessage,
    *,
    renderer: MessageContentRenderer,
) -> str:
    rendered = renderer.render(message.parts)
    if isinstance(rendered, str):
        if message.status is ToolResultStatus.OK:
            return rendered
        return f"status: {message.status.value}\n\n{rendered}"
    text_parts: list[str] = []
    for part in rendered:
        if isinstance(part, RenderedText):
            text_parts.append(part.text)
            continue
        raise ProviderError(
            "ToolResultMessage can only be rendered as text content",
            kind=ProviderErrorKind.CONFIG,
        )
    text = "\n\n".join(text_parts)
    if message.status is ToolResultStatus.OK:
        return text
    return f"status: {message.status.value}\n\n{text}"


def tool_result_text(
    message: ToolResultMessage,
    *,
    renderer: MessageContentRenderer,
) -> str:
    """Preserve a result when its exchange cannot use native tool replay."""

    return prompt_text.tool_result_context(
        tool_name=message.tool_name,
        call_id=message.call_id,
        content=tool_result_content(message, renderer=renderer),
    )


def assistant_context_parts(
    message: AssistantMessage, *, native_calls: bool
) -> tuple[MessagePart, ...]:
    """Keep requested calls as context without claiming they were executed."""
    if native_calls:
        return message.parts
    return (
        *message.parts,
        *(
            TextPart(
                prompt_text.tool_call_context(
                    tool_name=call.name,
                    call_id=call.id,
                    arguments=json.dumps(
                        call.arguments, ensure_ascii=False, separators=(",", ":")
                    ),
                )
            )
            for call in message.tool_calls
        ),
    )


@dataclass(frozen=True)
class ToolReplayPlan:
    """Indices of complete, ordered provider-native tool turns."""

    assistant_indices: frozenset[int]
    result_indices: frozenset[int]


def tool_replay_plan(messages: tuple[Message, ...]) -> ToolReplayPlan:
    assistant_indices: set[int] = set()
    result_indices: set[int] = set()
    for index, message in enumerate(messages):
        if not isinstance(message, AssistantMessage) or not message.tool_calls:
            continue
        calls_by_id: dict[str, ToolCallRecord] = {}
        duplicate_call_id = False
        for call in message.tool_calls:
            if call.id in calls_by_id:
                duplicate_call_id = True
                break
            calls_by_id[call.id] = call
        if duplicate_call_id:
            continue

        candidate_results: list[tuple[int, ToolResultMessage]] = []
        cursor = index + 1
        while cursor < len(messages):
            candidate = messages[cursor]
            if not isinstance(candidate, ToolResultMessage):
                break
            candidate_results.append((cursor, candidate))
            cursor += 1
        if len(candidate_results) != len(calls_by_id):
            continue
        result_by_id: dict[str, tuple[int, ToolResultMessage]] = {}
        for result_index, result in candidate_results:
            if result.call_id in result_by_id:
                break
            result_by_id[result.call_id] = (result_index, result)
        if len(result_by_id) != len(calls_by_id):
            continue
        if set(result_by_id) != set(calls_by_id):
            continue
        if any(
            calls_by_id[call_id].name != result.tool_name
            for call_id, (_, result) in result_by_id.items()
        ):
            continue
        assistant_indices.add(index)
        result_indices.update(result_index for result_index, _ in candidate_results)
    return ToolReplayPlan(
        assistant_indices=frozenset(assistant_indices),
        result_indices=frozenset(result_indices),
    )
