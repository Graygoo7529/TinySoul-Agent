"""Workspace action handlers."""

from __future__ import annotations

from tinysoul.action.backends.llm_action import LLMActionTaskRunner
from tinysoul.action import (
    ActionEngineBuilder,
    ActionExecution,
    ActionExecutionContext,
    ActionExecutor,
    ActionResult,
    ActionResultStage,
)
from tinysoul.context import (
    PromptReferenceError,
)
from tinysoul.infra.json import JsonObject
from tinysoul.runtime import SignalBus

from .engine import WorkspaceEngine
from .errors import WorkspaceError
from .manifest import WorkspaceResourceRecord
from .prompts import (
    WorkspaceEditPromptBuilder,
)
from .projection import workspace_snapshot_signal


WORKSPACE_REWRITE_ACTION = "workspace.rewrite"

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
        scan = self._workspace.reconcile()
        if not scan.complete:
            skip_counts: JsonObject = {}
            for kind, count in scan.skip_counts().items():
                skip_counts[kind] = count
            return _failed(
                execution,
                "Workspace scan was incomplete; the existing manifest was preserved.",
                {
                    "reason": "incomplete_reconciliation",
                    "skipped_count": scan.skipped_count,
                    "skip_counts": skip_counts,
                    "limit_reached": scan.limit_reached,
                },
            )
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
            WorkspaceDescribeExecutor(workspace, bus, llm_action),
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
    """Generate a digest-bound semantic description for one resource."""

    def __init__(
        self,
        workspace: WorkspaceEngine,
        bus: SignalBus,
        llm_action: LLMActionTaskRunner,
    ) -> None:
        self._workspace = workspace
        self._bus = bus
        self._llm_action = llm_action
        self._prompt_builder = WorkspaceEditPromptBuilder(workspace)

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        target_link = _required_link(execution)
        if target_link is None:
            return _failed(
                execution,
                "workspace.describe requires a non-empty 'target_link' parameter.",
                {"reason": "missing_target_link"},
            )
        instruction = execution.call.params.get("instruction", "")
        if not isinstance(instruction, str):
            return _failed(
                execution,
                "workspace.describe instruction must be a string when provided.",
                {"reason": "invalid_instruction"},
            )
        try:
            prompt_build = self._prompt_builder.build_describe(
                target_link=target_link,
                instruction=instruction,
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
                f"Workspace describe failed: {exc}",
                {"error_type": type(exc).__name__},
            )
        payload = self._llm_action.run_json(
            execution=execution,
            prompt=prompt_build.prompt,
            subject="Workspace describe LLM task",
        )
        if isinstance(payload, ActionResult):
            return payload
        description = payload.get("description")
        if not isinstance(description, str) or not description.strip():
            return _failed(
                execution,
                "Workspace describe LLM task must return a non-empty description.",
                {"reason": "invalid_description"},
            )
        try:
            record = self._workspace.set_description(
                target_link,
                description,
                expected_digest=prompt_build.target_digest,
            )
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
        self._prompt_builder = WorkspaceEditPromptBuilder(workspace)

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
            prompt_build = self._prompt_builder.build_write(
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
        self._prompt_builder = WorkspaceEditPromptBuilder(workspace)

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
            prompt_build = self._prompt_builder.build_rewrite(
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
    signal_bus.emit(
        workspace_snapshot_signal(
            manifest,
            call_id=execution.call.call_id,
            scope=execution.framework.scope,
            source=source,
        )
    )


def _record_payload(record: WorkspaceResourceRecord) -> JsonObject:
    return {
        "link": record.link,
        "summary": record.summary,
        "description": record.description,
        "kind": record.kind.value,
        "media_type": record.media_type,
        "size": record.size,
        "mtime_ns": record.mtime_ns,
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
