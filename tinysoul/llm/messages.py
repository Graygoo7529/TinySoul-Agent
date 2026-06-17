"""TinySoul message stack model."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class MessageRole(StrEnum):
    """Provider-visible message role."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True)
class TextPart:
    """A plain text message part."""

    text: str


@dataclass(frozen=True)
class ImagePart:
    """An image message part."""

    data: bytes | None = None
    path: Path | None = None
    url: str | None = None
    mime_type: str | None = None
    name: str = ""

    def __post_init__(self) -> None:
        provided = sum(item is not None for item in (self.data, self.path, self.url))
        if provided != 1:
            raise ValueError("ImagePart requires exactly one of data, path, or url")


MessagePart = TextPart | ImagePart


@dataclass(frozen=True)
class Message:
    """A provider-visible message with TinySoul metadata."""

    role: MessageRole
    parts: tuple[MessagePart, ...]
    label: str = ""

    @classmethod
    def text(
        cls,
        role: MessageRole,
        text: str,
        *,
        label: str = "",
    ) -> "Message":
        return cls(role=role, parts=(TextPart(text),), label=label)


@dataclass(frozen=True)
class MessageStack:
    """An ordered stack of model messages."""

    messages: tuple[Message, ...] = field(default_factory=tuple)

    def append(self, message: Message) -> "MessageStack":
        return MessageStack(messages=(*self.messages, message))

    @classmethod
    def of(cls, *messages: Message) -> "MessageStack":
        return cls(messages=tuple(messages))
