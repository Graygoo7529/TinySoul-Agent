"""Home Maintenance action state and owner-bound executors."""

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
from tinysoul.home import AgentHomeEngine, HomeMaintenanceResolution
from tinysoul.home.errors import AgentHomeError, AgentHomeInvariantError
from tinysoul.infra.json import JsonObject

from ..errors import MaintenanceContractError, MaintenanceInvariantError

HOME_MAINTENANCE_ACTIONS = (
    "maintenance.home.list",
    "maintenance.home.inspect",
    "maintenance.home.accept",
    "maintenance.home.reject",
    "maintenance.home.rewrite",
    "maintenance.complete",
)


@dataclass
class _HomeTaskState:
    completed: bool = False
    resolved: int = 0


class HomeMaintenanceActionController:
    """Own ephemeral action state for one Home Maintenance Turn."""

    def __init__(self, home: AgentHomeEngine) -> None:
        self._home = home
        self._lock = RLock()
        self._state: _HomeTaskState | None = None

    def begin(self) -> None:
        with self._lock:
            if self._state is not None:
                raise MaintenanceInvariantError("A Home Maintenance task is already active")
            self._state = _HomeTaskState()

    def finish(self) -> JsonObject:
        with self._lock:
            state = self._require_state()
            try:
                if not state.completed:
                    raise MaintenanceInvariantError(
                        "Home Maintenance Turn ended without maintenance.complete"
                    )
                pending = self._home.maintenance_pending()
                if pending.pending:
                    raise MaintenanceInvariantError(
                        "Home Maintenance completed with unresolved runtime differences"
                    )
                removed = self._home.finalize_maintenance()
                return {
                    "resolved": state.resolved,
                    "remaining_changes": 0,
                    "runtime_home_removed": removed,
                }
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
                state = self._require_state()
                payload = self._execute(state, execution)
            return _success(execution, payload)
        except AgentHomeInvariantError as exc:
            reason = "stale_change" if "stale" in str(exc).casefold() else "home_failed"
            return _failed(execution, str(exc), reason=reason)
        except (MaintenanceContractError, MaintenanceInvariantError, AgentHomeError) as exc:
            return _failed(execution, str(exc), reason="home_failed")

    def _execute(
        self,
        state: _HomeTaskState,
        execution: ActionExecution,
    ) -> JsonObject:
        name = execution.call.action_name
        params = execution.call.params
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
            return self._change(_required_text(params, "token")).to_review_json()
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
            outcome = self._home.resolve_maintenance(
                _required_text(params, "token"),
                resolution,
                rewrite_text=(
                    _required_text(params, "text")
                    if resolution is HomeMaintenanceResolution.REWRITE
                    else None
                ),
            )
            state.resolved += 1
            return {
                "link": outcome.link,
                "resolution": outcome.resolution.value,
                "remaining_changes": outcome.remaining_changes,
            }
        if name == "maintenance.complete":
            snapshot = self._home.maintenance_snapshot()
            if snapshot.pending or self._home.maintenance_pending().pending:
                raise MaintenanceContractError(
                    "Home Maintenance still has unresolved runtime differences"
                )
            state.completed = True
            return {"completed": True, "task": "home"}
        raise MaintenanceContractError(f"Unknown Home Maintenance action: {name}")

    def _change(self, token: str):
        matches = tuple(
            change
            for change in self._home.maintenance_snapshot().changes
            if change.token == token
        )
        if len(matches) != 1:
            raise AgentHomeInvariantError(
                "Home Maintenance change token is stale or unknown"
            )
        return matches[0]

    def _require_state(self) -> _HomeTaskState:
        if self._state is None:
            raise MaintenanceInvariantError("No Home Maintenance task is active")
        return self._state


class HomeMaintenanceActionExecutor(ActionExecutor):
    def __init__(self, controller: HomeMaintenanceActionController) -> None:
        self._controller = controller

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        return self._controller.execute(execution, context)


def register_home_maintenance_actions(
    builder: ActionEngineBuilder,
    *,
    controller: HomeMaintenanceActionController,
) -> ActionEngineBuilder:
    executor = HomeMaintenanceActionExecutor(controller)
    for handler in HOME_MAINTENANCE_ACTIONS:
        builder.register_executor(handler, executor)
    return builder


def _required_text(params: JsonObject, name: str) -> str:
    value = params.get(name)
    if not isinstance(value, str) or not value:
        raise MaintenanceContractError(
            f"Home Maintenance parameter {name} must be non-empty text"
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
            scope="maintenance.home",
            disposition=ActionFailureDisposition.CHANGE_REQUEST,
            feedback=feedback,
        ),
    )
