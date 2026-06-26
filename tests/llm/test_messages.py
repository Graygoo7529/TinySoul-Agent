from __future__ import annotations

import pytest

from tinysoul.llm.messages import (
    AssistantMessage,
    ImagePart,
    ImageUrlPart,
    JsonPart,
    MessageStack,
    TextPart,
    ToolResultMessage,
    UserMessage,
    SystemMessage,
)
from tinysoul.llm.tools import ToolCallRecord


def test_message_stack_appends_immutably() -> None:
    stack = MessageStack.of(SystemMessage.from_text("rules"))
    updated = stack.append(UserMessage.from_text("hello"))

    assert len(stack.messages) == 1
    assert len(updated.messages) == 2
    assert isinstance(updated.messages[1].parts[0], TextPart)


def test_message_constructs_from_json_and_parts() -> None:
    message = UserMessage.from_json(
        {"source": "tool_result", "ok": True},
    ).add_part(TextPart("done"))

    assert isinstance(message.parts[0], JsonPart)
    assert message.parts[0].value == {"source": "tool_result", "ok": True}
    assert message.parts[1] == TextPart("done")


def test_message_add_parts_preserves_metadata() -> None:
    message = AssistantMessage.from_parts(
        TextPart("answer"),
        reasoning="trace",
        label="previous",
    )

    updated = message.add_parts(JsonPart({"ok": True}))

    assert len(message.parts) == 1
    assert len(updated.parts) == 2
    assert updated.reasoning == message.reasoning
    assert updated.label == "previous"


def test_assistant_message_can_carry_tool_calls() -> None:
    tool_call = ToolCallRecord(
        id="call_1",
        name="read_file",
        arguments={"path": "workspace:doc.md"},
    )

    message = AssistantMessage.from_tool_calls(tool_call)

    assert message.tool_calls == (tool_call,)
    assert message.parts == ()


def test_tool_result_message_uses_message_parts() -> None:
    message = ToolResultMessage.from_json(
        call_id="call_1",
        tool_name="read_file",
        value={"ok": True},
    )

    assert isinstance(message.parts[0], JsonPart)
    assert message.parts[0].value == {"ok": True}


def test_image_part_requires_data_and_mime_type() -> None:
    with pytest.raises(ValueError):
        ImagePart(data=b"", mime_type="image/png")

    with pytest.raises(ValueError):
        ImagePart(data=b"abc", mime_type="")


def test_image_url_part_requires_url() -> None:
    with pytest.raises(ValueError):
        ImageUrlPart(url="")
