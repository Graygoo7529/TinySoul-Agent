"""Workspace prompt reference integration."""

from __future__ import annotations

from tinysoul.context import PromptBlock, PromptReferenceError, PromptReferenceResolver

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
