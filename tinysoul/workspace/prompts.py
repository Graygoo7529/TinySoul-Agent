"""Workspace prompt reference integration."""

from __future__ import annotations

from tinysoul.context import PromptBlock, PromptReferenceError, PromptReferenceResolver
from tinysoul.infra.json import JsonObject

from .engine import WorkspaceEngine, WorkspacePromptInput, WorkspaceTextSlice
from .errors import WorkspaceError


WORKSPACE_TEXT_REFERENCE = "workspace.text"
WORKSPACE_TARGET_REFERENCE = "workspace.target"


class WorkspacePromptReferenceResolver(PromptReferenceResolver):
    """Resolve workspace text references into task prompt blocks."""

    def __init__(self, workspace: WorkspaceEngine) -> None:
        self._workspace = workspace

    def supports(self, kind: str) -> bool:
        return kind in {WORKSPACE_TEXT_REFERENCE, WORKSPACE_TARGET_REFERENCE}

    def resolve(self, reference: JsonObject) -> tuple[PromptBlock, ...]:
        kind = reference.get("type")
        if not isinstance(kind, str) or not self.supports(kind):
            raise PromptReferenceError(
                "Workspace reference requires a supported type.",
                reason="unsupported_workspace_reference",
            )
        link = reference.get("link")
        if not isinstance(link, str) or not link:
            raise PromptReferenceError(
                f"{kind} reference requires a non-empty link.",
                reason="missing_workspace_link",
            )
        max_chars = _optional_positive_int(reference, "max_chars")
        start_line = _optional_positive_int(reference, "start_line")
        max_lines = _optional_positive_int(reference, "max_lines")
        try:
            if start_line is not None or max_lines is not None:
                text_slice = self._workspace.read_text_slice(
                    link,
                    start_line=start_line or 1,
                    max_lines=max_lines,
                    max_chars=max_chars,
                )
                return (_block_from_slice(text_slice, kind=kind),)
            prompt_input = self._workspace.prepare_task_input(
                (link,),
                max_chars_per_resource=max_chars,
            )
            return prompt_blocks_from_workspace_input(prompt_input, kind=kind)
        except WorkspaceError as exc:
            raise PromptReferenceError(
                f"Workspace reference failed: {exc}",
                reason="workspace_reference_failed",
                payload={"error_type": type(exc).__name__, "link": link},
            ) from exc


def prompt_blocks_from_workspace_input(
    prompt_input: WorkspacePromptInput,
    *,
    kind: str = WORKSPACE_TEXT_REFERENCE,
) -> tuple[PromptBlock, ...]:
    """Convert prepared workspace prompt input into prompt blocks."""

    return tuple(
        _block_from_slice(text_slice, kind=kind)
        for text_slice in prompt_input.slices
    )


def _block_from_slice(text_slice: WorkspaceTextSlice, *, kind: str) -> PromptBlock:
    role = "target" if kind == WORKSPACE_TARGET_REFERENCE else "reference"
    return PromptBlock.from_text(
        f"task_prompt:input:workspace:{role}:{text_slice.link}:{text_slice.range_label}",
        _render_slice(text_slice, kind=kind),
    )


def _render_slice(text_slice: WorkspaceTextSlice, *, kind: str) -> str:
    truncated = "true" if text_slice.truncated else "false"
    heading = (
        "# Workspace Target"
        if kind == WORKSPACE_TARGET_REFERENCE
        else "# Workspace Reference"
    )
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


def _optional_positive_int(reference: JsonObject, key: str) -> int | None:
    value = reference.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PromptReferenceError(
            f"workspace.text reference {key} must be a positive integer.",
            reason=f"invalid_{key}",
        )
    return value
