"""Google parts preserve signatures in their original part and order."""

from google.genai import types

from tinysoul.llm.execution.message_rendering import (
    MessageContentRenderer,
    RenderedImage,
    RenderedImageUrl,
    RenderedText,
)
from tinysoul.llm.protocol.messages import (
    AssistantMessage,
    MessagePart,
    SystemMessage,
    ToolResultMessage,
)
from tinysoul.llm.protocol.reasoning import NativeReplayMode
from tinysoul.llm.protocol.tools import ToolUse

from ..base import ProviderError, ProviderErrorKind, ProviderRequest
from ..common import cache_boundaries
from ..history import (
    assistant_context_parts,
    tool_replay_plan,
    tool_result_content,
    tool_result_text,
)
from ..replay import matching_replay
from ..tool_names import ProviderToolNameMap


def parts_payload(parts: tuple[MessagePart, ...]) -> list[types.Part]:
    rendered = MessageContentRenderer().render(parts)
    if isinstance(rendered, str):
        return [types.Part(text=rendered)] if rendered else []
    result: list[types.Part] = []
    for part in rendered:
        if isinstance(part, RenderedText):
            result.append(types.Part(text=part.text))
        elif isinstance(part, RenderedImage):
            result.append(
                types.Part(
                    inline_data=types.Blob(data=part.data, mime_type=part.mime_type)
                )
            )
        elif isinstance(part, RenderedImageUrl):
            result.append(types.Part(file_data=types.FileData(file_uri=part.url)))
    return result


def message_payload(
    request: ProviderRequest, names: ProviderToolNameMap
) -> tuple[types.Content | None, list[types.Content], int]:
    system_parts: list[types.Part] = []
    contents: list[types.Content] = []
    prefix_count = 0
    call_ids: dict[str, str | None] = {}
    native_tool_call_ids: set[str] = set()
    options = request.model.adapter_options.values
    candidates = cache_boundaries(request)
    boundary = (
        candidates[0].message_index
        if candidates and options.get("prompt_cache_mode") == "explicit"
        else None
    )
    plan = tool_replay_plan(request.messages.messages)
    if boundary is not None:
        for index, message in enumerate(request.messages.messages[: boundary + 1]):
            if (
                isinstance(message, AssistantMessage)
                and index in plan.assistant_indices
                and index + len(message.tool_calls) > boundary
            ):
                boundary = index - 1
                break
    renderer = MessageContentRenderer()
    for index, message in enumerate(request.messages.messages):
        if not isinstance(message, ToolResultMessage):
            call_ids.clear()
            native_tool_call_ids.clear()
        role = "user"
        if isinstance(message, SystemMessage):
            parts = parts_payload(message.parts)
            if any(part.text is None for part in parts):
                raise ProviderError(
                    "Google system instructions must be text",
                    kind=ProviderErrorKind.CAPABILITY,
                )
            system_parts.extend(parts)
        else:
            if isinstance(message, AssistantMessage):
                role = "model"
                native = (
                    request.tool_use is not ToolUse.DISABLED
                    and index in plan.assistant_indices
                )
                replay = (
                    matching_replay(message, request, mode=NativeReplayMode.SIGNED)
                    if request.model.adapter_options.native_replay_mode()
                    is NativeReplayMode.SIGNED
                    and (not message.tool_calls or native)
                    else ()
                )
                native_parts = [types.Part.model_validate(item) for item in replay]
                native_calls = [
                    part.function_call
                    for part in native_parts
                    if part.function_call is not None
                ]
                if [call.name for call in native_calls] != [
                    names.to_provider_name(call.name) for call in message.tool_calls
                ]:
                    replay = ()
                saved = message.reasoning.native_replay if message.reasoning else None
                signed = saved is not None and any(
                    item.get("thought_signature") or item.get("thoughtSignature")
                    for item in saved.ordered_items
                )
                plain_calls = native and not replay and not signed
                parts = (
                    native_parts
                    if replay
                    else parts_payload(
                        assistant_context_parts(message, native_calls=plain_calls)
                    )
                )
                if plain_calls:
                    for call in message.tool_calls:
                        parts.append(
                            types.Part(
                                function_call=types.FunctionCall(
                                    id=call.id,
                                    name=names.to_provider_name(call.name),
                                    args=call.arguments,
                                )
                            )
                        )
                        call_ids[call.id] = call.id
                        native_tool_call_ids.add(call.id)
                if replay and native:
                    for call, original in zip(
                        message.tool_calls, native_calls, strict=True
                    ):
                        call_ids[call.id] = original.id
                        native_tool_call_ids.add(call.id)
            elif isinstance(message, ToolResultMessage):
                if message.call_id in native_tool_call_ids:
                    parts = [
                        types.Part(
                            function_response=types.FunctionResponse(
                                id=call_ids.get(message.call_id),
                                name=names.to_provider_name(message.tool_name),
                                response={
                                    "result": tool_result_content(
                                        message, renderer=renderer
                                    )
                                },
                            )
                        )
                    ]
                else:
                    parts = [
                        types.Part(text=tool_result_text(message, renderer=renderer))
                    ]
            else:
                parts = parts_payload(message.parts)
            if parts:
                contents.append(types.Content(role=role, parts=parts))
        if index == boundary:
            prefix_count = len(contents)
    system = types.Content(parts=system_parts) if system_parts else None
    return system, contents, prefix_count
