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
from tinysoul.infra.json import JsonObject, to_json_object
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
    """Register TurnTrace heap actions."""

    return (
        builder.register_executor(
            "context.trace.inspect",
            ContextTraceInspectExecutor(context, runtime_bridge=runtime_bridge),
        )
        .register_executor(
            "context.trace.recall",
            ContextTraceRecallExecutor(context, runtime_bridge=runtime_bridge),
        )
        .register_executor(
            "context.trace.fold",
            ContextTraceFoldExecutor(context, runtime_bridge=runtime_bridge),
        )
    )


class ContextTraceInspectExecutor(ActionExecutor):
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
                "context.trace.inspect requires a non-empty ref",
                reason="invalid_ref",
            )
        try:
            payload = self._context.inspect_trace(ref)
        except ContextTraceRequestError as exc:
            return _failed_request(execution, exc)
        except ContextError as exc:
            raise self._runtime_bridge.from_context_error(exc) from exc
        return _success(execution, payload)


class ContextTraceRecallExecutor(ActionExecutor):
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
                "context.trace.recall requires a non-empty ref",
                reason=ContextTraceFailureReason.INVALID_REF.value,
            )
        max_chars = execution.call.params.get("max_chars")
        if max_chars is not None and (
            isinstance(max_chars, bool)
            or not isinstance(max_chars, int)
            or max_chars <= 0
        ):
            return _failed(
                execution,
                "context.trace.recall max_chars must be a positive integer",
                reason=ContextTraceFailureReason.INVALID_MAX_CHARS.value,
            )
        max_entries = execution.call.params.get("max_entries")
        if max_entries is not None and (
            isinstance(max_entries, bool)
            or not isinstance(max_entries, int)
            or max_entries <= 0
        ):
            return _failed(
                execution,
                "context.trace.recall max_entries must be a positive integer",
                reason=ContextTraceFailureReason.INVALID_MAX_ENTRIES.value,
            )
        cursor = execution.call.params.get("cursor")
        if cursor is not None and not isinstance(cursor, dict):
            return _failed(
                execution,
                "context.trace.recall cursor must be a continuation object",
                reason=ContextTraceFailureReason.INVALID_CURSOR.value,
            )
        try:
            payload = self._context.recall_trace(
                ref,
                max_chars=max_chars,
                max_entries=max_entries,
                cursor=cursor,
            )
        except ContextTraceRequestError as exc:
            return _failed_request(execution, exc)
        except ContextError as exc:
            raise self._runtime_bridge.from_context_error(exc) from exc
        return _success(
            execution,
            payload,
            trace_projection=ActionTraceProjection(
                origin_refs=(ref,),
                canonical_payload={
                    "origin_ref": ref,
                    "entry_count": payload["entry_count"],
                    "next_cursor": payload["next_cursor"],
                    "folded": True,
                },
            ),
        )


class ContextTraceFoldExecutor(ActionExecutor):
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
        try:
            folded = self._context.fold_trace_overlays()
        except ContextError as exc:
            raise self._runtime_bridge.from_context_error(exc) from exc
        return _success(execution, {"folded_overlay_count": folded})


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
    scope: str = "context.trace",
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
