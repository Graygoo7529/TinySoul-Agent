"""Context-owned action executors."""

from __future__ import annotations

from tinysoul.kernel.action import (
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
from tinysoul.kernel.context.runtime_bridge import RuntimeContextBridge
from tinysoul.kernel.action.tasks import ActionTaskFactory
from tinysoul.kernel.retrieval.operations import SearchSession
from tinysoul.kernel.retrieval.requests import parse_retrieval_request
from tinysoul.kernel.retrieval.contracts import SearchFailure, SearchContext, RetrievalRequest, ModelStep

from .engine import ContextEngine
from .errors import (
    ContextError,
    ContextInspectFailureReason,
    ContextInspectRequestError,
)


def register_context_actions(
    builder: ActionEngineBuilder,
    *,
    context: ContextEngine,
    runtime_bridge: RuntimeContextBridge,
    queries: SearchSession | None = None,
    tasks: ActionTaskFactory | None = None,
) -> ActionEngineBuilder:
    """Register the current-Turn semantic heap inspector."""

    builder.register_executor(
        "core.context.inspect",
        ContextInspectExecutor(context, runtime_bridge=runtime_bridge),
        executor_id="context.inspect",
    )
    if queries is not None and tasks is not None:
        builder.register_executor(
            "core.context.search", ContextSearchExecutor(queries, tasks, runtime_bridge)
        )
    return builder


class ContextSearchExecutor(ActionExecutor):
    def __init__(
        self,
        queries: SearchSession,
        tasks: ActionTaskFactory,
        bridge: RuntimeContextBridge,
    ) -> None:
        self._queries, self._tasks, self._bridge = queries, tasks, bridge

    async def execute(
        self, execution: ActionExecution, context: ActionExecutionContext
    ) -> ActionResult:
        try:
            request = parse_retrieval_request(execution.call.params, self._queries.retrieval_policies[0])
            if isinstance(request, str):
                page = await self._queries.search(request)
            else:
                use_context = (
                    any(isinstance(step, ModelStep) and step.context is SearchContext.CURRENT for step in request.steps)

                )
                inputs = await self._tasks.selection_input(
                    execution,
                    include_context=use_context,
                    control=context.control,
                )
                page = await self._queries.search(request, inputs=inputs)
        except SearchFailure as exc:
            return _failed(
                execution, str(exc), reason=exc.kind.value, scope="context.search"
            )
        except ContextInspectRequestError as exc:
            return _failed_request(execution, exc)
        except ContextError as exc:
            raise self._bridge.from_context_error(exc) from exc
        return _success(
            execution,
            page.to_json(),
            trace_projection=ActionTraceProjection(
                origin_refs=tuple(item.ref for item in page.items),
                canonical_payload={
                    "source": page.source.value,
                    "selected": [item.ref for item in page.items],
                },
            ),
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

    async def execute(
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
                reason=ContextInspectFailureReason.INVALID_CONTINUATION.value,
            )
        try:
            query = execution.call.params.get("query")
            if query is not None and (not isinstance(query, str) or not query.strip()):
                return _failed(
                    execution, "Query must be non-empty text", reason="invalid_query"
                )
            payload = await self._context.inspect(
                ref, query=query, continuation=continuation
            )
        except ContextInspectRequestError as exc:
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
    error: ContextInspectRequestError,
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
