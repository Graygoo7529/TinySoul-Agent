"""Workspace prompt reference integration."""

from __future__ import annotations

from tinysoul.prompts.plugins import workspace as prompt_text
from tinysoul.kernel.context import (
    PromptBlock,
    PromptReferenceError,
    PromptReferenceResolver,
    TaskPrompt,
)
from tinysoul.llm.protocol.messages import ImagePart, TextPart, UserMessage

from .inspection.models import (
    WorkspaceAnalysisInput,
    WorkspacePromptInput,
    WorkspaceTextSlice,
)
from .services import WorkspaceService
from .runtime_bridge import RuntimeWorkspaceBridge
from .errors import (
    WorkspaceError,
    WorkspaceImageValidationError,
    WorkspaceContractError,
)
from .refs import WORKSPACE_REF_PREFIX
from .storage.manifest import WorkspaceResourceKind


class WorkspaceAnalysisPromptBuilder:
    """Build one grounded read-only Workspace analysis task."""

    def build(
        self,
        *,
        intent: str,
        analysis_input: WorkspaceAnalysisInput,
        max_answer_chars: int,
    ) -> TaskPrompt:
        reference_blocks = tuple(
            PromptBlock.from_text(
                f"task_prompt:input:workspace:analysis:{reference.source_id}",
                "\n".join(
                    (
                        prompt_text.WORKSPACE_ANALYSIS_REFERENCE,
                        f"source_id: {reference.source_id}",
                        f"ref: {reference.ref}",
                        f"size: {reference.size} bytes",
                        f"range: lines:1-{reference.end_line}",
                        "complete: true",
                        "",
                        reference.text,
                    )
                ),
            )
            for reference in analysis_input.references
        )
        source_ids = ", ".join(
            reference.source_id for reference in analysis_input.references
        )
        return TaskPrompt(
            guide_blocks=(
                PromptBlock.from_text(
                    "task_prompt:guide:workspace:analyze",
                    prompt_text.ANALYSIS_GUIDE,
                ),
            ),
            input_blocks=(
                PromptBlock.from_text(
                    "task_prompt:input:workspace:analysis:intent",
                    prompt_text.analysis_intent(intent=intent),
                ),
                *reference_blocks,
            ),
            output_blocks=(
                PromptBlock.from_text(
                    "task_prompt:output:workspace:analysis",
                    prompt_text.analysis_expected_output(
                        max_answer_chars=max_answer_chars, source_ids=source_ids
                    ),
                ),
            ),
        )


class WorkspacePromptReferenceResolver(PromptReferenceResolver):
    """Resolve workspace refs into task prompt blocks."""

    def __init__(
        self,
        workspace: WorkspaceService,
        *,
        runtime_bridge: RuntimeWorkspaceBridge | None = None,
    ) -> None:
        self._workspace = workspace
        self._runtime_bridge = runtime_bridge

    def supports(self, ref: str) -> bool:
        return isinstance(ref, str) and ref.startswith(WORKSPACE_REF_PREFIX)

    async def resolve_reference(self, ref: str) -> tuple[PromptBlock, ...]:
        """Resolve a workspace ref as read-only prompt input."""

        return await self._resolve(ref, role="reference")

    async def resolve_target(self, ref: str) -> tuple[PromptBlock, ...]:
        """Resolve a workspace ref as the target of a workspace action."""

        return await self._resolve(ref, role="target")

    async def _resolve(self, ref: str, *, role: str) -> tuple[PromptBlock, ...]:
        if not isinstance(ref, str) or not ref:
            raise PromptReferenceError(
                prompt_text.REFERENCE_REF_REQUIRED,
                reason="missing_workspace_ref",
            )
        if not self.supports(ref):
            raise PromptReferenceError(
                prompt_text.WORKSPACE_REFERENCE_REQUIRED,
                reason="unsupported_workspace_ref",
                payload={"ref": ref},
            )
        try:
            record = await self._workspace.stat(ref)
            if record.kind is WorkspaceResourceKind.TEXT:
                prompt_input = await self._workspace.prepare_task_input((ref,))
                return prompt_blocks_from_workspace_input(prompt_input, role=role)
            if record.kind is WorkspaceResourceKind.IMAGE:
                image = await self._workspace.read_image(ref)
                label_role = "target" if role == "target" else "reference"
                heading = (
                    prompt_text.WORKSPACE_TARGET
                    if label_role == "target"
                    else prompt_text.WORKSPACE_REFERENCE
                )
                label = f"task_prompt:input:workspace:{label_role}:{image.ref}:image"
                metadata = "\n".join(
                    (
                        heading,
                        f"ref: {image.ref}",
                        f"media_type: {image.media_type}",
                        f"size: {image.size} bytes",
                    )
                )
                return (
                    PromptBlock(
                        label=label,
                        message=UserMessage.from_parts(
                            TextPart(metadata),
                            ImagePart(data=image.data, mime_type=image.media_type),
                            label=label,
                        ),
                    ),
                )
            if record.kind is WorkspaceResourceKind.DOCUMENT:
                raise PromptReferenceError(
                    prompt_text.reference_requires_conversion(ref=ref),
                    reason="conversion_required",
                    payload={
                        "ref": ref,
                        "kind": record.kind.value,
                        "media_type": record.media_type,
                    },
                )
            raise PromptReferenceError(
                prompt_text.unsupported_binary_reference(ref=ref),
                reason="unsupported_binary_resource",
                payload={
                    "ref": ref,
                    "kind": record.kind.value,
                    "media_type": record.media_type,
                },
            )
        except PromptReferenceError:
            raise
        except WorkspaceImageValidationError as exc:
            raise PromptReferenceError(
                prompt_text.invalid_image_reference(ref=ref),
                reason="invalid_image_resource",
                payload={"error_type": type(exc).__name__, "ref": ref},
            ) from exc
        except WorkspaceContractError as exc:
            raise PromptReferenceError(
                prompt_text.REFERENCE_UNAVAILABLE,
                reason="workspace_reference_failed",
                payload={"error_type": type(exc).__name__, "ref": ref},
            ) from exc
        except WorkspaceError as exc:
            raise (
                self._runtime_bridge or RuntimeWorkspaceBridge()
            ).from_workspace_error(exc) from exc


def prompt_blocks_from_workspace_input(
    prompt_input: WorkspacePromptInput,
    *,
    role: str = "reference",
) -> tuple[PromptBlock, ...]:
    """Convert prepared workspace prompt input into prompt blocks."""

    return tuple(
        _block_from_slice(text_slice, role=role) for text_slice in prompt_input.slices
    )


def _block_from_slice(text_slice: WorkspaceTextSlice, *, role: str) -> PromptBlock:
    label_role = "target" if role == "target" else "reference"
    return PromptBlock.from_text(
        f"task_prompt:input:workspace:{label_role}:{text_slice.ref}:{text_slice.range_label}",
        _render_slice(text_slice, role=label_role),
    )


def _render_slice(text_slice: WorkspaceTextSlice, *, role: str) -> str:
    truncated = "true" if text_slice.truncated else "false"
    heading = (
        prompt_text.WORKSPACE_TARGET
        if role == "target"
        else prompt_text.WORKSPACE_REFERENCE
    )
    lines = [
        heading,
        f"ref: {text_slice.ref}",
        f"range: {text_slice.range_label}",
        f"size: {text_slice.size} bytes",
        f"truncated: {truncated}",
        "",
        text_slice.text,
    ]
    return "\n".join(lines)
