"""Task prompt overlay model and rendering."""

from __future__ import annotations

from dataclasses import dataclass, field

from tinysoul.llm.messages import Message, UserMessage

from .errors import ContextInvariantError


@dataclass(frozen=True)
class PromptBlock:
    """One user-role task prompt message block."""

    label: str
    message: UserMessage

    def __post_init__(self) -> None:
        if not self.label:
            raise ContextInvariantError("PromptBlock.label must be non-empty")
        if not isinstance(self.message, UserMessage):
            raise ContextInvariantError("PromptBlock.message must be a UserMessage")
        if not self.message.parts:
            raise ContextInvariantError("PromptBlock.message must contain content")

    @classmethod
    def from_text(cls, label: str, text: str) -> "PromptBlock":
        if not text:
            raise ContextInvariantError("PromptBlock text must be non-empty")
        return cls(label=label, message=UserMessage.from_text(text, label=label))


@dataclass(frozen=True)
class TaskPrompt:
    """A per-task prompt overlay appended after the shared context sections."""

    guide: str
    task_input: str = ""
    output_desc: str = ""
    domain_guidance: tuple[str, ...] = field(default_factory=tuple)
    task_inputs: tuple[PromptBlock, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.guide:
            raise ContextInvariantError("TaskPrompt.guide must be non-empty")
        for item in self.domain_guidance:
            if not item:
                raise ContextInvariantError(
                    "TaskPrompt.domain_guidance must contain non-empty strings"
                )
        for item in self.task_inputs:
            if not isinstance(item, PromptBlock):
                raise ContextInvariantError(
                    "TaskPrompt.task_inputs must contain PromptBlock values"
                )

    def render_messages(self) -> tuple[Message, ...]:
        messages: list[Message] = [
            PromptBlock.from_text("task_prompt:guide", f"# Task Guide\n{self.guide}").message
        ]
        for item in self.domain_guidance:
            messages.append(
                PromptBlock.from_text(
                    "task_prompt:domain_guidance",
                    f"# Domain Guidance\n{item}",
                ).message
            )
        if self.task_input:
            messages.append(
                PromptBlock.from_text(
                    "task_prompt:input",
                    f"# Task Input\n{self.task_input}",
                ).message
            )
        messages.extend(item.message for item in self.task_inputs)
        if self.output_desc:
            messages.append(
                PromptBlock.from_text(
                    "task_prompt:output",
                    f"# Expected Output\n{self.output_desc}",
                ).message
            )
        return tuple(messages)
