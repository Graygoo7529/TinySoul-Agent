"""Phase task prompt construction."""

from __future__ import annotations

from typing import Protocol

from tinysoul.context import TaskPrompt


class DomainGuidanceProvider(Protocol):
    """Provide domain-level guidance for Phase2 task prompts."""

    def guidance_for(self, domains: tuple[str, ...]) -> tuple[str, ...]:
        """Return guidance snippets for selected domains."""
        ...


class EmptyDomainGuidanceProvider:
    """Domain guidance provider used before Agent Home HOW is connected."""

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
        guide="\n".join(sections),
        task_input=domain_prompt,
        output_desc=(
            "Call select_action_domains with at least one valid domain. "
            "You may also call context control tools."
        ),
    )


def phase2_task_prompt(
    *,
    selected_domains: tuple[str, ...],
    domain_guidance: tuple[str, ...] = (),
    feedback: tuple[str, ...] = (),
) -> TaskPrompt:
    sections = [
        "You are in TinySoul Phase2.",
        "Generate concrete action tool calls for the selected domains.",
        "Only call actions that are useful for the current cycle.",
    ]
    if feedback:
        sections.append("Previous attempt feedback:\n" + "\n".join(f"- {item}" for item in feedback))
    return TaskPrompt(
        guide="\n".join(sections),
        task_input="Selected domains: " + ", ".join(selected_domains),
        output_desc="Return one or more action tool calls with valid arguments.",
        domain_guidance=domain_guidance,
    )
