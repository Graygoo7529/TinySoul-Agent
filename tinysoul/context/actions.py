"""Context-owned action executors."""

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
from tinysoul.runtime.bridge import RuntimeContextBridge

from .engine import ContextEngine
from .errors import (
    ContextError,
    ContextTraceFailureReason,
    ContextTraceRequestError,
)


def register_context_actions(
    builder: ActionEngineBuilder,
    *,
    context: ContextEngine,
    runtime_bridge: RuntimeContextBridge,
) -> ActionEngineBuilder:
    """Register the current-Turn semantic heap inspector."""

    return builder.register_executor(
        "context.inspect",
        ContextInspectExecutor(context, runtime_bridge=runtime_bridge),
    )


class ContextInspectExecutor(ActionExecutor):
    def __init__(
        self,
        context: ContextEngine,
        *,
        runtime_bridge: RuntimeContextBridge,
    ) -> None:
        self._context = context
        self._runtime_bridge = runtime_bridge

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        ref = _required_ref(execution)
        if ref is None:
            return _failed(
                execution,
                "core.context.inspect requires a non-empty ref",
                reason="invalid_ref",
            )
        continuation = execution.call.params.get("continuation")
        if continuation is not None and (
            not isinstance(continuation, str) or not continuation
        ):
            return _failed(
                execution,
                "core.context.inspect continuation must be a non-empty opaque string",
                reason=ContextTraceFailureReason.INVALID_CONTINUATION.value,
            )
        try:
            payload = self._context.inspect_trace(ref, continuation=continuation)
        except ContextTraceRequestError as exc:
            return _failed_request(execution, exc)
        except ContextError as exc:
            raise self._runtime_bridge.from_context_error(exc) from exc
        canonical_payload: JsonObject = {"ref": ref, "inspected": True}
        return _success(
            execution,
            payload,
            trace_projection=ActionTraceProjection(
                origin_refs=(ref,),
                canonical_payload=canonical_payload,
            ),
        )


def _required_ref(execution: ActionExecution) -> str | None:
    value = execution.call.params.get("ref")
    return value if isinstance(value, str) and value else None


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
    error: ContextTraceRequestError,
) -> ActionResult:
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
    scope: str = "context.inspect",
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
