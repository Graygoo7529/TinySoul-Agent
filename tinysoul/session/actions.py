"""Session-owned history actions."""

from __future__ import annotations

from tinysoul.action import (
    ActionEngineBuilder,
    ActionExecution,
    ActionExecutionContext,
    ActionExecutor,
    ActionResult,
    ActionResultStage,
    ActionTraceMode,
    ActionTraceProjection,
)
from tinysoul.infra.json import JsonObject

from .engine import SessionEngine
from .errors import SessionError


def register_session_actions(
    builder: ActionEngineBuilder,
    *,
    session: SessionEngine,
) -> ActionEngineBuilder:
    return (
        builder.register_executor(
            "session.history.inspect",
            SessionHistoryInspectExecutor(session),
        )
        .register_executor(
            "session.history.recall",
            SessionHistoryRecallExecutor(session),
        )
    )


class SessionHistoryInspectExecutor(ActionExecutor):
    def __init__(self, session: SessionEngine) -> None:
        self._session = session

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        try:
            return _success(execution, self._session.inspect_history())
        except SessionError as exc:
            return _failed(execution, f"Session history inspection failed: {exc}")


class SessionHistoryRecallExecutor(ActionExecutor):
    def __init__(self, session: SessionEngine) -> None:
        self._session = session

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        ref = execution.call.params.get("ref")
        if not isinstance(ref, str) or not ref:
            return _failed(execution, "session.history.recall requires a non-empty ref")
        max_chars = execution.call.params.get("max_chars")
        if max_chars is not None and (
            isinstance(max_chars, bool)
            or not isinstance(max_chars, int)
            or max_chars <= 0
        ):
            return _failed(
                execution,
                "session.history.recall max_chars must be a positive integer",
            )
        cursor = execution.call.params.get("cursor", 0)
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
            return _failed(
                execution,
                "session.history.recall cursor must be a non-negative integer",
            )
        try:
            payload = self._session.recall_history(
                ref,
                max_chars=max_chars,
                cursor=cursor,
            )
        except SessionError as exc:
            return _failed(execution, f"Session history recall failed: {exc}")
        return _success(
            execution,
            payload,
            trace_projection=ActionTraceProjection(
                mode=ActionTraceMode.FOLDABLE,
                origin_ref=ref,
                compact_payload={
                    "origin_ref": ref,
                    "next_cursor": payload["next_cursor"],
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


def _failed(execution: ActionExecution, feedback: str) -> ActionResult:
    return ActionResult.failed(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        stage=ActionResultStage.EXECUTE,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        model_feedback=feedback,
    )
