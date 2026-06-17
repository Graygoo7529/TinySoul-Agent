"""TinySoul message stack model."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


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

    data: bytes
    mime_type: str

    def __post_init__(self) -> None:
        if not self.data:
            raise ValueError("ImagePart requires non-empty image data")
        if not self.mime_type:
            raise ValueError("ImagePart requires a non-empty MIME type")


@dataclass(frozen=True)
class ImageUrlPart:
    """A remote image URL message part."""

    url: str

    def __post_init__(self) -> None:
        if not self.url:
            raise ValueError("ImageUrlPart requires a non-empty URL")


MessagePart = TextPart | ImagePart | ImageUrlPart


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
