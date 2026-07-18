"""Context-owned action executors."""

from __future__ import annotations

from tinysoul.action import (
    ActionEngineBuilder,
    ActionExecution,
    ActionExecutionContext,
    ActionExecutor,
    ActionResult,
    ActionResultStage,
    ActionTraceProjection,
)
from tinysoul.infra.json import JsonObject, to_json_object

from .engine import ContextEngine
from .errors import ContextError


def register_context_actions(
    builder: ActionEngineBuilder,
    *,
    context: ContextEngine,
) -> ActionEngineBuilder:
    """Register TurnTrace heap actions."""

    return (
        builder.register_executor(
            "context.trace.inspect",
            ContextTraceInspectExecutor(context),
        )
        .register_executor(
            "context.trace.recall",
            ContextTraceRecallExecutor(context),
        )
        .register_executor(
            "context.trace.fold",
            ContextTraceFoldExecutor(context),
        )
    )


class ContextTraceInspectExecutor(ActionExecutor):
    def __init__(self, context: ContextEngine) -> None:
        self._context = context

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        ref = _required_ref(execution)
        if ref is None:
            return _failed(execution, "context.trace.inspect requires a non-empty ref")
        try:
            payload = self._context.inspect_trace(ref)
        except ContextError as exc:
            return _failed(execution, f"Trace inspect failed: {exc}")
        return _success(execution, payload)


class ContextTraceRecallExecutor(ActionExecutor):
    def __init__(self, context: ContextEngine) -> None:
        self._context = context

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        ref = _required_ref(execution)
        if ref is None:
            return _failed(execution, "context.trace.recall requires a non-empty ref")
        max_chars = execution.call.params.get("max_chars")
        if max_chars is not None and (
            isinstance(max_chars, bool)
            or not isinstance(max_chars, int)
            or max_chars <= 0
        ):
            return _failed(
                execution,
                "context.trace.recall max_chars must be a positive integer",
            )
        cursor = execution.call.params.get("cursor", 0)
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
            return _failed(
                execution,
                "context.trace.recall cursor must be a non-negative integer",
            )
        try:
            payload = self._context.recall_trace(
                ref,
                max_chars=max_chars,
                cursor=cursor,
            )
        except ContextError as exc:
            return _failed(execution, f"Trace recall failed: {exc}")
        return _success(
            execution,
            payload,
            trace_projection=ActionTraceProjection(
                origin_refs=(ref,),
                compact_payload={
                    "origin_ref": ref,
                    "entry_count": payload["entry_count"],
                    "next_cursor": payload["next_cursor"],
                    "folded": True,
                },
            ),
        )


class ContextTraceFoldExecutor(ActionExecutor):
    def __init__(self, context: ContextEngine) -> None:
        self._context = context

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        try:
            folded = self._context.fold_trace_overlays()
        except ContextError as exc:
            return _failed(execution, f"Trace fold failed: {exc}")
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
