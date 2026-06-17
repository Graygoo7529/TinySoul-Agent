from __future__ import annotations

import pytest

from tinysoul.llm.messages import (
    ImagePart,
    ImageUrlPart,
    Message,
    MessageRole,
    MessageStack,
    TextPart,
)


def test_message_stack_appends_immutably() -> None:
    stack = MessageStack.of(Message.text(MessageRole.SYSTEM, "rules"))
    updated = stack.append(Message.text(MessageRole.USER, "hello"))

    assert len(stack.messages) == 1
    assert len(updated.messages) == 2
    assert isinstance(updated.messages[1].parts[0], TextPart)


def test_image_part_requires_data_and_mime_type() -> None:
    with pytest.raises(ValueError):
        ImagePart(data=b"", mime_type="image/png")

    with pytest.raises(ValueError):
        ImagePart(data=b"abc", mime_type="")


def test_image_url_part_requires_url() -> None:
    with pytest.raises(ValueError):
        ImageUrlPart(url="")
