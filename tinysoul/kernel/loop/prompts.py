"""Phase task prompt construction."""

from __future__ import annotations

from typing import Protocol

from tinysoul.prompts.kernel import loop as prompt_text
from tinysoul.kernel.context import PromptBlock, TaskPrompt
from tinysoul.kernel.context.prompts import PromptGuidance


class DomainSkillProvider(Protocol):
    """Provide domain-level skills for Phase2 task prompts."""

    async def guidance_for(
        self, domains: tuple[str, ...]
    ) -> tuple[PromptGuidance, ...]:
        """Return guidance snippets for selected domains."""
        ...


class EmptyDomainSkillProvider:
    """Empty domain skill provider used before Agent Home is connected."""

    async def guidance_for(
        self, domains: tuple[str, ...]
    ) -> tuple[PromptGuidance, ...]:
        return ()


def phase1_task_prompt(
    *,
    domain_prompt: str,
    feedback: tuple[str, ...] = (),
    turn_guidance: tuple[str, ...] = (),
) -> TaskPrompt:
    sections = list(prompt_text.PHASE1_GUIDANCE)
    sections.extend(turn_guidance)
    if feedback:
        sections.append(
            prompt_text.PREVIOUS_FEEDBACK_HEADING
            + "\n".join(f"- {item}" for item in feedback)
        )
    return TaskPrompt(
        guide_blocks=(
            PromptBlock.from_text(
                "task_prompt:guide:phase1",
                prompt_text.TASK_GUIDE_HEADING + "\n".join(sections),
            ),
        ),
        input_blocks=(
            PromptBlock.from_text(
                "task_prompt:input:action_domains",
                prompt_text.TASK_INPUT_HEADING + domain_prompt,
            ),
        ),
        output_blocks=(
            PromptBlock.from_text(
                "task_prompt:output:phase1",
                (prompt_text.PHASE1_EXPECTED_OUTPUT),
            ),
        ),
    )


def phase2_task_prompt(
    *,
    selected_domains: tuple[str, ...],
    domain_skills: tuple[PromptGuidance, ...] = (),
    feedback: tuple[str, ...] = (),
    turn_guidance: tuple[str, ...] = (),
) -> TaskPrompt:
    sections = list(prompt_text.PHASE2_GUIDANCE)
    sections.extend(turn_guidance)
    if feedback:
        sections.append(
            prompt_text.PREVIOUS_FEEDBACK_HEADING
            + "\n".join(f"- {item}" for item in feedback)
        )
    guide_blocks = [
        PromptBlock.from_text(
            "task_prompt:guide:phase2",
            prompt_text.TASK_GUIDE_HEADING + "\n".join(sections),
        )
    ]
    for index, skill in enumerate(domain_skills, start=1):
        guide_blocks.append(
            PromptBlock.from_text(
                f"task_prompt:guide:domain_skill:{index}",
                prompt_text.DOMAIN_SKILL_HEADING + skill.text,
                owner=skill.owner,
                refs=(skill.reference,),
            )
        )
    return TaskPrompt(
        guide_blocks=tuple(guide_blocks),
        input_blocks=(
            PromptBlock.from_text(
                "task_prompt:input:selected_domains",
                prompt_text.SELECTED_DOMAINS_HEADING + ", ".join(selected_domains),
            ),
        ),
        output_blocks=(
            PromptBlock.from_text(
                "task_prompt:output:phase2",
                prompt_text.PHASE2_EXPECTED_OUTPUT,
            ),
        ),
    )
