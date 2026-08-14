"""Shared Action integration for supervised Execution jobs."""

from __future__ import annotations

from typing import Protocol

from tinysoul.action import (
    ActionEngineBuilder,
    ActionExecution,
    ActionExecutionContext,
    ActionExecutor,
    ActionFailureDisposition,
    ActionLocalFailure,
    ActionResult,
    ActionResultStage,
)
from tinysoul.infra import JsonObject
from tinysoul.runtime import RuntimeException, SignalBus
from tinysoul.workspace import (
    WorkspaceContractError,
    WorkspaceError,
    WorkspaceMirrorConflict,
    workspace_snapshot_signal,
)

from .errors import SupervisedProcessError
from .manager import SupervisedProcessManager
from .models import SupervisedProcessObservation


EXECUTION_LIFECYCLE_ACTIONS = (
    "execution.wait",
    "execution.stop",
    "execution.read_candidate",
    "execution.apply",
    "execution.discard",
)


class SupervisedProcessWorkspaceRuntimeBridge(Protocol):
    def from_workspace_error(
        self,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException: ...


class SupervisedProcessJobExecutor(ActionExecutor):
    """Resolve one shared Script/Shell job operation by execution identity."""

    def __init__(
        self,
        *,
        operation: str,
        jobs: SupervisedProcessManager,
        bus: SignalBus,
        workspace_bridge: SupervisedProcessWorkspaceRuntimeBridge | None,
    ) -> None:
        self._operation = operation
        self._jobs = jobs
        self._bus = bus
        self._workspace_bridge = workspace_bridge

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        execution_id = _required_text(execution, "execution_id")
        if execution_id is None:
            return _failed(
                execution,
                "Execution job action requires execution_id.",
                reason="missing_execution_id",
            )
        try:
            if self._operation == "wait":
                wait = execution.call.params.get(
                    "wait_seconds",
                    self._jobs.wait_policy.default_seconds,
                )
                if isinstance(wait, bool) or not isinstance(wait, int):
                    return _failed(
                        execution,
                        "Execution wait_seconds must be an integer.",
                        reason="invalid_wait",
                    )
                return _observation_result(
                    execution,
                    self._jobs.wait(
                        turn_id=execution.framework.turn_id,
                        execution_id=execution_id,
                        wait_seconds=wait,
                        control=context.control,
                        bus=context.signal_bus or self._bus,
                    ),
                )
            if self._operation == "stop":
                return _observation_result(
                    execution,
                    self._jobs.stop(
                        turn_id=execution.framework.turn_id,
                        execution_id=execution_id,
                    ),
                )
            if self._operation == "read_candidate":
                path = _required_text(execution, "path")
                cursor = execution.call.params.get("cursor", 0)
                max_chars = execution.call.params.get(
                    "max_chars",
                    self._jobs.settings.max_candidate_read_chars,
                )
                if (
                    path is None
                    or isinstance(cursor, bool)
                    or not isinstance(cursor, int)
                    or isinstance(max_chars, bool)
                    or not isinstance(max_chars, int)
                ):
                    return _failed(
                        execution,
                        "Execution candidate read parameters are invalid.",
                        reason="invalid_candidate_read",
                    )
                return _success(
                    execution,
                    self._jobs.read_candidate(
                        turn_id=execution.framework.turn_id,
                        execution_id=execution_id,
                        path=path,
                        cursor=cursor,
                        max_chars=max_chars,
                    ),
                )
            if self._operation == "apply":
                applied = self._jobs.apply(
                    turn_id=execution.framework.turn_id,
                    execution_id=execution_id,
                )
                (context.signal_bus or self._bus).emit(
                    workspace_snapshot_signal(
                        applied.manifest,
                        call_id=execution.call.call_id,
                        scope=execution.framework.scope,
                        source=execution.call.action_name,
                    )
                )
                return _success(execution, applied.payload)
            if self._operation == "discard":
                return _success(
                    execution,
                    self._jobs.discard(
                        turn_id=execution.framework.turn_id,
                        execution_id=execution_id,
                    ),
                )
        except WorkspaceMirrorConflict:
            return _failed(
                execution,
                "Execution apply conflicts with a concurrently changed Workspace "
                "path. The job remains available for review or discard.",
                reason="workspace_apply_conflict",
            )
        except (SupervisedProcessError, WorkspaceContractError) as exc:
            return _failed(
                execution,
                "Execution job operation failed.",
                reason="job_operation_failed",
                frame_data={"error_type": type(exc).__name__},
            )
        except WorkspaceError as exc:
            if self._workspace_bridge is None:
                raise
            raise self._workspace_bridge.from_workspace_error(
                exc,
                payload={"capability": "supervised_process"},
            ) from exc
        return _failed(
            execution,
            "Execution job operation is unavailable.",
            reason="unknown_job_operation",
            disposition=ActionFailureDisposition.STOP,
        )


def register_supervised_process_actions(
    builder: ActionEngineBuilder,
    *,
    enabled: bool,
    jobs: SupervisedProcessManager,
    bus: SignalBus,
    workspace_bridge: SupervisedProcessWorkspaceRuntimeBridge | None = None,
) -> ActionEngineBuilder:
    """Register the single model-visible lifecycle for Script and Shell jobs."""

    if not enabled:
        builder.mark_actions_unsupported(*EXECUTION_LIFECYCLE_ACTIONS)
        return builder
    for operation in ("wait", "stop", "read_candidate", "apply", "discard"):
        builder.register_executor(
            f"supervised_process.{operation}",
            SupervisedProcessJobExecutor(
                operation=operation,
                jobs=jobs,
                bus=bus,
                workspace_bridge=workspace_bridge,
            ),
        )
    return builder


def _required_text(execution: ActionExecution, name: str) -> str | None:
    value = execution.call.params.get(name)
    return value if isinstance(value, str) and value else None


def _observation_result(
    execution: ActionExecution,
    observation: SupervisedProcessObservation,
) -> ActionResult:
    if observation.timed_out:
        return ActionResult.timeout(
            call_id=execution.call.call_id,
            invoke_id=execution.framework.invoke_id,
            batch_id=execution.framework.batch_id,
            action_name=execution.call.action_name,
            sequence=execution.call.sequence,
            domain=execution.framework.domain,
            failure=ActionLocalFailure(
                reason="process_job_timeout",
                scope="supervised_process.action",
                disposition=ActionFailureDisposition.CHANGE_REQUEST,
                feedback=(
                    "Execution job reached its configured timeout and must be discarded."
                ),
            ),
            payload=observation.payload,
            frame_data={"executor_leaked": False},
        )
    if observation.failed:
        return _failed(
            execution,
            "Execution process failed. Logs and candidates remain inspectable but "
            "cannot be applied.",
            reason="process_failed",
            payload=observation.payload,
        )
    return _success(execution, observation.payload)


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
    feedback: str,
    *,
    reason: str,
    disposition: ActionFailureDisposition = ActionFailureDisposition.CHANGE_REQUEST,
    frame_data: JsonObject | None = None,
    payload: JsonObject | None = None,
) -> ActionResult:
    return ActionResult.failed(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        stage=ActionResultStage.EXECUTE,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        failure=ActionLocalFailure(
            reason=reason,
            scope="supervised_process.action",
            disposition=disposition,
            feedback=feedback,
        ),
        frame_data=frame_data,
        payload=payload,
    )
