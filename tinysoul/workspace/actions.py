"""Workspace action handlers."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.action.backends.llm_action import LLMActionTaskRunner
from tinysoul.action.engine import ActionEngineBuilder
from tinysoul.action.core.call import ActionExecution
from tinysoul.action.core.executor import ActionExecutionContext, ActionExecutor
from tinysoul.action.core.result import ActionResult, ActionResultStage
from tinysoul.context import (
    PromptBlock,
    PromptReferenceError,
    TaskPrompt,
    WorkspaceResource,
    WorkspaceSnapshot,
    build_workspace_sync_signal,
)
from tinysoul.infra.json import JsonObject
from tinysoul.runtime import SignalBus

from .engine import WorkspaceEngine
from .errors import WorkspaceError
from .manifest import WorkspaceResourceRecord
from .prompts import (
    WorkspacePromptReferenceResolver,
    prompt_blocks_from_workspace_input,
)


WORKSPACE_REWRITE_ACTION = "workspace.rewrite"


@dataclass(frozen=True)
class _WorkspaceLLMPrompt:
    prompt: TaskPrompt
    target_digest: str = ""


class WorkspaceScanExecutor(ActionExecutor):
    """Scan workspace resources and sync their summaries into WorkingContext."""

    def __init__(self, workspace: WorkspaceEngine, bus: SignalBus) -> None:
        self._workspace = workspace
        self._bus = bus

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        scan = self._workspace.scan()
        _emit_workspace_snapshot(
            self._workspace,
            execution=execution,
            context=context,
            bus=self._bus,
            source="workspace.scan",
        )
        skip_counts: JsonObject = {}
        for kind, count in scan.skip_counts().items():
            skip_counts[kind] = count
        return _success(
            execution,
            {
                "count": len(scan.manifest.resources),
                "resources": [
                    {"link": record.link, "summary": record.summary}
                    for record in scan.manifest.resources
                ],
                "skipped_count": scan.skipped_count,
                "skip_counts": skip_counts,
                "limit_reached": scan.limit_reached,
            },
        )


def register_workspace_actions(
    builder: ActionEngineBuilder,
    *,
    workspace: WorkspaceEngine,
    bus: SignalBus,
    llm_action: LLMActionTaskRunner,
) -> ActionEngineBuilder:
    """Register workspace action executors on an action builder."""

    result = (
        builder.register_executor("workspace.scan", WorkspaceScanExecutor(workspace, bus))
        .register_executor(
            "workspace.describe",
            WorkspaceDescribeExecutor(workspace, bus),
        )
        .register_executor(
            "workspace.write",
            WorkspaceWriteExecutor(
                workspace=workspace,
                bus=bus,
                llm_action=llm_action,
            ),
        )
        .register_executor(
            "workspace.patch",
            WorkspacePatchExecutor(workspace, bus),
        )
        .register_executor(
            "workspace.delete",
            WorkspaceDeleteExecutor(workspace, bus),
        )
    )
    return result.register_executor(
        WORKSPACE_REWRITE_ACTION,
        WorkspaceRewriteExecutor(
            workspace=workspace,
            bus=bus,
            llm_action=llm_action,
        ),
    )


class WorkspaceDescribeExecutor(ActionExecutor):
    """Refresh and return one workspace resource summary."""

    def __init__(self, workspace: WorkspaceEngine, bus: SignalBus) -> None:
        self._workspace = workspace
        self._bus = bus

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        link = execution.call.params.get("link")
        if not isinstance(link, str) or not link:
            return _failed(
                execution,
                "workspace.describe requires a non-empty 'link' parameter.",
                {"reason": "missing_link"},
            )
        try:
            record = self._workspace.describe(link)
        except WorkspaceError as exc:
            return _failed(
                execution,
                f"Workspace describe failed: {exc}",
                {"error_type": type(exc).__name__},
            )
        _emit_workspace_snapshot(
            self._workspace,
            execution=execution,
            context=context,
            bus=self._bus,
            source="workspace.describe",
        )
        return _success(execution, _record_payload(record))


class WorkspaceWriteExecutor(ActionExecutor):
    """Generate and write one workspace text resource through an internal LLM task."""

    def __init__(
        self,
        *,
        workspace: WorkspaceEngine,
        bus: SignalBus,
        llm_action: LLMActionTaskRunner,
    ) -> None:
        self._workspace = workspace
        self._bus = bus
        self._llm_action = llm_action
        self._prompt_resolver = WorkspacePromptReferenceResolver(workspace)

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        target_link = _required_link(execution)
        if target_link is None:
            return _failed(
                execution,
                "workspace.write requires a non-empty 'target_link' parameter.",
                {"reason": "missing_target_link"},
            )
        instruction = execution.call.params.get("instruction")
        if not isinstance(instruction, str) or not instruction:
            return _failed(
                execution,
                "workspace.write requires a non-empty 'instruction' string parameter.",
                {"reason": "invalid_instruction"},
            )
        overwrite = execution.call.params.get("overwrite", False)
        if not isinstance(overwrite, bool):
            return _failed(
                execution,
                "workspace.write overwrite must be a boolean when provided.",
                {"reason": "invalid_overwrite"},
            )
        expected_digest = execution.call.params.get("expected_digest", "")
        if not isinstance(expected_digest, str):
            return _failed(
                execution,
                "workspace.write expected_digest must be a string when provided.",
                {"reason": "invalid_expected_digest"},
            )
        reference_links = _string_list_param(
            execution.call.params.get("reference_links", []),
        )
        if reference_links is None:
            return _failed(
                execution,
                "workspace.write reference_links must be a list of strings.",
                {"reason": "invalid_reference_links"},
            )
        try:
            target_exists = self._workspace.write_target_exists(target_link)
            if target_exists and not overwrite:
                return _failed(
                    execution,
                    f"Workspace write target already exists: {target_link}",
                    {"reason": "target_exists", "link": target_link},
                )
            prompt_build = self._write_prompt(
                target_link=target_link,
                instruction=instruction,
                reference_links=reference_links,
                include_target=target_exists,
                overwrite=overwrite,
            )
            if expected_digest:
                if not target_exists:
                    return _failed(
                        execution,
                        f"Workspace write target does not exist for digest check: {target_link}",
                        {"reason": "missing_digest_target", "link": target_link},
                    )
                if prompt_build.target_digest != expected_digest:
                    return _failed(
                        execution,
                        f"Workspace write target digest mismatch: {target_link}",
                        {"reason": "digest_mismatch", "link": target_link},
                    )
        except PromptReferenceError as exc:
            return _failed(
                execution,
                str(exc),
                {**exc.payload, "reason": exc.reason},
            )
        except WorkspaceError as exc:
            return _failed(
                execution,
                f"Workspace write failed: {exc}",
                {"error_type": type(exc).__name__},
            )
        payload = self._llm_action.run_json(
            execution=execution,
            prompt=prompt_build.prompt,
            subject="Workspace write LLM task",
        )
        if isinstance(payload, ActionResult):
            return payload
        text = payload.get("text")
        if not isinstance(text, str):
            return _failed(
                execution,
                "Workspace write LLM task must return a JSON object with string field 'text'.",
                {"reason": "invalid_write_text"},
            )
        try:
            record = self._workspace.write_text(
                target_link,
                text,
                overwrite=overwrite,
                expected_digest=expected_digest or prompt_build.target_digest,
            )
        except WorkspaceError as exc:
            return _failed(
                execution,
                f"Workspace write failed: {exc}",
                {"error_type": type(exc).__name__},
            )
        _emit_workspace_snapshot(
            self._workspace,
            execution=execution,
            context=context,
            bus=self._bus,
            source="workspace.write",
        )
        result_payload = _record_payload(record)
        result_payload["written"] = True
        return _success(execution, result_payload)

    def _write_prompt(
        self,
        *,
        target_link: str,
        instruction: str,
        reference_links: tuple[str, ...],
        include_target: bool,
        overwrite: bool,
    ) -> _WorkspaceLLMPrompt:
        target_blocks: tuple[PromptBlock, ...] = ()
        target_digest = ""
        if include_target:
            target_input = self._workspace.prepare_task_input((target_link,))
            target_digest = target_input.slices[0].digest
            target_blocks = prompt_blocks_from_workspace_input(
                target_input,
                role="target",
            )
        reference_blocks: list[PromptBlock] = []
        for link in reference_links:
            if not self._prompt_resolver.supports(link):
                raise PromptReferenceError(
                    f"Unsupported workspace reference link: {link}",
                    reason="unsupported_reference_link",
                    payload={"link": link},
            )
            reference_blocks.extend(self._prompt_resolver.resolve_reference(link))
        overwrite_text = "true" if overwrite else "false"
        return _WorkspaceLLMPrompt(
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
                    *tuple(reference_blocks),
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

class WorkspacePatchExecutor(ActionExecutor):
    """Apply an exact text replacement to one workspace resource."""

    def __init__(self, workspace: WorkspaceEngine, bus: SignalBus) -> None:
        self._workspace = workspace
        self._bus = bus

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        link = _required_link(execution)
        if link is None:
            return _failed(
                execution,
                "workspace.patch requires a non-empty 'target_link' parameter.",
                {"reason": "missing_target_link"},
            )
        old_text = execution.call.params.get("old_text")
        if not isinstance(old_text, str) or not old_text:
            return _failed(
                execution,
                "workspace.patch requires a non-empty 'old_text' string parameter.",
                {"reason": "invalid_old_text"},
            )
        new_text = execution.call.params.get("new_text")
        if not isinstance(new_text, str):
            return _failed(
                execution,
                "workspace.patch requires a 'new_text' string parameter.",
                {"reason": "invalid_new_text"},
            )
        expected_digest = execution.call.params.get("expected_digest", "")
        if not isinstance(expected_digest, str):
            return _failed(
                execution,
                "workspace.patch expected_digest must be a string when provided.",
                {"reason": "invalid_expected_digest"},
            )
        try:
            record = self._workspace.patch_text(
                link,
                old_text=old_text,
                new_text=new_text,
                expected_digest=expected_digest,
            )
        except WorkspaceError as exc:
            return _failed(
                execution,
                f"Workspace patch failed: {exc}",
                {"error_type": type(exc).__name__},
            )
        _emit_workspace_snapshot(
            self._workspace,
            execution=execution,
            context=context,
            bus=self._bus,
            source="workspace.patch",
        )
        return _success(execution, _record_payload(record))


class WorkspaceDeleteExecutor(ActionExecutor):
    """Delete one workspace resource and remove its working summary."""

    def __init__(self, workspace: WorkspaceEngine, bus: SignalBus) -> None:
        self._workspace = workspace
        self._bus = bus

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        link = _required_link(execution)
        if link is None:
            return _failed(
                execution,
                "workspace.delete requires a non-empty 'target_link' parameter.",
                {"reason": "missing_target_link"},
            )
        try:
            record = self._workspace.delete_resource(link)
        except WorkspaceError as exc:
            return _failed(
                execution,
                f"Workspace delete failed: {exc}",
                {"error_type": type(exc).__name__},
            )
        _emit_workspace_snapshot(
            self._workspace,
            execution=execution,
            context=context,
            bus=self._bus,
            source="workspace.delete",
        )
        payload = _record_payload(record)
        payload["deleted"] = True
        return _success(execution, payload)


class WorkspaceRewriteExecutor(ActionExecutor):
    """Rewrite a workspace text resource through an internal LLM task."""

    def __init__(
        self,
        *,
        workspace: WorkspaceEngine,
        bus: SignalBus,
        llm_action: LLMActionTaskRunner,
    ) -> None:
        self._workspace = workspace
        self._bus = bus
        self._llm_action = llm_action
        self._prompt_resolver = WorkspacePromptReferenceResolver(workspace)

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        target_link = _required_link(execution)
        if target_link is None:
            return _failed(
                execution,
                "workspace.rewrite requires a non-empty 'target_link' parameter.",
                {"reason": "missing_target_link"},
            )
        instruction = execution.call.params.get("instruction")
        if not isinstance(instruction, str) or not instruction:
            return _failed(
                execution,
                "workspace.rewrite requires a non-empty 'instruction' string parameter.",
                {"reason": "invalid_instruction"},
            )
        expected_digest = execution.call.params.get("expected_digest", "")
        if not isinstance(expected_digest, str):
            return _failed(
                execution,
                "workspace.rewrite expected_digest must be a string when provided.",
                {"reason": "invalid_expected_digest"},
            )
        reference_links = _string_list_param(
            execution.call.params.get("reference_links", []),
        )
        if reference_links is None:
            return _failed(
                execution,
                "workspace.rewrite reference_links must be a list of strings.",
                {"reason": "invalid_reference_links"},
            )
        try:
            prompt_build = self._rewrite_prompt(
                target_link=target_link,
                instruction=instruction,
                reference_links=reference_links,
            )
            if expected_digest and prompt_build.target_digest != expected_digest:
                return _failed(
                    execution,
                    f"Workspace rewrite target digest mismatch: {target_link}",
                    {"reason": "digest_mismatch", "link": target_link},
                )
        except PromptReferenceError as exc:
            return _failed(
                execution,
                str(exc),
                {**exc.payload, "reason": exc.reason},
            )
        except WorkspaceError as exc:
            return _failed(
                execution,
                f"Workspace rewrite failed: {exc}",
                {"error_type": type(exc).__name__},
            )
        payload = self._llm_action.run_json(
            execution=execution,
            prompt=prompt_build.prompt,
            subject="Workspace rewrite LLM task",
        )
        if isinstance(payload, ActionResult):
            return payload
        text = payload.get("text")
        if not isinstance(text, str):
            return _failed(
                execution,
                "Workspace rewrite LLM task must return a JSON object with string field 'text'.",
                {"reason": "invalid_rewrite_text"},
            )
        try:
            record = self._workspace.write_text(
                target_link,
                text,
                overwrite=True,
                expected_digest=expected_digest or prompt_build.target_digest,
            )
        except WorkspaceError as exc:
            return _failed(
                execution,
                f"Workspace rewrite failed: {exc}",
                {"error_type": type(exc).__name__},
            )
        _emit_workspace_snapshot(
            self._workspace,
            execution=execution,
            context=context,
            bus=self._bus,
            source="workspace.rewrite",
        )
        result_payload = _record_payload(record)
        result_payload["rewritten"] = True
        return _success(execution, result_payload)

    def _rewrite_prompt(
        self,
        *,
        target_link: str,
        instruction: str,
        reference_links: tuple[str, ...],
    ) -> _WorkspaceLLMPrompt:
        target_input = self._workspace.prepare_task_input((target_link,))
        target_blocks = prompt_blocks_from_workspace_input(
            target_input,
            role="target",
        )
        reference_blocks: list[PromptBlock] = []
        for link in reference_links:
            if not self._prompt_resolver.supports(link):
                raise PromptReferenceError(
                    f"Unsupported workspace reference link: {link}",
                    reason="unsupported_reference_link",
                    payload={"link": link},
            )
            reference_blocks.extend(self._prompt_resolver.resolve_reference(link))
        return _WorkspaceLLMPrompt(
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
                    *tuple(reference_blocks),
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


def _required_link(execution: ActionExecution) -> str | None:
    link = execution.call.params.get("target_link")
    if not isinstance(link, str) or not link:
        return None
    return link


def _string_list_param(value: object) -> tuple[str, ...] | None:
    if value is None:
        return ()
    if not isinstance(value, list):
        return None
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            return None
        if item not in result:
            result.append(item)
    return tuple(result)


def _emit_workspace_snapshot(
    workspace: WorkspaceEngine,
    *,
    execution: ActionExecution,
    context: ActionExecutionContext,
    bus: SignalBus,
    source: str,
) -> None:
    signal_bus = context.signal_bus or bus
    manifest = workspace.snapshot()
    snapshot = WorkspaceSnapshot(
        revision=manifest.revision,
        resources=tuple(
            WorkspaceResource(link=record.link, summary=record.summary)
            for record in manifest.resources
        ),
    )
    signal_bus.emit(
        build_workspace_sync_signal(
            snapshot,
            call_id=execution.call.call_id,
            scope=execution.framework.scope,
            source=source,
        )
    )


def _record_payload(record: WorkspaceResourceRecord) -> JsonObject:
    return {
        "link": record.link,
        "summary": record.summary,
        "size": record.size,
        "mtime": record.mtime,
        "digest": record.digest,
    }


def _success(execution: ActionExecution, payload: JsonObject) -> ActionResult:
    return ActionResult.success(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        payload=payload,
    )


def _failed(
    execution: ActionExecution,
    model_feedback: str,
    frame_data: JsonObject,
) -> ActionResult:
    return ActionResult.failed(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        stage=ActionResultStage.EXECUTE,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        model_feedback=model_feedback,
        frame_data=frame_data,
    )
