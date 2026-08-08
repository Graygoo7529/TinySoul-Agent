"""Phase task prompt construction."""

from __future__ import annotations

from typing import Protocol

from tinysoul.context import PromptBlock, TaskPrompt


class DomainSkillProvider(Protocol):
    """Provide domain-level skills for Phase2 task prompts."""

    def guidance_for(self, domains: tuple[str, ...]) -> tuple[str, ...]:
        """Return guidance snippets for selected domains."""
        ...


class EmptyDomainSkillProvider:
    """Empty domain skill provider used before Agent Home is connected."""

    def guidance_for(self, domains: tuple[str, ...]) -> tuple[str, ...]:
        return ()


def phase1_task_prompt(
    *,
    domain_prompt: str,
    feedback: tuple[str, ...] = (),
    turn_guidance: tuple[str, ...] = (),
) -> TaskPrompt:
    sections = [
        "You are in TinySoul Phase1.",
        (
            "Before selecting action domains, reconcile existing WorkingContext "
            "milestones and todos with authoritative ActionResults already visible "
            "in the current Context."
        ),
        (
            "When real task state changed, call the relevant set/remove milestone "
            "or todo control tools in this same Phase1 "
            "response; do not leave completed work pending or in_progress, and do "
            "not mark a failed or merely attempted action done."
        ),
        (
            "Treat milestones as concise factual register entries that remain useful "
            "for later cycles. Record valuable completed work, attempts, failures, "
            "blocked conditions, concrete links, versions, values, decisions, or "
            "digests with their status made explicit. Do not use a milestone as a "
            "todo mirror or describe an attempt as completed work."
        ),
        (
            "Useful milestone examples: a computed value such as an average, a "
            "workspace document Link with its current section and digest, an "
            "authoritative URL used for the task, or a write attempt that failed "
            "at a known boundary and was changed to a patch workflow."
        ),
        (
            "Selecting core does not require every current-goal todo to be done or "
            "cancelled. When core.answer requests user input, unresolved todos may "
            "remain pending or in_progress; keep their status honest."
        ),
        "The action domain selection is mandatory for this phase.",
        "Phase1 does not complete the Turn or produce final user output. "
        "It only updates Context and selects action domains.",
    ]
    sections.extend(turn_guidance)
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
                    "Call the relevant set/remove milestone or todo control tools in "
                    "the same response whenever existing task state needs "
                    "reconciliation; other context control tools remain optional. "
                    "The domain selection call must be present before this phase "
                    "can complete."
                ),
            ),
        ),
    )


def phase2_task_prompt(
    *,
    selected_domains: tuple[str, ...],
    domain_skills: tuple[str, ...] = (),
    feedback: tuple[str, ...] = (),
    turn_guidance: tuple[str, ...] = (),
) -> TaskPrompt:
    sections = [
        "You are in TinySoul Phase2.",
        "Generate concrete action tool calls for the selected domains.",
        "Only call actions that are useful for the current cycle.",
    ]
    sections.extend(turn_guidance)
    if feedback:
        sections.append("Previous attempt feedback:\n" + "\n".join(f"- {item}" for item in feedback))
    guide_blocks = [
        PromptBlock.from_text(
            "task_prompt:guide:phase2",
            "# Task Guide\n" + "\n".join(sections),
        )
    ]
    for index, skill in enumerate(domain_skills, start=1):
        guide_blocks.append(
            PromptBlock.from_text(
                f"task_prompt:guide:domain_skill:{index}",
                "# Domain Skill\n" + skill,
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
