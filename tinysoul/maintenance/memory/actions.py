"""Memory Maintenance action state and owner-bound executors."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

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
from tinysoul.infra.json import JsonObject
from tinysoul.memory import (
    MemoryConsolidator,
    MemoryEngine,
    MemoryMaintenanceOutcome,
    MemoryMaintenanceStatus,
)
from tinysoul.memory.errors import MemoryError
from tinysoul.session import SessionMemoryFactsProjection
from tinysoul.workspace import WorkspaceManifest

from tinysoul.infra.time import BusinessDay
from ..errors import MaintenanceContractError, MaintenanceInvariantError

MEMORY_MAINTENANCE_ACTIONS = (
    "maintenance.memory.inspect_facts",
    "maintenance.memory.inspect_workspace",
    "maintenance.memory.consolidate",
    "maintenance.complete",
)


@dataclass
class _MemoryTaskState:
    target_day: BusinessDay
    projection: SessionMemoryFactsProjection
    workspace: WorkspaceManifest | None
    rebuild_memory: bool
    outcome: MemoryMaintenanceOutcome | None = None
    completed: bool = False


class MemoryMaintenanceActionController:
    """Own ephemeral action state for one Memory Maintenance Turn."""

    def __init__(
        self,
        *,
        memory: MemoryEngine,
        consolidator: MemoryConsolidator,
        timezone: str,
    ) -> None:
        self._memory = memory
        self._consolidator = consolidator
        self._timezone = timezone
        self._lock = RLock()
        self._state: _MemoryTaskState | None = None

    def begin(
        self,
        *,
        target_day: BusinessDay,
        projection: SessionMemoryFactsProjection,
        workspace: WorkspaceManifest | None,
        rebuild_memory: bool,
    ) -> None:
        with self._lock:
            if self._state is not None:
                raise MaintenanceInvariantError(
                    "A Memory Maintenance task is already active"
                )
            self._state = _MemoryTaskState(
                target_day=target_day,
                projection=projection,
                workspace=workspace,
                rebuild_memory=rebuild_memory,
            )

    def finish(self) -> JsonObject:
        with self._lock:
            state = self._require_state()
            try:
                if not state.completed or state.outcome is None:
                    raise MaintenanceInvariantError(
                        "Memory Maintenance Turn ended before owner completion"
                    )
                return _outcome_json(state.outcome)
            finally:
                self._state = None

    def abort(self) -> None:
        with self._lock:
            self._state = None

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        del context
        try:
            with self._lock:
                payload = self._execute(self._require_state(), execution)
            return _success(execution, payload)
        except (MaintenanceContractError, MaintenanceInvariantError, MemoryError) as exc:
            return _failed(execution, str(exc), reason="memory_failed")

    def _execute(
        self,
        state: _MemoryTaskState,
        execution: ActionExecution,
    ) -> JsonObject:
        name = execution.call.action_name
        params = execution.call.params
        if name == "maintenance.memory.inspect_facts":
            offset = _optional_int(params, "offset", default=0, minimum=0, maximum=None)
            limit = _optional_int(params, "limit", default=8, minimum=1, maximum=32)
            selected = state.projection.facts[offset : offset + limit]
            return {
                "day": str(state.projection.day),
                "revision": state.projection.revision,
                "offset": offset,
                "facts": [fact.to_json() for fact in selected],
                "has_more": offset + len(selected) < len(state.projection.facts),
            }
        if name == "maintenance.memory.inspect_workspace":
            if state.workspace is None:
                return {"available": False, "resources": []}
            return {
                "available": True,
                "day": state.workspace.day,
                "revision": state.workspace.revision,
                "resources": [
                    {
                        "link": item.link,
                        "kind": item.kind.value,
                        "summary": item.summary,
                        "size": item.size,
                        "digest": item.digest,
                    }
                    for item in state.workspace.resources
                ],
            }
        if name == "maintenance.memory.consolidate":
            if state.outcome is not None:
                raise MaintenanceContractError(
                    "Memory consolidation already ran in this Maintenance Turn"
                )
            state.outcome = self._memory.run_maintenance(
                projection=state.projection,
                consolidator=self._consolidator,
                timezone=self._timezone,
                target_day=state.target_day,
                rewrite_existing=state.rebuild_memory,
                scope=execution.framework.scope,
            )
            return _outcome_json(state.outcome)
        if name == "maintenance.complete":
            if state.outcome is None:
                raise MaintenanceContractError(
                    "Memory Maintenance must consolidate before completion"
                )
            if state.outcome.status is MemoryMaintenanceStatus.FAILED:
                raise MaintenanceContractError(
                    "Memory Maintenance consolidation failed"
                )
            state.completed = True
            return {"completed": True, "task": "memory"}
        raise MaintenanceContractError(f"Unknown Memory Maintenance action: {name}")

    def _require_state(self) -> _MemoryTaskState:
        if self._state is None:
            raise MaintenanceInvariantError("No Memory Maintenance task is active")
        return self._state


class MemoryMaintenanceActionExecutor(ActionExecutor):
    def __init__(self, controller: MemoryMaintenanceActionController) -> None:
        self._controller = controller

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        return self._controller.execute(execution, context)


def register_memory_maintenance_actions(
    builder: ActionEngineBuilder,
    *,
    controller: MemoryMaintenanceActionController,
) -> ActionEngineBuilder:
    executor = MemoryMaintenanceActionExecutor(controller)
    for handler in MEMORY_MAINTENANCE_ACTIONS:
        builder.register_executor(handler, executor)
    return builder


def _outcome_json(outcome: MemoryMaintenanceOutcome) -> JsonObject:
    value: JsonObject = {
        "day": str(outcome.day),
        "link": outcome.link,
        "status": outcome.status.value,
        "fact_count": outcome.fact_count,
        "model_calls": outcome.model_calls,
        "document_digest": outcome.document_digest,
    }
    if outcome.skip_reason is not None:
        value["skip_reason"] = outcome.skip_reason.value
    if outcome.failure is not None:
        value["failure_kind"] = outcome.failure.value
    return value


def _optional_int(
    params: JsonObject,
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int | None,
) -> int:
    value = params.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise MaintenanceContractError(
            f"Memory Maintenance parameter {name} is invalid"
        )
    if maximum is not None and value > maximum:
        raise MaintenanceContractError(
            f"Memory Maintenance parameter {name} exceeds {maximum}"
        )
    return value


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


def _failed(execution: ActionExecution, feedback: str, *, reason: str) -> ActionResult:
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
            scope="maintenance.memory",
            disposition=ActionFailureDisposition.CHANGE_REQUEST,
            feedback=feedback,
        ),
    )
