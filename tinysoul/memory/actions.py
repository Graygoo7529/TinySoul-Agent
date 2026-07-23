"""Memory search and recall action executors."""

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
)
from tinysoul.infra.json import JsonObject
from tinysoul.runtime.bridge import RuntimeMemoryBridge

from .engine import MemoryEngine
from .errors import MemoryContractError, MemoryError, MemoryInvariantError
from .search import MemorySearchReranker


def register_memory_actions(
    builder: ActionEngineBuilder,
    *,
    memory: MemoryEngine,
    runtime_bridge: RuntimeMemoryBridge,
    search_reranker: MemorySearchReranker | None = None,
) -> ActionEngineBuilder:
    builder.register_executor(
        "memory.search",
        MemorySearchExecutor(
            memory,
            reranker=search_reranker,
            runtime_bridge=runtime_bridge,
        ),
    )
    builder.register_executor(
        "memory.recall",
        MemoryRecallExecutor(memory, runtime_bridge=runtime_bridge),
    )
    return builder


class MemorySearchExecutor(ActionExecutor):
    def __init__(
        self,
        memory: MemoryEngine,
        *,
        reranker: MemorySearchReranker | None = None,
        runtime_bridge: RuntimeMemoryBridge | None = None,
    ) -> None:
        self._memory = memory
        self._reranker = reranker
        self._runtime_bridge = runtime_bridge or RuntimeMemoryBridge()

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        query = execution.call.params.get("query")
        top_k = execution.call.params.get("top_k")
        if not isinstance(query, str) or not query.strip():
            return _failed(execution, "memory.search requires a non-empty query", reason="invalid_query")
        if top_k is not None and (isinstance(top_k, bool) or not isinstance(top_k, int)):
            return _failed(execution, "memory.search top_k must be an integer", reason="invalid_top_k")
        try:
            result = self._memory.search(
                query,
                top_k=top_k if isinstance(top_k, int) else None,
                reranker=self._reranker,
                scope=execution.framework.scope,
            )
        except MemoryContractError as exc:
            return _failed(
                execution,
                f"Memory search failed: {exc}",
                reason="search_failed",
                frame_data={"error_type": type(exc).__name__},
            )
        except MemoryError as exc:
            raise self._runtime_bridge.from_memory_error(exc) from exc
        return ActionResult.success(
            call_id=execution.call.call_id,
            invoke_id=execution.framework.invoke_id,
            batch_id=execution.framework.batch_id,
            action_name=execution.call.action_name,
            sequence=execution.call.sequence,
            domain=execution.framework.domain,
            payload={
                "query": result.query,
                "top_k": result.top_k,
                "candidate_count": result.candidate_count,
                "reranked": result.reranked,
                "items": [item.to_json() for item in result.items],
            },
        )


class MemoryRecallExecutor(ActionExecutor):
    def __init__(
        self,
        memory: MemoryEngine,
        *,
        runtime_bridge: RuntimeMemoryBridge | None = None,
    ) -> None:
        self._memory = memory
        self._runtime_bridge = runtime_bridge or RuntimeMemoryBridge()

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        link = execution.call.params.get("memory_link")
        if not isinstance(link, str) or not link:
            return _failed(execution, "memory.recall requires memory_link", reason="invalid_link")
        try:
            result = self._memory.recall(link)
        except MemoryInvariantError as exc:
            raise self._runtime_bridge.from_memory_error(exc) from exc
        except MemoryContractError as exc:
            return _failed(
                execution,
                f"Memory recall failed: {exc}",
                reason="invalid_or_missing_memory",
            )
        except MemoryError as exc:
            raise self._runtime_bridge.from_memory_error(exc) from exc
        return ActionResult.success(
            call_id=execution.call.call_id,
            invoke_id=execution.framework.invoke_id,
            batch_id=execution.framework.batch_id,
            action_name=execution.call.action_name,
            sequence=execution.call.sequence,
            domain=execution.framework.domain,
            payload={
                "link": result.link,
                "date": result.day,
                "text": result.text,
                "digest": result.digest,
            },
        )


def _failed(
    execution: ActionExecution,
    feedback: str,
    *,
    reason: str,
    frame_data: JsonObject | None = None,
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
            scope="memory.action",
            disposition=ActionFailureDisposition.CHANGE_REQUEST,
            feedback=feedback,
        ),
        frame_data=frame_data,
    )
