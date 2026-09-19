"""Constructive message stack composition."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.infra.json import JsonObject, dumps_json, to_json_object
from tinysoul.llm.protocol.messages import (
    AssistantMessage,
    ImagePart,
    JsonPart,
    Message,
    MessageStack,
    TextPart,
    ToolResultMessage,
)

from ..errors import ContextBudgetError, ContextInvariantError
from ..prompts import TaskPrompt
from ..segments import SegmentProjection


@dataclass(frozen=True)
class ContextBudget:
    """Non-token hard limits for one composed message stack."""

    max_image_bytes: int | None = None

    def __post_init__(self) -> None:
        if self.max_image_bytes is not None and self.max_image_bytes <= 0:
            raise ContextInvariantError(
                "ContextBudget.max_image_bytes must be positive"
            )


@dataclass(frozen=True)
class ContextSectionUsage:
    chars: int
    image_bytes: int

    def to_json(self) -> dict[str, int]:
        return {"chars": self.chars, "image_bytes": self.image_bytes}


@dataclass(frozen=True)
class ContextBudgetReport:
    """Per-section usage for one attempted MessageStack composition."""

    sections: dict[str, ContextSectionUsage]
    total_chars: int
    total_image_bytes: int
    max_image_bytes: int | None

    def to_json(self) -> JsonObject:
        return to_json_object(
            {
                "sections": {
                    section: usage.to_json() for section, usage in self.sections.items()
                },
                "total_chars": self.total_chars,
                "total_image_bytes": self.total_image_bytes,
                "max_image_bytes": self.max_image_bytes,
            }
        )


class MessageStackComposer:
    """Compose the full message stack from context sections plus a task prompt."""

    def __init__(self, *, budget: ContextBudget | None = None) -> None:
        self._budget = budget or ContextBudget()

    @property
    def budget(self) -> ContextBudget:
        return self._budget

    def compose(
        self,
        *,
        segments: tuple[SegmentProjection, ...],
        task_prompt: TaskPrompt,
    ) -> MessageStack:
        ids = tuple(segment.descriptor.id for segment in segments)
        if len(ids) != len(set(ids)) or "task_prompt" in ids:
            raise ContextInvariantError(
                "Context projection ids must be unique and exclude task_prompt"
            )
        ordered = sorted(
            segments,
            key=lambda item: item.descriptor.sort_key,
        )
        section_messages = {item.descriptor.id: item.messages for item in ordered}
        section_messages["task_prompt"] = task_prompt.render_messages()
        messages = tuple(
            message for section in section_messages.values() for message in section
        )
        report = ContextBudgetReport(
            sections={
                section: ContextSectionUsage(
                    chars=estimate_chars(value),
                    image_bytes=estimate_image_bytes(value),
                )
                for section, value in section_messages.items()
            },
            total_chars=estimate_chars(messages),
            total_image_bytes=estimate_image_bytes(messages),
            max_image_bytes=self._budget.max_image_bytes,
        )
        estimated = report.total_chars
        estimated_image_bytes = report.total_image_bytes
        max_image_bytes = self._budget.max_image_bytes
        if max_image_bytes is not None and estimated_image_bytes > max_image_bytes:
            raise ContextBudgetError(
                "Composed message stack exceeds the image byte budget",
                estimated_chars=estimated,
                estimated_image_bytes=estimated_image_bytes,
                max_image_bytes=max_image_bytes,
                section_usage=report.to_json(),
            )
        return MessageStack(messages=messages)


def estimate_chars(messages: tuple[Message, ...]) -> int:
    """Estimate the text size of a message sequence in characters."""

    total = 0
    for message in messages:
        for part in message.parts:
            if isinstance(part, TextPart):
                total += len(part.text)
            elif isinstance(part, JsonPart):
                total += len(dumps_json(part.value))
        if isinstance(message, AssistantMessage):
            for call in message.tool_calls:
                total += len(call.id) + len(call.name)
                total += len(dumps_json(call.arguments))
                if call.kind is not None:
                    total += len(call.kind.value)
            if message.reasoning is not None:
                reasoning = message.reasoning
                if reasoning.content is not None:
                    total += len(reasoning.content)
                if reasoning.summary is not None:
                    total += len(reasoning.summary)
                for item in reasoning.encrypted_items:
                    total += len(dumps_json(item))
        elif isinstance(message, ToolResultMessage):
            total += len(message.call_id)
            total += len(message.tool_name)
            total += len(message.status.value)
    return total


def estimate_image_bytes(messages: tuple[Message, ...]) -> int:
    """Return the total number of inline image bytes in a message sequence."""

    return sum(
        len(part.data)
        for message in messages
        for part in message.parts
        if isinstance(part, ImagePart)
    )
