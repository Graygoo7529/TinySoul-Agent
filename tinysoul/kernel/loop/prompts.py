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
    return TaskPrompt(
        guide_blocks=(
            *_turn_guide_blocks(turn_guidance),
            PromptBlock.from_text(
                "task_prompt:guide:phase1",
                prompt_text.TASK_GUIDE_HEADING + "\n".join(prompt_text.PHASE1_GUIDANCE),
            ),
        ),
        input_blocks=(
            PromptBlock.from_text(
                "task_prompt:input:action_domains",
                prompt_text.TASK_INPUT_HEADING + domain_prompt,
            ),
            *_feedback_blocks(feedback),
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
    intent: str = "",
    domain_skills: tuple[PromptGuidance, ...] = (),
    feedback: tuple[str, ...] = (),
    turn_guidance: tuple[str, ...] = (),
) -> TaskPrompt:
    guide_blocks = [
        *_turn_guide_blocks(turn_guidance),
        PromptBlock.from_text(
            "task_prompt:guide:phase2",
            prompt_text.TASK_GUIDE_HEADING + "\n".join(prompt_text.PHASE2_GUIDANCE),
        ),
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
                prompt_text.phase2_input(domains=selected_domains, intent=intent),
            ),
            *_feedback_blocks(feedback),
        ),
        output_blocks=(
            PromptBlock.from_text(
                "task_prompt:output:phase2",
                prompt_text.PHASE2_EXPECTED_OUTPUT,
            ),
        ),
    )


def _turn_guide_blocks(guidance: tuple[str, ...]) -> tuple[PromptBlock, ...]:
    if not guidance:
        return ()
    return (
        PromptBlock.from_text(
            "task_prompt:guide:turn",
            prompt_text.TURN_GUIDANCE_HEADING
            + "\n".join((*guidance, prompt_text.TURN_GUIDANCE_SCOPE)),
        ),
    )


def _feedback_blocks(feedback: tuple[str, ...]) -> tuple[PromptBlock, ...]:
    if not feedback:
        return ()
    return (
        PromptBlock.from_text(
            "task_prompt:input:feedback",
            prompt_text.PREVIOUS_FEEDBACK_HEADING
            + "\n".join(f"- {item}" for item in feedback),
        ),
    )
