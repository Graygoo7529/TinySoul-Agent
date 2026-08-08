"""User-turn Memory action executors."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

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
from tinysoul.runtime.bridge import RuntimeMemoryBridge

from .active import MemoryPatchOperation
from .catalog import MemoryInspectRequest
from .engine import MemoryEngine
from .errors import MemoryContractError, MemoryError, MemoryInvariantError
from .links import MemoryKind, MemoryLink


def register_memory_actions(
    builder: ActionEngineBuilder,
    *,
    memory: MemoryEngine,
    runtime_bridge: RuntimeMemoryBridge,
) -> ActionEngineBuilder:
    builder.register_executor("memory.memorize", MemoryMemorizeExecutor(memory, runtime_bridge))
    builder.register_executor("memory.inspect", MemoryInspectExecutor(memory, runtime_bridge))
    builder.register_executor("memory.recall", MemoryRecallExecutor(memory, runtime_bridge))
    return builder


class MemoryMemorizeExecutor(ActionExecutor):
    def __init__(self, memory: MemoryEngine, runtime_bridge: RuntimeMemoryBridge) -> None:
        self._memory = memory
        self._runtime_bridge = runtime_bridge

    def execute(self, execution: ActionExecution, context: ActionExecutionContext) -> ActionResult:
        del context
        params = execution.call.params
        expected = params.get("expected_digest")
        raw_operations = params.get("operations")
        if not isinstance(expected, str) or not isinstance(raw_operations, list):
            return _failed(execution, "core.memory.memorize requires expected_digest and operations", "invalid_patch")
        try:
            parsed_operations: list[MemoryPatchOperation] = []
            for item in raw_operations:
                if not isinstance(item, Mapping):
                    raise MemoryContractError("Memory patch operations must be objects")
                parsed_operations.append(
                    MemoryPatchOperation.from_mapping(
                        cast(Mapping[str, object], item)
                    )
                )
            operations = tuple(parsed_operations)
            snapshot = self._memory.patch_active(
                day=self._memory.active_day(),
                expected_digest=expected,
                operations=operations,
            )
        except MemoryContractError as exc:
            return _failed(execution, str(exc), "invalid_or_stale_patch")
        except MemoryError as exc:
            raise self._runtime_bridge.from_memory_error(exc) from exc
        payload = to_json_object({
            "ref": "memory:current",
            "revision": snapshot.document.revision,
            "digest": snapshot.digest,
            "changed": True,
            "cleared": not bool(snapshot.content),
            "chars": len(snapshot.content),
        })
        return _success(execution, payload)


class MemoryInspectExecutor(ActionExecutor):
    def __init__(self, memory: MemoryEngine, runtime_bridge: RuntimeMemoryBridge) -> None:
        self._memory = memory
        self._runtime_bridge = runtime_bridge

    def execute(self, execution: ActionExecution, context: ActionExecutionContext) -> ActionResult:
        del context
        params = execution.call.params
        try:
            request = _inspect_request(params)
            result = self._memory.inspect(request)
        except MemoryContractError as exc:
            return _failed(execution, str(exc), "invalid_inspect")
        except MemoryError as exc:
            raise self._runtime_bridge.from_memory_error(exc) from exc
        payload = result.to_json()
        refs: tuple[str, ...] = ()
        if request.memory_link is not None:
            refs = (str(request.memory_link),)
        return _success(
            execution,
            payload,
            trace_projection=ActionTraceProjection(
                origin_refs=refs,
                canonical_payload={
                    "mode": result.mode,
                    "candidate_count": result.candidate_count,
                    "selected": [item.link for item in result.items],
                },
            ),
        )


class MemoryRecallExecutor(ActionExecutor):
    def __init__(self, memory: MemoryEngine, runtime_bridge: RuntimeMemoryBridge) -> None:
        self._memory = memory
        self._runtime_bridge = runtime_bridge

    def execute(self, execution: ActionExecution, context: ActionExecutionContext) -> ActionResult:
        del context
        link = execution.call.params.get("memory_link")
        if not isinstance(link, str) or not link:
            return _failed(execution, "core.memory.recall requires memory_link", "invalid_link")
        try:
            result = self._memory.recall(link)
        except MemoryContractError as exc:
            return _failed(execution, str(exc), "invalid_or_missing_memory")
        except MemoryInvariantError as exc:
            raise self._runtime_bridge.from_memory_error(exc) from exc
        except MemoryError as exc:
            raise self._runtime_bridge.from_memory_error(exc) from exc
        payload = to_json_object({
            "link": result.link,
            "kind": result.kind,
            "cite": result.cite,
            "metadata": result.metadata,
            "markdown": result.content,
            "digest": result.digest,
            "resolution_chain": list(result.resolution_chain),
        })
        return _success(
            execution,
            payload,
            trace_projection=ActionTraceProjection(
                origin_refs=(result.link,),
                canonical_payload={
                    "link": result.link,
                    "kind": result.kind,
                    "digest": result.digest,
                    "resolution_chain": list(result.resolution_chain),
                },
            ),
        )


def _inspect_request(params: JsonObject) -> MemoryInspectRequest:
    query = params.get("query")
    raw_link = params.get("memory_link")
    link = MemoryLink.parse(raw_link) if isinstance(raw_link, str) else None
    raw_kinds = params.get("kinds", [])
    if not isinstance(raw_kinds, list) or any(not isinstance(item, str) for item in raw_kinds):
        raise MemoryContractError("core.memory.inspect kinds must be a list of strings")
    try:
        kinds = tuple(MemoryKind(item) for item in raw_kinds)
    except ValueError as exc:
        raise MemoryContractError("core.memory.inspect contains an invalid kind") from exc
    limit = params.get("limit")
    continuation = params.get("continuation")
    if continuation is not None and not isinstance(continuation, str):
        raise MemoryContractError("core.memory.inspect continuation must be text")
    if query is not None and not isinstance(query, str):
        raise MemoryContractError("core.memory.inspect query must be text")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int)):
        raise MemoryContractError("core.memory.inspect limit must be an integer")
    return MemoryInspectRequest(
        query=query,
        memory_link=link,
        kinds=kinds,
        limit=limit,
        continuation=continuation,
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


def _failed(execution: ActionExecution, feedback: str, reason: str) -> ActionResult:
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
    )
