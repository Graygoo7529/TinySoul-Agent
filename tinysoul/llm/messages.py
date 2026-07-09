"""TinySoul message stack model."""

from __future__ import annotations

from dataclasses import dataclass, field

from tinysoul.infra.json import JsonObject, JsonTypeError, to_json_object

from .errors import LLMContractError
from .reasoning import Reasoning
from .tools import ToolCallRecord, ToolResultStatus


@dataclass(frozen=True)
class TextPart:
    """A plain text message part."""

    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise LLMContractError("TextPart.text must be a string")


@dataclass(frozen=True)
class JsonPart:
    """A structured JSON message part."""

    value: JsonObject

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _json_object(self.value, field="JsonPart.value"))


@dataclass(frozen=True)
class ImagePart:
    """An image message part."""

    data: bytes
    mime_type: str

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes) or not self.data:
            raise LLMContractError("ImagePart requires non-empty image data")
        if not isinstance(self.mime_type, str) or not self.mime_type:
            raise LLMContractError("ImagePart requires a non-empty MIME type")


@dataclass(frozen=True)
class ImageUrlPart:
    """A remote image URL message part."""

    url: str

    def __post_init__(self) -> None:
        if not isinstance(self.url, str) or not self.url:
            raise LLMContractError("ImageUrlPart requires a non-empty URL")


MessagePart = TextPart | JsonPart | ImagePart | ImageUrlPart
_MESSAGE_PART_TYPES = (TextPart, JsonPart, ImagePart, ImageUrlPart)


@dataclass(frozen=True)
class SystemMessage:
    """A system message with TinySoul metadata."""

    parts: tuple[MessagePart, ...]
    label: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "parts",
            _message_parts(self.parts, field="SystemMessage.parts"),
        )
        _require_label(self.label, field="SystemMessage.label")

    @classmethod
    def from_text(cls, text: str, *, label: str = "") -> "SystemMessage":
        return cls(parts=(TextPart(text),), label=label)

    @classmethod
    def from_json(cls, value: object, *, label: str = "") -> "SystemMessage":
        return cls(
            parts=(_json_part(value, field="SystemMessage.value"),),
            label=label,
        )

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

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "parts",
            _message_parts(self.parts, field="UserMessage.parts"),
        )
        _require_label(self.label, field="UserMessage.label")

    @classmethod
    def from_text(cls, text: str, *, label: str = "") -> "UserMessage":
        return cls(parts=(TextPart(text),), label=label)

    @classmethod
    def from_json(cls, value: object, *, label: str = "") -> "UserMessage":
        return cls(
            parts=(_json_part(value, field="UserMessage.value"),),
            label=label,
        )

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

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "parts",
            _message_parts(self.parts, field="AssistantMessage.parts"),
        )
        object.__setattr__(
            self,
            "tool_calls",
            _tool_calls(self.tool_calls, field="AssistantMessage.tool_calls"),
        )
        if self.reasoning is not None and not isinstance(self.reasoning, Reasoning):
            raise LLMContractError(
                "AssistantMessage.reasoning must be Reasoning or None"
            )
        _require_label(self.label, field="AssistantMessage.label")

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
            parts=(_json_part(value, field="AssistantMessage.value"),),
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
    label: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.call_id, str) or not self.call_id:
            raise LLMContractError("ToolResultMessage.call_id must be non-empty")
        if not isinstance(self.tool_name, str) or not self.tool_name:
            raise LLMContractError("ToolResultMessage.tool_name must be non-empty")
        if not isinstance(self.status, ToolResultStatus):
            raise LLMContractError("ToolResultMessage.status must be a ToolResultStatus")
        object.__setattr__(
            self,
            "parts",
            _message_parts(self.parts, field="ToolResultMessage.parts"),
        )
        for part in self.parts:
            if not isinstance(part, (TextPart, JsonPart)):
                raise LLMContractError(
                    "ToolResultMessage only supports text and JSON parts; "
                    "non-text resources should be passed by rebuilding MessageStack"
                )
        _require_label(self.label, field="ToolResultMessage.label")

    @classmethod
    def from_text(
        cls,
        *,
        call_id: str,
        tool_name: str,
        text: str,
        status: ToolResultStatus = ToolResultStatus.OK,
        label: str = "",
    ) -> "ToolResultMessage":
        return cls(
            call_id=call_id,
            tool_name=tool_name,
            parts=(TextPart(text),),
            status=status,
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
        label: str = "",
    ) -> "ToolResultMessage":
        return cls(
            call_id=call_id,
            tool_name=tool_name,
            parts=(_json_part(value, field="ToolResultMessage.value"),),
            status=status,
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
        label: str = "",
    ) -> "ToolResultMessage":
        return cls(
            call_id=call_id,
            tool_name=tool_name,
            parts=parts,
            status=status,
            label=label,
        )


Message = SystemMessage | UserMessage | AssistantMessage | ToolResultMessage


@dataclass(frozen=True)
class MessageStack:
    """An ordered stack of model messages."""

    messages: tuple[Message, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        try:
            messages = tuple(self.messages)
        except TypeError as exc:
            raise LLMContractError(
                "MessageStack.messages must be an iterable of TinySoul message values"
            ) from exc
        for message in messages:
            if not isinstance(
                message,
                (SystemMessage, UserMessage, AssistantMessage, ToolResultMessage),
            ):
                raise LLMContractError(
                    "MessageStack.messages must contain TinySoul message values"
                )
        object.__setattr__(self, "messages", messages)

    def append(self, message: Message) -> "MessageStack":
        return MessageStack(messages=(*self.messages, message))

    @classmethod
    def of(cls, *messages: Message) -> "MessageStack":
        return cls(messages=tuple(messages))


def _reasoning(value: str | Reasoning | None) -> Reasoning | None:
    if value is None or isinstance(value, Reasoning):
        return value
    return Reasoning.text(value)


def _json_object(value: object, *, field: str) -> JsonObject:
    try:
        return to_json_object(value)
    except JsonTypeError as exc:
        raise LLMContractError(f"{field} must be a JSON object") from exc


def _json_part(value: object, *, field: str) -> JsonPart:
    return JsonPart(_json_object(value, field=field))


def _message_parts(
    value: tuple[MessagePart, ...],
    *,
    field: str,
) -> tuple[MessagePart, ...]:
    try:
        parts = tuple(value)
    except TypeError as exc:
        raise LLMContractError(f"{field} must be an iterable of message parts") from exc
    for part in parts:
        if not isinstance(part, _MESSAGE_PART_TYPES):
            raise LLMContractError(f"{field} must contain message parts")
    return parts


def _tool_calls(
    value: tuple[ToolCallRecord, ...],
    *,
    field: str,
) -> tuple[ToolCallRecord, ...]:
    try:
        tool_calls = tuple(value)
    except TypeError as exc:
        raise LLMContractError(
            f"{field} must be an iterable of ToolCallRecord values"
        ) from exc
    for tool_call in tool_calls:
        if not isinstance(tool_call, ToolCallRecord):
            raise LLMContractError(f"{field} must contain ToolCallRecord values")
    return tool_calls


def _require_label(value: str, *, field: str) -> None:
    if not isinstance(value, str):
        raise LLMContractError(f"{field} must be a string")
