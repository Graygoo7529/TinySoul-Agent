"""TinySoul message stack model."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from tinysoul.infra.json import JsonObject, to_json_object

from .reasoning import Reasoning

class MessageRole(StrEnum):
    """Provider-visible message role."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class TextPart:
    """A plain text message part."""

    text: str


@dataclass(frozen=True)
class JsonPart:
    """A structured JSON message part."""

    value: JsonObject


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


MessagePart = TextPart | JsonPart | ImagePart | ImageUrlPart


@dataclass(frozen=True)
class Message:
    """A provider-visible message with TinySoul metadata."""

    role: MessageRole
    parts: tuple[MessagePart, ...]
    reasoning: Reasoning | None = None
    label: str = ""

    def __post_init__(self) -> None:
        if self.reasoning is not None and self.role is not MessageRole.ASSISTANT:
            raise ValueError("Message reasoning is only valid on assistant messages")

    @classmethod
    def from_text(
        cls,
        role: MessageRole,
        text: str,
        reasoning: str | Reasoning | None = None,
        *,
        label: str = "",
    ) -> "Message":
        resolved_reasoning = _reasoning(reasoning)
        return cls(
            role=role,
            parts=(TextPart(text),),
            reasoning=resolved_reasoning,
            label=label,
        )

    @classmethod
    def from_json(
        cls,
        role: MessageRole,
        value: object,
        reasoning: str | Reasoning | None = None,
        *,
        label: str = "",
    ) -> "Message":
        resolved_reasoning = _reasoning(reasoning)
        return cls(
            role=role,
            parts=(JsonPart(to_json_object(value)),),
            reasoning=resolved_reasoning,
            label=label,
        )

    @classmethod
    def from_parts(
        cls,
        role: MessageRole,
        *parts: MessagePart,
        reasoning: str | Reasoning | None = None,
        label: str = "",
    ) -> "Message":
        resolved_reasoning = _reasoning(reasoning)
        return cls(
            role=role,
            parts=tuple(parts),
            reasoning=resolved_reasoning,
            label=label,
        )

    def add_part(self, part: MessagePart) -> "Message":
        return self.add_parts(part)

    def add_parts(self, *parts: MessagePart) -> "Message":
        return Message(
            role=self.role,
            parts=(*self.parts, *parts),
            reasoning=self.reasoning,
            label=self.label,
        )


@dataclass(frozen=True)
class MessageStack:
    """An ordered stack of model messages."""

    messages: tuple[Message, ...] = field(default_factory=tuple)

    def append(self, message: Message) -> "MessageStack":
        return MessageStack(messages=(*self.messages, message))

    @classmethod
    def of(cls, *messages: Message) -> "MessageStack":
        return cls(messages=tuple(messages))


def _reasoning(value: str | Reasoning | None) -> Reasoning | None:
    if value is None or isinstance(value, Reasoning):
        return value
    return Reasoning.text(value)
