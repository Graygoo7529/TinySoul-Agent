"""Session-owned semantic heap Action executor."""

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
from .errors import SessionError, SessionInspectRequestError


def register_session_actions(
    builder: ActionEngineBuilder,
    *,
    session: SessionEngine,
    runtime_bridge: RuntimeSessionBridge,
) -> ActionEngineBuilder:
    """Register the prior-Turn semantic heap inspector."""

    return builder.register_executor(
        "session.inspect",
        SessionInspectExecutor(session, runtime_bridge=runtime_bridge),
    )


class SessionInspectExecutor(ActionExecutor):
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
        raw_ref = execution.call.params.get("ref")
        if raw_ref is not None and (not isinstance(raw_ref, str) or not raw_ref):
            return _failed(
                execution,
                "core.session.inspect ref must be non-empty text",
                reason="invalid_ref",
            )
        action = execution.call.params.get("action")
        if action is not None and (not isinstance(action, str) or not action):
            return _failed(
                execution,
                "core.session.inspect action filter must be non-empty text",
                reason="invalid_ref",
            )
        continuation = execution.call.params.get("continuation")
        if continuation is not None and (
            not isinstance(continuation, str) or not continuation
        ):
            return _failed(
                execution,
                "core.session.inspect continuation must be an opaque string",
                reason="invalid_continuation",
            )
        try:
            payload = self._session.inspect(
                raw_ref,
                action=action,
                continuation=continuation,
            )
        except SessionInspectRequestError as exc:
            return _failed(
                execution,
                str(exc),
                reason=exc.reason.value,
                scope=exc.scope,
                constraint=exc.constraint,
            )
        except SessionError as exc:
            raise self._runtime_bridge.from_session_error(exc) from exc
        canonical: JsonObject = {"inspected": True}
        if raw_ref is not None:
            canonical["ref"] = raw_ref
        return ActionResult.success(
            call_id=execution.call.call_id,
            invoke_id=execution.framework.invoke_id,
            batch_id=execution.framework.batch_id,
            action_name=execution.call.action_name,
            sequence=execution.call.sequence,
            domain=execution.framework.domain,
            payload=payload,
            trace_projection=ActionTraceProjection(
                origin_refs=((raw_ref,) if raw_ref is not None else ()),
                canonical_payload=canonical,
            ),
        )


def _failed(
    execution: ActionExecution,
    feedback: str,
    *,
    reason: str,
    scope: str = "session.inspect",
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
