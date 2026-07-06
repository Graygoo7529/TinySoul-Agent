"""Constructive message stack composition."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.infra.json import dumps_json
from tinysoul.llm.messages import (
    JsonPart,
    Message,
    MessageStack,
    SystemMessage,
    TextPart,
)

from .background import BackgroundContext
from .errors import ContextBudgetError, ContextInvariantError
from .prompts import TaskPrompt
from .trace import TurnTraceContext
from .working import WorkingContext


@dataclass(frozen=True)
class ContextBudget:
    """Character budget for one composed message stack."""

    max_chars: int | None = None

    def __post_init__(self) -> None:
        if self.max_chars is not None and self.max_chars <= 0:
            raise ContextInvariantError("ContextBudget.max_chars must be positive")


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
        background: BackgroundContext,
        working: WorkingContext,
        trace: TurnTraceContext,
        task_prompt: TaskPrompt,
    ) -> MessageStack:
        messages: tuple[Message, ...] = (
            SystemMessage.from_text(self._system_text, label="identity"),
            *background.render_messages(),
            *working.render_messages(),
            *trace.render_messages(),
            *task_prompt.render_messages(),
        )
        estimated = estimate_chars(messages)
        max_chars = self._budget.max_chars
        if max_chars is not None and estimated > max_chars:
            raise ContextBudgetError(
                "Composed message stack exceeds the context budget",
                estimated_chars=estimated,
                max_chars=max_chars,
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
    return total
