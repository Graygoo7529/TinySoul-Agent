"""Phase task prompt construction."""

from __future__ import annotations

from typing import Protocol

from tinysoul.context import PromptBlock, TaskPrompt


class DomainHowProvider(Protocol):
    """Provide domain-level HOW for Phase2 task prompts."""

    def guidance_for(self, domains: tuple[str, ...]) -> tuple[str, ...]:
        """Return guidance snippets for selected domains."""
        ...


class EmptyDomainHowProvider:
    """Domain HOW provider used before Agent Home HOW is connected."""

    def guidance_for(self, domains: tuple[str, ...]) -> tuple[str, ...]:
        return ()


def phase1_task_prompt(
    *,
    domain_prompt: str,
    feedback: tuple[str, ...] = (),
) -> TaskPrompt:
    sections = [
        "You are in TinySoul Phase1.",
        "Update context only when useful, then select one or more action domains.",
        "The action domain selection is mandatory for this phase.",
    ]
    if feedback:
        sections.append("Previous attempt feedback:\n" + "\n".join(f"- {item}" for item in feedback))
    return TaskPrompt(
        guide_blocks=(
            PromptBlock.from_text(
                "task_prompt:guide:phase1",
                "# Task Guide\n" + "\n".join(sections),
            ),
        ),
        input_blocks=(
            PromptBlock.from_text(
                "task_prompt:input:action_domains",
                "# Task Input\n" + domain_prompt,
            ),
        ),
        output_blocks=(
            PromptBlock.from_text(
                "task_prompt:output:phase1",
                (
                    "# Expected Output\n"
                    "Call select_action_domains with at least one valid domain. "
                    "You may also call context control tools."
                ),
            ),
        ),
    )


def phase2_task_prompt(
    *,
    selected_domains: tuple[str, ...],
    domain_how: tuple[str, ...] = (),
    feedback: tuple[str, ...] = (),
) -> TaskPrompt:
    sections = [
        "You are in TinySoul Phase2.",
        "Generate concrete action tool calls for the selected domains.",
        "Only call actions that are useful for the current cycle.",
    ]
    if feedback:
        sections.append("Previous attempt feedback:\n" + "\n".join(f"- {item}" for item in feedback))
    guide_blocks = [
        PromptBlock.from_text(
            "task_prompt:guide:phase2",
            "# Task Guide\n" + "\n".join(sections),
        )
    ]
    for index, how in enumerate(domain_how, start=1):
        guide_blocks.append(
            PromptBlock.from_text(
                f"task_prompt:guide:domain_how:{index}",
                "# Domain HOW\n" + how,
            )
        )
    return TaskPrompt(
        guide_blocks=tuple(guide_blocks),
        input_blocks=(
            PromptBlock.from_text(
                "task_prompt:input:selected_domains",
                "# Task Input\nSelected domains: " + ", ".join(selected_domains),
            ),
        ),
        output_blocks=(
            PromptBlock.from_text(
                "task_prompt:output:phase2",
                "# Expected Output\nReturn one or more action tool calls with valid arguments.",
            ),
        ),
    )
