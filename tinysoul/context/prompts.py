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
    """A per-task prompt overlay appended after shared context sections."""

    guide_blocks: tuple[PromptBlock, ...]
    input_blocks: tuple[PromptBlock, ...] = field(default_factory=tuple)
    output_blocks: tuple[PromptBlock, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _check_blocks(self.guide_blocks, "TaskPrompt.guide_blocks")
        _check_blocks(self.input_blocks, "TaskPrompt.input_blocks")
        _check_blocks(self.output_blocks, "TaskPrompt.output_blocks")
        if not self.guide_blocks:
            raise ContextInvariantError(
                "TaskPrompt.guide_blocks must contain at least one block"
            )

    def render_messages(self) -> tuple[Message, ...]:
        return tuple(
            block.message
            for block in (
                *self.guide_blocks,
                *self.input_blocks,
                *self.output_blocks,
            )
        )


def _check_blocks(blocks: tuple[PromptBlock, ...], field: str) -> None:
    for block in blocks:
        if not isinstance(block, PromptBlock):
            raise ContextInvariantError(f"{field} must contain PromptBlock values")
