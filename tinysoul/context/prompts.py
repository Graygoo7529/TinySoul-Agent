"""Task prompt overlay model and rendering."""

from __future__ import annotations

from dataclasses import dataclass, field

from tinysoul.llm.messages import Message, UserMessage

from .errors import ContextInvariantError


@dataclass(frozen=True)
class TaskPrompt:
    """A per-task prompt overlay appended after the shared context sections."""

    guide: str
    task_input: str = ""
    output_desc: str = ""
    domain_guidance: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.guide:
            raise ContextInvariantError("TaskPrompt.guide must be non-empty")
        for item in self.domain_guidance:
            if not item:
                raise ContextInvariantError(
                    "TaskPrompt.domain_guidance must contain non-empty strings"
                )

    def render_messages(self) -> tuple[Message, ...]:
        sections = [f"# Task Guide\n{self.guide}"]
        if self.task_input:
            sections.append(f"# Task Input\n{self.task_input}")
        if self.output_desc:
            sections.append(f"# Expected Output\n{self.output_desc}")
        if self.domain_guidance:
            guidance = "\n\n".join(self.domain_guidance)
            sections.append(f"# Domain Guidance\n{guidance}")
        return (UserMessage.from_text("\n\n".join(sections), label="task_prompt"),)
