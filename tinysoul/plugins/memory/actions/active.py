"""User-turn Memory action executors."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

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
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.plugins.memory.runtime_bridge import RuntimeMemoryBridge
from tinysoul.runtime import Signal

from ..storage.active import MemoryPatchOperation
from ..background import MEMORY_CONTEXT_UPDATE
from tinysoul.infra.continuation import ContinuationError
from tinysoul.kernel.action.tasks import ActionTaskFactory
from tinysoul.kernel.retrieval.contracts import SearchContext, SearchFailure, RetrievalRequest, ModelStep
from tinysoul.kernel.retrieval.operations import SelectionInput
from tinysoul.kernel.retrieval.requests import parse_retrieval_request
from ..services import MemoryReadService, MemoryService
from ..errors import MemoryContractError, MemoryError, MemoryInvariantError
from ..links import MemoryKind, MemoryLink


def register_memory_actions(
    builder: ActionEngineBuilder,
    *,
    memory: MemoryReadService,
    runtime_bridge: RuntimeMemoryBridge,
    tasks: ActionTaskFactory | None = None,
) -> ActionEngineBuilder:
    if isinstance(memory, MemoryService):
        builder.register_executor(
            "memory.memorize", MemoryMemorizeExecutor(memory, runtime_bridge)
        )
    builder.register_executor(
        "memory.inspect", MemoryInspectExecutor(memory, runtime_bridge)
    )
    builder.register_executor(
        "memory.search", MemorySearchExecutor(memory, runtime_bridge, tasks)
    )
    return builder


class MemoryMemorizeExecutor(ActionExecutor):
    def __init__(
        self, memory: MemoryService, runtime_bridge: RuntimeMemoryBridge
    ) -> None:
        self._memory = memory
        self._runtime_bridge = runtime_bridge

    async def execute(
        self, execution: ActionExecution, context: ActionExecutionContext
    ) -> ActionResult:
        memory = self._memory.using(context.owner_operations)
        bus = context.require_signal_bus()
        params = execution.call.params
        raw_operations = params.get("operations")
        if not isinstance(raw_operations, list):
            return _failed(
                execution, "memory.memorize requires operations", "invalid_patch"
            )
        try:
            parsed_operations: list[MemoryPatchOperation] = []
            for item in raw_operations:
                if not isinstance(item, Mapping):
                    raise MemoryContractError("Memory patch operations must be objects")
                parsed_operations.append(
                    MemoryPatchOperation.from_mapping(cast(Mapping[str, object], item))
                )
            operations = tuple(parsed_operations)
            snapshot = await memory.patch_active(
                day=await memory.active_day(),
                operations=operations,
            )
        except MemoryContractError as exc:
            return _failed(execution, str(exc), "invalid_patch")
        except MemoryError as exc:
            raise self._runtime_bridge.from_memory_error(exc) from exc
        payload = to_json_object(
            {
                "ref": "memory:current",
                "changed": True,
                "cleared": not bool(snapshot.content),
                "chars": len(snapshot.content),
            }
        )
        bus.emit(
            Signal(
                name=MEMORY_CONTEXT_UPDATE,
                source="memory.memorize",
                scope=execution.framework.scope,
                payload={"refresh": True},
            )
        )
        return _success(execution, payload)


class MemorySearchExecutor(ActionExecutor):
    def __init__(
        self,
        memory: MemoryReadService,
        runtime_bridge: RuntimeMemoryBridge,
        tasks: ActionTaskFactory | None = None,
    ) -> None:
        self._memory, self._runtime_bridge, self._tasks = memory, runtime_bridge, tasks

    async def execute(
        self, execution: ActionExecution, context: ActionExecutionContext
    ) -> ActionResult:
        memory = self._memory.using(context.owner_operations)
        try:
            request = parse_retrieval_request(execution.call.params, memory.retrieval_policies[0])
            inputs = SelectionInput()
            if not isinstance(request, str) and self._tasks is not None:
                use_context = (
                    any(isinstance(step, ModelStep) and step.context is SearchContext.CURRENT for step in request.steps)

                )
                inputs = await self._tasks.selection_input(
                    execution,
                    include_context=use_context,
                    control=context.control,
                )
            result = await memory.search(request, inputs=inputs)
        except SearchFailure as exc:
            return _failed(execution, str(exc), exc.kind.value)
        except MemoryContractError as exc:
            return _failed(execution, str(exc), "invalid_search")
        except MemoryError as exc:
            raise self._runtime_bridge.from_memory_error(exc) from exc
        return _success(
            execution,
            result.to_json(),
            trace_projection=ActionTraceProjection(
                origin_refs=tuple(item.ref for item in result.items),
                canonical_payload={
                    "source": result.source.value,
                    "selected": [item.ref for item in result.items],
                },
            ),
        )


class MemoryInspectExecutor(ActionExecutor):
    def __init__(
        self, memory: MemoryReadService, runtime_bridge: RuntimeMemoryBridge
    ) -> None:
        self._memory, self._runtime_bridge = memory, runtime_bridge

    async def execute(
        self, execution: ActionExecution, context: ActionExecutionContext
    ) -> ActionResult:
        memory = self._memory.using(context.owner_operations)
        params = execution.call.params
        ref, view = params.get("ref"), params.get("view", "content")
        continuation, max_chars = params.get("continuation"), params.get("max_chars")
        if (
            not isinstance(ref, str)
            or not isinstance(view, str)
            or (continuation is not None and not isinstance(continuation, str))
            or (
                max_chars is not None and (type(max_chars) is not int or max_chars <= 0)
            )
        ):
            return _failed(
                execution,
                "Inspect requires a known ref and valid content page options",
                "invalid_inspect",
            )
        try:
            result = await memory.inspect(
                ref, view=view, continuation=continuation, max_chars=max_chars
            )
        except (MemoryContractError, SearchFailure, ContinuationError) as exc:
            return _failed(execution, str(exc), "invalid_inspect")
        except MemoryError as exc:
            raise self._runtime_bridge.from_memory_error(exc) from exc
        return _success(
            execution,
            result,
            trace_projection=ActionTraceProjection(
                origin_refs=(ref,),
                canonical_payload={"ref": ref, "view": view},
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
