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
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.runtime.bridge import RuntimeSessionBridge

from .background import project_model_background
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
        .register_executor(
            "session.history.actions",
            SessionHistoryActionsExecutor(session, runtime_bridge=runtime_bridge),
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
        max_chars = execution.call.params.get("max_chars")
        if max_chars is not None and (
            isinstance(max_chars, bool)
            or not isinstance(max_chars, int)
            or max_chars <= 0
        ):
            return _failed(
                execution,
                "session.history.inspect max_chars must be a positive integer",
                reason=SessionHistoryFailureReason.INVALID_MAX_CHARS.value,
                scope="session.history.inspect",
            )
        max_entries = execution.call.params.get("max_entries")
        if max_entries is not None and (
            isinstance(max_entries, bool)
            or not isinstance(max_entries, int)
            or max_entries <= 0
        ):
            return _failed(
                execution,
                "session.history.inspect max_entries must be a positive integer",
                reason=SessionHistoryFailureReason.INVALID_MAX_ENTRIES.value,
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
            payload = self._session.inspect_history(
                ref,
                max_chars=max_chars,
                max_entries=max_entries,
                cursor=cursor,
            )
            return _success(
                execution,
                _model_history_payload(payload),
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
        max_chars = execution.call.params.get("max_chars")
        if max_chars is not None and (
            isinstance(max_chars, bool)
            or not isinstance(max_chars, int)
            or max_chars <= 0
        ):
            return _failed(
                execution,
                "session.history.recall max_chars must be a positive integer",
                reason=SessionHistoryFailureReason.INVALID_MAX_CHARS.value,
                scope="session.history.recall",
            )
        max_entries = execution.call.params.get("max_entries")
        if max_entries is not None and (
            isinstance(max_entries, bool)
            or not isinstance(max_entries, int)
            or max_entries <= 0
        ):
            return _failed(
                execution,
                "session.history.recall max_entries must be a positive integer",
                reason=SessionHistoryFailureReason.INVALID_MAX_ENTRIES.value,
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
            payload = self._session.recall_history(
                ref,
                max_chars=max_chars,
                max_entries=max_entries,
                cursor=cursor,
            )
        except SessionHistoryRequestError as exc:
            return _failed_request(execution, exc)
        except SessionError as exc:
            raise self._runtime_bridge.from_session_error(exc) from exc
        return _success(
            execution,
            _model_history_payload(payload),
            trace_projection=ActionTraceProjection(
                origin_refs=(ref,),
                canonical_payload={
                    "origin_ref": ref,
                    "next_cursor": payload["next_cursor"],
                    "folded": True,
                },
            ),
        )


class SessionHistoryActionsExecutor(ActionExecutor):
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
                "session.history.actions ref must be non-empty text",
                reason=SessionHistoryFailureReason.INVALID_REF.value,
                scope="session.history.actions",
            )
        cursor = execution.call.params.get("cursor", 0)
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
            return _failed(
                execution,
                "session.history.actions cursor must be a non-negative integer",
                reason=SessionHistoryFailureReason.INVALID_CURSOR.value,
                scope="session.history.actions",
            )
        max_items = execution.call.params.get("max_items")
        if max_items is not None and (
            isinstance(max_items, bool)
            or not isinstance(max_items, int)
            or max_items <= 0
        ):
            return _failed(
                execution,
                "session.history.actions max_items must be a positive integer",
                reason=SessionHistoryFailureReason.INVALID_MAX_ITEMS.value,
                scope="session.history.actions",
            )
        try:
            payload = self._session.action_history(
                ref,
                cursor=cursor,
                max_items=max_items,
            )
        except SessionHistoryRequestError as exc:
            return _failed_request(execution, exc)
        except SessionError as exc:
            raise self._runtime_bridge.from_session_error(exc) from exc
        model_payload = _model_history_payload(payload)
        return _success(
            execution,
            model_payload,
            trace_projection=ActionTraceProjection(
                origin_refs=(ref,),
                canonical_payload={
                    "source": model_payload["source"],
                    "summary": model_payload["summary"],
                    "coverage": model_payload["coverage"],
                    "next_cursor": model_payload["next_cursor"],
                    "page_complete": model_payload["page_complete"],
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


def _model_history_payload(payload: JsonObject) -> JsonObject:
    """Project Session query facts for Agent use without integrity metadata."""

    value = to_json_object(payload)
    source = value.get("source")
    if isinstance(source, dict):
        source.pop("revision", None)
        source.pop("trace_digest", None)
    summary = value.get("summary")
    if isinstance(summary, dict):
        summary.pop("trace_digest", None)
    items = value.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            preview = item.get("preview")
            if isinstance(preview, dict):
                item["preview"] = project_model_background(preview)
    return value


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
