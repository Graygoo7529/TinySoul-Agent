from __future__ import annotations

from pathlib import Path

import pytest

from tinysoul.llm.messages import ImagePart, Message, MessageRole, MessageStack, TextPart


def test_message_stack_appends_immutably() -> None:
    stack = MessageStack.of(Message.text(MessageRole.SYSTEM, "rules"))
    updated = stack.append(Message.text(MessageRole.USER, "hello"))

    assert len(stack.messages) == 1
    assert len(updated.messages) == 2
    assert isinstance(updated.messages[1].parts[0], TextPart)


def test_image_part_requires_one_source() -> None:
    with pytest.raises(ValueError):
        ImagePart()

    with pytest.raises(ValueError):
        ImagePart(path=Path("a.png"), url="https://example.test/a.png")

