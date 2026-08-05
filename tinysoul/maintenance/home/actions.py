"""Home Maintenance action state and owner-bound executors."""

from __future__ import annotations

from dataclasses import dataclass, field
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
from tinysoul.home import (
    AgentHomeEngine,
    HomeReviewChange,
    HomeReviewResolution,
    HomeSkillReview,
)
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
    inspected_tokens: set[str] = field(default_factory=set)


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
                pending = self._home.review_pending()
                if pending.pending:
                    raise MaintenanceInvariantError(
                        "Home Maintenance completed with unresolved runtime differences"
                    )
                removed = self._home.remove_resolved_overlay()
                return {
                    "resolved": state.resolved,
                    "remaining_reviews": 0,
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
            snapshot = self._home.review_snapshot()
            return {
                "count": len(snapshot.reviews),
                "items": [_review_summary(review) for review in snapshot.reviews],
            }
        if name == "maintenance.home.inspect":
            review = self._review(_required_text(params, "token"))
            state.inspected_tokens.add(review.token)
            return review.to_review_json()
        if name in {
            "maintenance.home.accept",
            "maintenance.home.reject",
            "maintenance.home.rewrite",
        }:
            resolution = {
                "maintenance.home.accept": HomeReviewResolution.ACCEPT,
                "maintenance.home.reject": HomeReviewResolution.REJECT,
                "maintenance.home.rewrite": HomeReviewResolution.REWRITE,
            }[name]
            token = _required_text(params, "token")
            if token not in state.inspected_tokens:
                raise MaintenanceContractError(
                    "Home Maintenance review must be inspected before resolution"
                )
            outcome = self._home.resolve_review(
                token,
                resolution,
                rewrite_text=(
                    _required_text(params, "text")
                    if resolution is HomeReviewResolution.REWRITE
                    else None
                ),
            )
            state.inspected_tokens.discard(token)
            state.resolved += 1
            return {
                "link": outcome.link,
                "resolution": outcome.resolution.value,
                "remaining_reviews": outcome.remaining_reviews,
            }
        if name == "maintenance.complete":
            snapshot = self._home.review_snapshot()
            if snapshot.pending or self._home.review_pending().pending:
                raise MaintenanceContractError(
                    "Home Maintenance still has unresolved reviews"
                )
            state.completed = True
            return {"completed": True, "task": "home"}
        raise MaintenanceContractError(f"Unknown Home Maintenance action: {name}")

    def _review(self, token: str):
        matches = tuple(
            review
            for review in self._home.review_snapshot().reviews
            if review.token == token
        )
        if len(matches) != 1:
            raise AgentHomeInvariantError(
                "Home Maintenance review token is stale or unknown"
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


def _review_summary(review: HomeReviewChange | HomeSkillReview) -> JsonObject:
    if isinstance(review, HomeReviewChange):
        return {
            "kind": "change",
            "token": review.token,
            "link": review.link,
            "state": review.state.value,
            "baseline_digest": review.baseline_digest,
            "runtime_digest": review.runtime_digest,
            "actual_digest": review.actual_digest,
            "allowed_resolutions": ["accept", "reject", "rewrite"],
        }
    return {
        "kind": "skill_review",
        "token": review.token,
        "link": review.link,
        "skill": review.skill,
        "actual_digest": review.actual_digest,
        "skill_memory_digest": review.skill_memory.digest,
        "allowed_resolutions": ["reject", "rewrite"],
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
