"""Workspace prompt reference integration."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.context import (
    PromptBlock,
    PromptReferenceError,
    PromptReferenceResolver,
    TaskPrompt,
)

from .engine import WorkspaceEngine, WorkspacePromptInput, WorkspaceTextSlice
from .errors import WorkspaceError
from .links import WORKSPACE_LINK_PREFIX


class WorkspacePromptReferenceResolver(PromptReferenceResolver):
    """Resolve workspace links into task prompt blocks."""

    def __init__(self, workspace: WorkspaceEngine) -> None:
        self._workspace = workspace

    def supports(self, link: str) -> bool:
        return isinstance(link, str) and link.startswith(WORKSPACE_LINK_PREFIX)

    def resolve_reference(self, link: str) -> tuple[PromptBlock, ...]:
        """Resolve a workspace link as read-only prompt input."""

        return self._resolve(link, role="reference")

    def resolve_target(self, link: str) -> tuple[PromptBlock, ...]:
        """Resolve a workspace link as the target of a workspace action."""

        return self._resolve(link, role="target")

    def _resolve(self, link: str, *, role: str) -> tuple[PromptBlock, ...]:
        if not isinstance(link, str) or not link:
            raise PromptReferenceError(
                "Workspace prompt reference requires a non-empty link.",
                reason="missing_workspace_link",
            )
        if not self.supports(link):
            raise PromptReferenceError(
                "Workspace prompt reference requires a workspace link.",
                reason="unsupported_workspace_link",
                payload={"link": link},
            )
        try:
            prompt_input = self._workspace.prepare_task_input((link,))
            return prompt_blocks_from_workspace_input(prompt_input, role=role)
        except WorkspaceError as exc:
            raise PromptReferenceError(
                f"Workspace prompt reference failed: {exc}",
                reason="workspace_reference_failed",
                payload={"error_type": type(exc).__name__, "link": link},
            ) from exc


@dataclass(frozen=True)
class WorkspaceEditPrompt:
    """One workspace edit task prompt and the target state it was built from."""

    prompt: TaskPrompt
    target_digest: str = ""


class WorkspaceEditPromptBuilder:
    """Build write and rewrite prompts from workspace resource links."""

    def __init__(self, workspace: WorkspaceEngine) -> None:
        self._workspace = workspace
        self._resolver = WorkspacePromptReferenceResolver(workspace)

    def build_write(
        self,
        *,
        target_link: str,
        instruction: str,
        reference_links: tuple[str, ...],
        include_target: bool,
        overwrite: bool,
    ) -> WorkspaceEditPrompt:
        target_blocks: tuple[PromptBlock, ...] = ()
        target_digest = ""
        if include_target:
            target_input = self._workspace.prepare_task_input((target_link,))
            target_digest = target_input.slices[0].digest
            target_blocks = prompt_blocks_from_workspace_input(
                target_input,
                role="target",
            )
        overwrite_text = "true" if overwrite else "false"
        return WorkspaceEditPrompt(
            prompt=TaskPrompt(
                guide_blocks=(
                    PromptBlock.from_text(
                        "task_prompt:guide:workspace_write",
                        (
                            "# Task Guide\n"
                            "Generate the complete UTF-8 text for the workspace target. "
                            "Return only the full text that should be written."
                        ),
                    ),
                ),
                input_blocks=(
                    PromptBlock.from_text(
                        "task_prompt:input:workspace_write_instruction",
                        "# Write Instruction\n" + instruction,
                    ),
                    PromptBlock.from_text(
                        "task_prompt:input:workspace_write_target",
                        (
                            "# Workspace Write Target\n"
                            f"link: {target_link}\n"
                            f"overwrite: {overwrite_text}"
                        ),
                    ),
                    *target_blocks,
                    *self._reference_blocks(reference_links),
                ),
                output_blocks=(
                    PromptBlock.from_text(
                        "task_prompt:output:workspace_write",
                        "# Expected Output\nReturn a JSON object with a string field 'text'.",
                    ),
                ),
            ),
            target_digest=target_digest,
        )

    def build_rewrite(
        self,
        *,
        target_link: str,
        instruction: str,
        reference_links: tuple[str, ...],
    ) -> WorkspaceEditPrompt:
        target_input = self._workspace.prepare_task_input((target_link,))
        target_blocks = prompt_blocks_from_workspace_input(
            target_input,
            role="target",
        )
        return WorkspaceEditPrompt(
            prompt=TaskPrompt(
                guide_blocks=(
                    PromptBlock.from_text(
                        "task_prompt:guide:workspace_rewrite",
                        (
                            "# Task Guide\n"
                            "Rewrite the workspace target according to the instruction. "
                            "Return the complete replacement text for the target resource."
                        ),
                    ),
                ),
                input_blocks=(
                    PromptBlock.from_text(
                        "task_prompt:input:workspace_rewrite_instruction",
                        "# Rewrite Instruction\n" + instruction,
                    ),
                    *target_blocks,
                    *self._reference_blocks(reference_links),
                ),
                output_blocks=(
                    PromptBlock.from_text(
                        "task_prompt:output:workspace_rewrite",
                        "# Expected Output\nReturn a JSON object with a string field 'text'.",
                    ),
                ),
            ),
            target_digest=target_input.slices[0].digest,
        )

    def _reference_blocks(
        self,
        links: tuple[str, ...],
    ) -> tuple[PromptBlock, ...]:
        blocks: list[PromptBlock] = []
        for link in links:
            if not self._resolver.supports(link):
                raise PromptReferenceError(
                    f"Unsupported workspace reference link: {link}",
                    reason="unsupported_reference_link",
                    payload={"link": link},
                )
            blocks.extend(self._resolver.resolve_reference(link))
        return tuple(blocks)


def prompt_blocks_from_workspace_input(
    prompt_input: WorkspacePromptInput,
    *,
    role: str = "reference",
) -> tuple[PromptBlock, ...]:
    """Convert prepared workspace prompt input into prompt blocks."""

    return tuple(
        _block_from_slice(text_slice, role=role)
        for text_slice in prompt_input.slices
    )


def _block_from_slice(text_slice: WorkspaceTextSlice, *, role: str) -> PromptBlock:
    label_role = "target" if role == "target" else "reference"
    return PromptBlock.from_text(
        f"task_prompt:input:workspace:{label_role}:{text_slice.link}:{text_slice.range_label}",
        _render_slice(text_slice, role=label_role),
    )


def _render_slice(text_slice: WorkspaceTextSlice, *, role: str) -> str:
    truncated = "true" if text_slice.truncated else "false"
    heading = "# Workspace Target" if role == "target" else "# Workspace Reference"
    lines = [
        heading,
        f"link: {text_slice.link}",
        f"range: {text_slice.range_label}",
        f"size: {text_slice.size} bytes",
        f"digest: {text_slice.digest}",
        f"truncated: {truncated}",
        "",
        text_slice.text,
    ]
    return "\n".join(lines)
