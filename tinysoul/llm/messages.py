"""TinySoul message stack model."""

from __future__ import annotations

from dataclasses import dataclass, field

from tinysoul.infra.json import JsonObject, to_json_object

from .reasoning import Reasoning
from .tools import ToolCallRecord, ToolResultStatus


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
class SystemMessage:
    """A system message with TinySoul metadata."""

    parts: tuple[MessagePart, ...]
    label: str = ""

    @classmethod
    def from_text(cls, text: str, *, label: str = "") -> "SystemMessage":
        return cls(parts=(TextPart(text),), label=label)

    @classmethod
    def from_json(cls, value: object, *, label: str = "") -> "SystemMessage":
        return cls(parts=(JsonPart(to_json_object(value)),), label=label)

    @classmethod
    def from_parts(
        cls,
        *parts: MessagePart,
        label: str = "",
    ) -> "SystemMessage":
        return cls(parts=tuple(parts), label=label)

    def add_part(self, part: MessagePart) -> "SystemMessage":
        return self.add_parts(part)

    def add_parts(self, *parts: MessagePart) -> "SystemMessage":
        return SystemMessage(parts=(*self.parts, *parts), label=self.label)


@dataclass(frozen=True)
class UserMessage:
    """A user message with TinySoul metadata."""

    parts: tuple[MessagePart, ...]
    label: str = ""

    @classmethod
    def from_text(cls, text: str, *, label: str = "") -> "UserMessage":
        return cls(parts=(TextPart(text),), label=label)

    @classmethod
    def from_json(cls, value: object, *, label: str = "") -> "UserMessage":
        return cls(parts=(JsonPart(to_json_object(value)),), label=label)

    @classmethod
    def from_parts(
        cls,
        *parts: MessagePart,
        label: str = "",
    ) -> "UserMessage":
        return cls(parts=tuple(parts), label=label)

    def add_part(self, part: MessagePart) -> "UserMessage":
        return self.add_parts(part)

    def add_parts(self, *parts: MessagePart) -> "UserMessage":
        return UserMessage(parts=(*self.parts, *parts), label=self.label)


@dataclass(frozen=True)
class AssistantMessage:
    """An assistant message with optional reasoning and tool calls."""

    parts: tuple[MessagePart, ...] = field(default_factory=tuple)
    reasoning: Reasoning | None = None
    tool_calls: tuple[ToolCallRecord, ...] = field(default_factory=tuple)
    label: str = ""

    @classmethod
    def from_text(
        cls,
        text: str,
        reasoning: str | Reasoning | None = None,
        *,
        tool_calls: tuple[ToolCallRecord, ...] = (),
        label: str = "",
    ) -> "AssistantMessage":
        return cls(
            parts=(TextPart(text),),
            reasoning=_reasoning(reasoning),
            tool_calls=tool_calls,
            label=label,
        )

    @classmethod
    def from_json(
        cls,
        value: object,
        reasoning: str | Reasoning | None = None,
        *,
        tool_calls: tuple[ToolCallRecord, ...] = (),
        label: str = "",
    ) -> "AssistantMessage":
        return cls(
            parts=(JsonPart(to_json_object(value)),),
            reasoning=_reasoning(reasoning),
            tool_calls=tool_calls,
            label=label,
        )

    @classmethod
    def from_parts(
        cls,
        *parts: MessagePart,
        reasoning: str | Reasoning | None = None,
        tool_calls: tuple[ToolCallRecord, ...] = (),
        label: str = "",
    ) -> "AssistantMessage":
        return cls(
            parts=tuple(parts),
            reasoning=_reasoning(reasoning),
            tool_calls=tool_calls,
            label=label,
        )

    @classmethod
    def from_tool_calls(
        cls,
        *tool_calls: ToolCallRecord,
        label: str = "",
    ) -> "AssistantMessage":
        return cls(tool_calls=tuple(tool_calls), label=label)

    def add_part(self, part: MessagePart) -> "AssistantMessage":
        return self.add_parts(part)

    def add_parts(self, *parts: MessagePart) -> "AssistantMessage":
        return AssistantMessage(
            parts=(*self.parts, *parts),
            reasoning=self.reasoning,
            tool_calls=self.tool_calls,
            label=self.label,
        )

    def add_tool_calls(self, *tool_calls: ToolCallRecord) -> "AssistantMessage":
        return AssistantMessage(
            parts=self.parts,
            reasoning=self.reasoning,
            tool_calls=(*self.tool_calls, *tool_calls),
            label=self.label,
        )


@dataclass(frozen=True)
class ToolResultMessage:
    """A model-side tool result replay message."""

    call_id: str
    tool_name: str
    parts: tuple[MessagePart, ...]
    status: ToolResultStatus = ToolResultStatus.OK
    provider_call_id: str | None = None
    label: str = ""

    def __post_init__(self) -> None:
        if not self.call_id:
            raise ValueError("ToolResultMessage.call_id must be non-empty")
        if not self.tool_name:
            raise ValueError("ToolResultMessage.tool_name must be non-empty")
        if self.provider_call_id is not None and not self.provider_call_id:
            raise ValueError("ToolResultMessage.provider_call_id must be non-empty")

    @classmethod
    def from_text(
        cls,
        *,
        call_id: str,
        tool_name: str,
        text: str,
        status: ToolResultStatus = ToolResultStatus.OK,
        provider_call_id: str | None = None,
        label: str = "",
    ) -> "ToolResultMessage":
        return cls(
            call_id=call_id,
            tool_name=tool_name,
            parts=(TextPart(text),),
            status=status,
            provider_call_id=provider_call_id,
            label=label,
        )

    @classmethod
    def from_json(
        cls,
        *,
        call_id: str,
        tool_name: str,
        value: object,
        status: ToolResultStatus = ToolResultStatus.OK,
        provider_call_id: str | None = None,
        label: str = "",
    ) -> "ToolResultMessage":
        return cls(
            call_id=call_id,
            tool_name=tool_name,
            parts=(JsonPart(to_json_object(value)),),
            status=status,
            provider_call_id=provider_call_id,
            label=label,
        )

    @classmethod
    def from_parts(
        cls,
        *,
        call_id: str,
        tool_name: str,
        parts: tuple[MessagePart, ...],
        status: ToolResultStatus = ToolResultStatus.OK,
        provider_call_id: str | None = None,
        label: str = "",
    ) -> "ToolResultMessage":
        return cls(
            call_id=call_id,
            tool_name=tool_name,
            parts=parts,
            status=status,
            provider_call_id=provider_call_id,
            label=label,
        )


Message = SystemMessage | UserMessage | AssistantMessage | ToolResultMessage


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
