from __future__ import annotations

import pytest

from tinysoul.llm.messages import (
    ImagePart,
    ImageUrlPart,
    JsonPart,
    Message,
    MessageRole,
    MessageStack,
    TextPart,
)


def test_message_stack_appends_immutably() -> None:
    stack = MessageStack.of(Message.from_text(MessageRole.SYSTEM, "rules"))
    updated = stack.append(Message.from_text(MessageRole.USER, "hello"))

    assert len(stack.messages) == 1
    assert len(updated.messages) == 2
    assert isinstance(updated.messages[1].parts[0], TextPart)


def test_message_constructs_from_json_and_parts() -> None:
    message = Message.from_json(
        MessageRole.USER,
        {"source": "tool_result", "ok": True},
    ).add_part(TextPart("done"))

    assert isinstance(message.parts[0], JsonPart)
    assert message.parts[0].value == {"source": "tool_result", "ok": True}
    assert message.parts[1] == TextPart("done")


def test_message_add_parts_preserves_metadata() -> None:
    message = Message.from_parts(
        MessageRole.ASSISTANT,
        TextPart("answer"),
        reasoning="trace",
        label="previous",
    )

    updated = message.add_parts(JsonPart({"ok": True}))

    assert len(message.parts) == 1
    assert len(updated.parts) == 2
    assert updated.reasoning == message.reasoning
    assert updated.label == "previous"


def test_image_part_requires_data_and_mime_type() -> None:
    with pytest.raises(ValueError):
        ImagePart(data=b"", mime_type="image/png")

    with pytest.raises(ValueError):
        ImagePart(data=b"abc", mime_type="")


def test_image_url_part_requires_url() -> None:
    with pytest.raises(ValueError):
        ImageUrlPart(url="")
