"""Constructive message stack composition."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from tinysoul.infra.json import JsonObject, dumps_json, to_json_object
from tinysoul.llm.messages import (
    AssistantMessage,
    ImagePart,
    JsonPart,
    Message,
    MessageStack,
    SystemMessage,
    TextPart,
    ToolResultMessage,
)

from .background import BackgroundContext
from .errors import ContextBudgetError, ContextInvariantError
from .prompts import TaskPrompt
from .trace import PendingInputs, TurnTraceHeap
from .working import WorkingContext


@dataclass(frozen=True)
class ContextBudget:
    """Character budget for one composed message stack."""

    max_chars: int | None = None
    max_image_bytes: int | None = None

    def __post_init__(self) -> None:
        if self.max_chars is not None and self.max_chars <= 0:
            raise ContextInvariantError("ContextBudget.max_chars must be positive")
        if self.max_image_bytes is not None and self.max_image_bytes <= 0:
            raise ContextInvariantError(
                "ContextBudget.max_image_bytes must be positive"
            )


class ContextSection(StrEnum):
    """Stable sections used for budget diagnostics and recovery planning."""

    IDENTITY = "identity"
    USER_INPUTS = "user_inputs"
    SESSION_BACKGROUND = "session_background"
    BACKGROUND = "background"
    WORKING = "working"
    TRACE = "trace"
    TASK_PROMPT = "task_prompt"


@dataclass(frozen=True)
class ContextSectionUsage:
    chars: int
    image_bytes: int

    def to_json(self) -> dict[str, int]:
        return {"chars": self.chars, "image_bytes": self.image_bytes}


@dataclass(frozen=True)
class ContextBudgetReport:
    """Per-section usage for one attempted MessageStack composition."""

    sections: dict[ContextSection, ContextSectionUsage]
    total_chars: int
    total_image_bytes: int
    max_chars: int | None
    max_image_bytes: int | None

    @property
    def required_chars(self) -> int:
        if self.max_chars is None:
            return 0
        return max(0, self.total_chars - self.max_chars)

    def to_json(self) -> JsonObject:
        return to_json_object({
            "sections": {
                section.value: usage.to_json()
                for section, usage in self.sections.items()
            },
            "total_chars": self.total_chars,
            "total_image_bytes": self.total_image_bytes,
            "max_chars": self.max_chars,
            "max_image_bytes": self.max_image_bytes,
            "required_chars": self.required_chars,
        })


class MessageStackComposer:
    """Compose the full message stack from context sections plus a task prompt."""

    def __init__(self, *, system_text: str, budget: ContextBudget | None = None) -> None:
        if not system_text:
            raise ContextInvariantError("MessageStackComposer.system_text must be non-empty")
        self._system_text = system_text
        self._budget = budget or ContextBudget()

    @property
    def budget(self) -> ContextBudget:
        return self._budget

    def compose(
        self,
        *,
        inputs: PendingInputs,
        background: BackgroundContext,
        working: WorkingContext,
        trace: TurnTraceHeap,
        task_prompt: TaskPrompt,
    ) -> MessageStack:
        section_messages: dict[ContextSection, tuple[Message, ...]] = {
            ContextSection.IDENTITY: (
                SystemMessage.from_text(self._system_text, label="identity"),
            ),
            ContextSection.USER_INPUTS: inputs.render_messages(),
            ContextSection.SESSION_BACKGROUND: background.render_session_messages(),
            ContextSection.BACKGROUND: background.render_background_messages(),
            ContextSection.WORKING: working.render_messages(),
            ContextSection.TRACE: trace.render_messages(),
            ContextSection.TASK_PROMPT: task_prompt.render_messages(),
        }
        messages = tuple(
            message
            for section in ContextSection
            for message in section_messages[section]
        )
        report = ContextBudgetReport(
            sections={
                section: ContextSectionUsage(
                    chars=estimate_chars(section_messages[section]),
                    image_bytes=estimate_image_bytes(section_messages[section]),
                )
                for section in ContextSection
            },
            total_chars=estimate_chars(messages),
            total_image_bytes=estimate_image_bytes(messages),
            max_chars=self._budget.max_chars,
            max_image_bytes=self._budget.max_image_bytes,
        )
        estimated = report.total_chars
        max_chars = self._budget.max_chars
        if max_chars is not None and estimated > max_chars:
            raise ContextBudgetError(
                "Composed message stack exceeds the context budget",
                estimated_chars=estimated,
                max_chars=max_chars,
                estimated_image_bytes=report.total_image_bytes,
                max_image_bytes=report.max_image_bytes,
                section_usage=report.to_json(),
            )
        estimated_image_bytes = report.total_image_bytes
        max_image_bytes = self._budget.max_image_bytes
        if (
            max_image_bytes is not None
            and estimated_image_bytes > max_image_bytes
        ):
            raise ContextBudgetError(
                "Composed message stack exceeds the image byte budget",
                estimated_chars=estimated,
                max_chars=max_chars,
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
