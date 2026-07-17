"""Prompt construction for agent-authored Script resources."""

from __future__ import annotations

from tinysoul.context import PromptBlock, PromptReferenceError, TaskPrompt
from tinysoul.workspace import WorkspacePromptReferenceResolver

from .models import ScriptSource


class ScriptEditPromptBuilder:
    """Build bounded write and rewrite prompts for Script source files."""

    def __init__(self, references: WorkspacePromptReferenceResolver) -> None:
        self._references = references

    def build_write(
        self,
        *,
        target_link: str,
        instruction: str,
        reference_links: tuple[str, ...],
        existing: ScriptSource | None,
    ) -> TaskPrompt:
        target_blocks: tuple[PromptBlock, ...] = ()
        if existing is not None:
            target_blocks = (self._source_block(existing, role="existing target"),)
        return TaskPrompt(
            guide_blocks=(
                PromptBlock.from_text(
                    "task_prompt:guide:script_write",
                    "# Task Guide\n"
                    "Write a complete executable script for the requested target. "
                    "The script must treat TINYSOUL_WORKSPACE and its current working "
                    "directory as the only intended data workspace. Return the complete "
                    "source, not a patch or Markdown fence.",
                ),
            ),
            input_blocks=(
                PromptBlock.from_text(
                    "task_prompt:input:script_instruction",
                    "# Script Instruction\n" + instruction,
                ),
                PromptBlock.from_text(
                    "task_prompt:input:script_target",
                    "# Script Target\nlink: " + target_link,
                ),
                *target_blocks,
                *self._reference_blocks(reference_links),
            ),
            output_blocks=(
                PromptBlock.from_text(
                    "task_prompt:output:script_source",
                    "# Expected Output\n"
                    "Return a JSON object with one string field named 'text'.",
                ),
            ),
        )

    def build_rewrite(
        self,
        *,
        source: ScriptSource,
        instruction: str,
        reference_links: tuple[str, ...],
    ) -> TaskPrompt:
        return TaskPrompt(
            guide_blocks=(
                PromptBlock.from_text(
                    "task_prompt:guide:script_rewrite",
                    "# Task Guide\n"
                    "Rewrite the complete executable script according to the instruction. "
                    "Preserve the workspace boundary: the script must treat "
                    "TINYSOUL_WORKSPACE and its current working directory as the only "
                    "intended data workspace. Return the complete replacement source.",
                ),
            ),
            input_blocks=(
                PromptBlock.from_text(
                    "task_prompt:input:script_instruction",
                    "# Rewrite Instruction\n" + instruction,
                ),
                self._source_block(source, role="rewrite target"),
                *self._reference_blocks(reference_links),
            ),
            output_blocks=(
                PromptBlock.from_text(
                    "task_prompt:output:script_source",
                    "# Expected Output\n"
                    "Return a JSON object with one string field named 'text'.",
                ),
            ),
        )

    def _reference_blocks(self, links: tuple[str, ...]) -> tuple[PromptBlock, ...]:
        blocks: list[PromptBlock] = []
        for link in links:
            if not self._references.supports(link):
                raise PromptReferenceError(
                    f"Script reference must be a Workspace Link: {link}",
                    reason="unsupported_script_reference",
                    payload={"link": link},
                )
            blocks.extend(self._references.resolve_reference(link))
        return tuple(blocks)

    @staticmethod
    def _source_block(source: ScriptSource, *, role: str) -> PromptBlock:
        return PromptBlock.from_text(
            f"task_prompt:input:script:{source.link}",
            "# Script Source\n"
            f"role: {role}\n"
            f"link: {source.link}\n"
            f"digest: {source.digest}\n"
            "source:\n"
            + source.text,
        )
