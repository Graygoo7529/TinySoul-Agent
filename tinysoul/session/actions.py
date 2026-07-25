"""Session-owned history actions."""

from __future__ import annotations

from tinysoul.action import (
    ActionEngineBuilder,
    ActionExecution,
    ActionExecutionContext,
    ActionExecutor,
    ActionFailureDisposition,
    ActionLocalFailure,
    ActionResult,
    ActionResultStage,
    ActionTraceProjection,
)
from tinysoul.infra.json import JsonObject
from tinysoul.runtime.bridge import RuntimeSessionBridge

from .engine import SessionEngine
from .errors import (
    SessionError,
    SessionHistoryFailureReason,
    SessionHistoryRequestError,
)


def register_session_actions(
    builder: ActionEngineBuilder,
    *,
    session: SessionEngine,
    runtime_bridge: RuntimeSessionBridge,
) -> ActionEngineBuilder:
    return (
        builder.register_executor(
            "session.history.inspect",
            SessionHistoryInspectExecutor(session, runtime_bridge=runtime_bridge),
        )
        .register_executor(
            "session.history.recall",
            SessionHistoryRecallExecutor(session, runtime_bridge=runtime_bridge),
        )
    )


class SessionHistoryInspectExecutor(ActionExecutor):
    def __init__(
        self,
        session: SessionEngine,
        *,
        runtime_bridge: RuntimeSessionBridge,
    ) -> None:
        self._session = session
        self._runtime_bridge = runtime_bridge

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        ref = execution.call.params.get("ref")
        if ref is not None and (not isinstance(ref, str) or not ref):
            return _failed(
                execution,
                "session.history.inspect ref must be non-empty text",
                reason=SessionHistoryFailureReason.INVALID_REF.value,
                scope="session.history.inspect",
            )
        action = execution.call.params.get("action")
        if action is not None and (not isinstance(action, str) or not action):
            return _failed(
                execution,
                "session.history.inspect action must be non-empty text",
                reason=SessionHistoryFailureReason.INVALID_REF.value,
                scope="session.history.inspect",
            )
        cursor = execution.call.params.get("cursor")
        if cursor is not None and not isinstance(cursor, dict):
            return _failed(
                execution,
                "session.history.inspect cursor must be a continuation object",
                reason=SessionHistoryFailureReason.INVALID_CURSOR.value,
                scope="session.history.inspect",
            )
        try:
            payload = self._session.inspect_model_history(
                ref,
                action=action,
                cursor=cursor,
            )
            return _success(
                execution,
                payload,
                trace_projection=ActionTraceProjection(
                    origin_refs=(ref,) if isinstance(ref, str) else (),
                    canonical_payload={
                        "origin_ref": ref or "session:head",
                        "next_cursor": payload.get("next_cursor"),
                        "folded": True,
                    },
                ),
            )
        except SessionHistoryRequestError as exc:
            return _failed_request(execution, exc)
        except SessionError as exc:
            raise self._runtime_bridge.from_session_error(exc) from exc


class SessionHistoryRecallExecutor(ActionExecutor):
    def __init__(
        self,
        session: SessionEngine,
        *,
        runtime_bridge: RuntimeSessionBridge,
    ) -> None:
        self._session = session
        self._runtime_bridge = runtime_bridge

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        ref = execution.call.params.get("ref")
        if not isinstance(ref, str) or not ref:
            return _failed(
                execution,
                "session.history.recall ref must be non-empty text",
                reason=SessionHistoryFailureReason.INVALID_REF.value,
                scope="session.history.recall",
            )
        cursor = execution.call.params.get("cursor")
        if cursor is not None and not isinstance(cursor, dict):
            return _failed(
                execution,
                "session.history.recall cursor must be a continuation object",
                reason=SessionHistoryFailureReason.INVALID_CURSOR.value,
                scope="session.history.recall",
            )
        try:
            payload = self._session.recall_model_action(
                ref,
                cursor=cursor,
            )
        except SessionHistoryRequestError as exc:
            return _failed_request(execution, exc)
        except SessionError as exc:
            raise self._runtime_bridge.from_session_error(exc) from exc
        return _success(
            execution,
            payload,
            trace_projection=ActionTraceProjection(
                origin_refs=(ref,),
                canonical_payload={
                    "origin_ref": ref,
                    "next_cursor": payload.get("next_cursor"),
                    "folded": True,
                },
            ),
        )


def _success(
    execution: ActionExecution,
    payload: JsonObject,
    *,
    trace_projection: ActionTraceProjection | None = None,
) -> ActionResult:
    return ActionResult.success(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        payload=payload,
        trace_projection=trace_projection,
    )


def _failed_request(
    execution: ActionExecution,
    error: SessionHistoryRequestError,
) -> ActionResult:
    if error.reason is SessionHistoryFailureReason.REVISION_CHANGED:
        return _failed(
            execution,
            "Session history changed; restart active-head inspection without a cursor.",
            reason=error.reason.value,
            scope=error.scope,
            constraint={"restart": "active_head"},
        )
    return _failed(
        execution,
        str(error),
        reason=error.reason.value,
        scope=error.scope,
        constraint=error.constraint,
    )


def _failed(
    execution: ActionExecution,
    feedback: str,
    *,
    reason: str,
    scope: str = "session.history",
    constraint: JsonObject | None = None,
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
            scope=scope,
            disposition=ActionFailureDisposition.CHANGE_REQUEST,
            feedback=feedback,
            constraint=constraint or {},
        ),
    )
