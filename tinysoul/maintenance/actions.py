"""Maintenance-only action executors and request-local task state."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from tinysoul.action import (
    ActionEngine,
    ActionEngineBuilder,
    ActionExecution,
    ActionExecutionContext,
    ActionExecutor,
    ActionFailureDisposition,
    ActionLocalFailure,
    ActionResult,
    ActionResultStage,
    ActionResultStatus,
)
from tinysoul.home import (
    AgentHomeEngine,
    HomeMaintenanceResolution,
)
from tinysoul.home.errors import AgentHomeError
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

from .day import BusinessDay
from .errors import MaintenanceContractError, MaintenanceInvariantError

MAINTENANCE_HOME_ACTIONS = (
    "maintenance.home.list",
    "maintenance.home.inspect",
    "maintenance.home.accept",
    "maintenance.home.reject",
    "maintenance.home.rewrite",
    "maintenance.complete",
)
MAINTENANCE_MEMORY_ACTIONS = (
    "maintenance.memory.inspect_facts",
    "maintenance.memory.inspect_workspace",
    "maintenance.memory.consolidate",
    "maintenance.complete",
)
MAINTENANCE_ACTIONS = tuple(
    dict.fromkeys((*MAINTENANCE_HOME_ACTIONS, *MAINTENANCE_MEMORY_ACTIONS))
)
MAINTENANCE_COMPLETION = "maintenance"


def user_action_view(action: ActionEngine) -> ActionEngine:
    """Exclude framework-only Maintenance actions from a User Turn."""

    return action.view(
        tuple(
            name
            for domain, name in action.action_identifiers()
            if domain != "maintenance"
        )
    )


def maintenance_action_view(
    action: ActionEngine,
    *,
    kind: str,
) -> ActionEngine:
    """Return the immutable action view for one Maintenance task kind."""

    actions = {
        "home": MAINTENANCE_HOME_ACTIONS,
        "memory": MAINTENANCE_MEMORY_ACTIONS,
    }.get(kind)
    if actions is None:
        raise MaintenanceContractError(f"Unknown Maintenance task kind: {kind}")
    return action.view(actions)


class MaintenanceCompletionDetector:
    """Detect one owner-validated ``maintenance.complete`` result."""

    def detect(self, results: tuple[ActionResult, ...]) -> JsonObject | None:
        completions = tuple(
            result
            for result in results
            if result.action_name == "maintenance.complete"
            and result.status is ActionResultStatus.SUCCESS
        )
        if not completions:
            return None
        if len(completions) != 1:
            raise MaintenanceInvariantError(
                "A Maintenance Turn cycle produced multiple successful completions"
            )
        result = completions[0]
        task = result.payload.get("task")
        if result.payload.get("completed") is not True or task not in {
            "home",
            "memory",
        }:
            raise MaintenanceInvariantError(
                "A successful maintenance.complete result has an invalid payload"
            )
        return {
            "kind": MAINTENANCE_COMPLETION,
            "result_id": result.result_id,
            "task": task,
        }


@dataclass(frozen=True)
class MaintenanceTaskResult:
    kind: str
    details: JsonObject


@dataclass
class _TaskState:
    kind: str
    target_day: BusinessDay | None = None
    projection: SessionMemoryFactsProjection | None = None
    workspace: WorkspaceManifest | None = None
    rebuild_memory: bool = False
    memory_outcome: MemoryMaintenanceOutcome | None = None
    completed: bool = False


class MaintenanceActionController:
    """Own non-persisted state for the currently running Maintenance Turn."""

    def __init__(
        self,
        *,
        home: AgentHomeEngine,
        memory: MemoryEngine,
        consolidator: MemoryConsolidator,
        timezone: str,
    ) -> None:
        self._home = home
        self._memory = memory
        self._consolidator = consolidator
        self._timezone = timezone
        self._lock = RLock()
        self._state: _TaskState | None = None

    def begin_home(self) -> None:
        self._begin(_TaskState(kind="home"))

    def begin_memory(
        self,
        *,
        target_day: BusinessDay,
        projection: SessionMemoryFactsProjection,
        workspace: WorkspaceManifest | None,
        rebuild_memory: bool,
    ) -> None:
        self._begin(
            _TaskState(
                kind="memory",
                target_day=target_day,
                projection=projection,
                workspace=workspace,
                rebuild_memory=rebuild_memory,
            )
        )

    def finish(self) -> MaintenanceTaskResult:
        with self._lock:
            state = self._require_state()
            try:
                if not state.completed:
                    raise MaintenanceInvariantError(
                        "Maintenance Turn ended without maintenance.complete"
                    )
                if state.kind == "home":
                    return MaintenanceTaskResult(
                        kind=state.kind,
                        details={"remaining_changes": 0},
                    )
                outcome = state.memory_outcome
                if outcome is None:
                    raise MaintenanceInvariantError(
                        "Memory Maintenance completed without consolidation"
                    )
                details = _memory_outcome_json(outcome)
                return MaintenanceTaskResult(kind=state.kind, details=details)
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
        try:
            with self._lock:
                state = self._require_state()
                payload = self._execute(state, execution)
            return _success(execution, payload)
        except (MaintenanceContractError, MaintenanceInvariantError, AgentHomeError, MemoryError) as exc:
            return _failed(
                execution,
                str(exc),
                reason="maintenance_action_failed",
                frame_data={"error_type": type(exc).__name__},
            )

    def _execute(self, state: _TaskState, execution: ActionExecution) -> JsonObject:
        name = execution.call.action_name
        params = execution.call.params
        if name.startswith("maintenance.home."):
            self._require_kind(state, "home")
        if name.startswith("maintenance.memory."):
            self._require_kind(state, "memory")

        if name == "maintenance.home.list":
            snapshot = self._home.maintenance_snapshot()
            return {
                "count": len(snapshot.changes),
                "items": [
                    {
                        "token": change.token,
                        "link": change.link,
                        "state": change.state.value,
                        "baseline_digest": change.baseline_digest,
                        "runtime_digest": change.runtime_digest,
                        "actual_digest": change.actual_digest,
                    }
                    for change in snapshot.changes
                ],
            }
        if name == "maintenance.home.inspect":
            change = self._home_change(_required_text(params, "token"))
            return change.to_review_json()
        if name in {
            "maintenance.home.accept",
            "maintenance.home.reject",
            "maintenance.home.rewrite",
        }:
            resolution = {
                "maintenance.home.accept": HomeMaintenanceResolution.ACCEPT,
                "maintenance.home.reject": HomeMaintenanceResolution.REJECT,
                "maintenance.home.rewrite": HomeMaintenanceResolution.REWRITE,
            }[name]
            rewrite_text = (
                _required_text(params, "text")
                if resolution is HomeMaintenanceResolution.REWRITE
                else None
            )
            outcome = self._home.resolve_maintenance(
                _required_text(params, "token"),
                resolution,
                rewrite_text=rewrite_text,
            )
            return {
                "link": outcome.link,
                "resolution": outcome.resolution.value,
                "remaining_changes": outcome.remaining_changes,
            }
        if name == "maintenance.memory.inspect_facts":
            projection = self._require_projection(state)
            offset = _optional_non_negative_int(params, "offset", default=0)
            limit = _optional_positive_int(params, "limit", default=8, maximum=32)
            selected = projection.facts[offset : offset + limit]
            return {
                "day": str(projection.day),
                "revision": projection.revision,
                "offset": offset,
                "facts": [fact.to_json() for fact in selected],
                "has_more": offset + len(selected) < len(projection.facts),
            }
        if name == "maintenance.memory.inspect_workspace":
            workspace = state.workspace
            if workspace is None:
                return {"available": False, "resources": []}
            return {
                "available": True,
                "day": workspace.day,
                "revision": workspace.revision,
                "resources": [
                    {
                        "link": item.link,
                        "kind": item.kind.value,
                        "summary": item.summary,
                        "size": item.size,
                        "digest": item.digest,
                    }
                    for item in workspace.resources
                ],
            }
        if name == "maintenance.memory.consolidate":
            if state.memory_outcome is not None:
                raise MaintenanceContractError(
                    "Memory consolidation already ran in this Maintenance Turn"
                )
            projection = self._require_projection(state)
            state.memory_outcome = self._memory.run_maintenance(
                projection=projection,
                consolidator=self._consolidator,
                timezone=self._timezone,
                target_day=state.target_day,
                rewrite_existing=state.rebuild_memory,
                scope=execution.framework.scope,
            )
            return _memory_outcome_json(state.memory_outcome)
        if name == "maintenance.complete":
            if state.kind == "home":
                snapshot = self._home.maintenance_snapshot()
                if snapshot.pending:
                    raise MaintenanceContractError(
                        "Home Maintenance still has unresolved changes"
                    )
            else:
                outcome = state.memory_outcome
                if outcome is None:
                    raise MaintenanceContractError(
                        "Memory Maintenance must consolidate before completion"
                    )
                if outcome.status is MemoryMaintenanceStatus.FAILED:
                    raise MaintenanceContractError(
                        "Memory Maintenance consolidation failed"
                    )
            state.completed = True
            return {"completed": True, "task": state.kind}
        raise MaintenanceContractError(f"Unknown Maintenance action: {name}")

    def _home_change(self, token: str):
        matching = tuple(
            change
            for change in self._home.maintenance_snapshot().changes
            if change.token == token
        )
        if len(matching) != 1:
            raise MaintenanceContractError(
                "Home Maintenance change token is stale or unknown"
            )
        return matching[0]

    def _begin(self, state: _TaskState) -> None:
        with self._lock:
            if self._state is not None:
                raise MaintenanceInvariantError(
                    "A Maintenance action task is already active"
                )
            self._state = state

    def _require_state(self) -> _TaskState:
        if self._state is None:
            raise MaintenanceInvariantError("No Maintenance action task is active")
        return self._state

    @staticmethod
    def _require_kind(state: _TaskState, expected: str) -> None:
        if state.kind != expected:
            raise MaintenanceContractError(
                f"{expected.title()} action is unavailable in a {state.kind} task"
            )

    @staticmethod
    def _require_projection(state: _TaskState) -> SessionMemoryFactsProjection:
        if state.projection is None:
            raise MaintenanceInvariantError("Memory facts projection disappeared")
        return state.projection


class MaintenanceActionExecutor(ActionExecutor):
    def __init__(self, controller: MaintenanceActionController) -> None:
        self._controller = controller

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        return self._controller.execute(execution, context)


def register_maintenance_actions(
    builder: ActionEngineBuilder,
    *,
    controller: MaintenanceActionController,
) -> ActionEngineBuilder:
    executor = MaintenanceActionExecutor(controller)
    for name in MAINTENANCE_ACTIONS:
        builder.register_executor(name, executor)
    return builder


def _required_text(params: JsonObject, name: str) -> str:
    value = params.get(name)
    if not isinstance(value, str) or not value:
        raise MaintenanceContractError(
            f"Maintenance action requires non-empty {name}"
        )
    return value


def _optional_non_negative_int(
    params: JsonObject,
    name: str,
    *,
    default: int,
) -> int:
    value = params.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MaintenanceContractError(f"Maintenance action {name} is invalid")
    return value


def _optional_positive_int(
    params: JsonObject,
    name: str,
    *,
    default: int,
    maximum: int,
) -> int:
    value = params.get(name, default)
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        or value > maximum
    ):
        raise MaintenanceContractError(f"Maintenance action {name} is invalid")
    return value


def _memory_outcome_json(outcome: MemoryMaintenanceOutcome) -> JsonObject:
    value: JsonObject = {
        "day": str(outcome.day),
        "link": outcome.link,
        "status": outcome.status.value,
        "fact_count": outcome.fact_count,
        "model_calls": outcome.model_calls,
    }
    if outcome.skip_reason is not None:
        value["skip_reason"] = outcome.skip_reason.value
    if outcome.failure is not None:
        value["failure_kind"] = outcome.failure.value
    if outcome.document_digest:
        value["document_digest"] = outcome.document_digest
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


def _failed(
    execution: ActionExecution,
    feedback: str,
    *,
    reason: str,
    frame_data: JsonObject | None = None,
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
            scope="maintenance.action",
            disposition=ActionFailureDisposition.CHANGE_REQUEST,
            feedback=feedback,
        ),
        frame_data=frame_data,
    )
