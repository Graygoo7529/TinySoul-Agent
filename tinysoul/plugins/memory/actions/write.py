"""Memory Reflection actions: one validated document per accepted write."""

from __future__ import annotations

from datetime import date

from tinysoul.kernel.action import (
    ActionEngineBuilder,
    ActionExecution,
    ActionExecutionContext,
    ActionResult,
    ActionExecutor,
    ActionResultStage,
    ActionLocalFailure,
    ActionFailureDisposition,
)
from tinysoul.infra.json import JsonObject
from tinysoul.infra.time import CalendarDay
from ..documents import DailyMemoryDocument
from ..links import MemoryLink, MemoryKind
from tinysoul.plugins.memory.services import MemoryKnowledgeService
from tinysoul.plugins.memory.errors import MemoryContractError, MemoryError
from tinysoul.plugins.memory.runtime_bridge import RuntimeMemoryBridge

from ..errors import MemoryInvariantError

MEMORY_WRITE_ACTIONS = ("memory.write_daily", "memory.write")


class MemoryWriteSession:
    """Bind the Reflection target; all persistent facts remain with Memory."""

    def __init__(self, *, memory: MemoryKnowledgeService) -> None:
        self._memory = memory
        self._target_day: date | None = None

    def begin(self, *, target_day: CalendarDay) -> None:
        if self._target_day is not None:
            raise MemoryInvariantError("A Memory Reflection is already active")
        self._target_day = target_day.value

    def finish(self) -> JsonObject:
        day = self.target_day()
        self._target_day = None
        return {"target_day": day.isoformat()}

    def abort(self) -> None:
        self._target_day = None

    def target_day(self) -> date:
        if self._target_day is None:
            raise MemoryInvariantError("No Memory Reflection is active")
        return self._target_day

    async def write(
        self, execution: ActionExecution, context: ActionExecutionContext
    ) -> ActionResult:
        memory = self._memory.using(context.owner_operations)
        day = self.target_day()
        params = execution.call.params
        markdown = params.get("markdown")
        if not isinstance(markdown, str) or not markdown.strip():
            return _failed(
                execution,
                "Memory write requires non-empty Markdown.",
                "invalid_document",
            )
        try:
            if execution.call.action_name == "memory.write_daily":
                stored = await memory.write_document(
                    DailyMemoryDocument(
                        day=day,
                        created_on=day,
                        updated_on=day,
                        content=markdown,
                    )
                )
            else:
                raw_link = params.get("memory_link")
                if not isinstance(raw_link, str):
                    raise MemoryContractError("Memory write requires a persistent Link")
                link = MemoryLink.parse(raw_link)
                if link.kind is MemoryKind.DAILY:
                    raise MemoryContractError(
                        "Use write_daily for the Reflection target daily"
                    )
                stored = await memory.write_markdown(link, markdown)
        except MemoryContractError:
            return _failed(
                execution,
                "Memory write rejected: check the Link, Markdown schema, existing references and redirect chain.",
                "invalid_document",
            )
        except MemoryError as exc:
            raise RuntimeMemoryBridge().from_memory_error(exc) from exc
        return _success(execution, {"link": str(stored.link), "written": True})


class MemoryWriteExecutor(ActionExecutor):
    def __init__(self, controller: MemoryWriteSession) -> None:
        self._controller = controller

    async def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        if execution.call.action_name not in MEMORY_WRITE_ACTIONS:
            return _failed(
                execution,
                "Memory action is not available in this Reflection.",
                "unknown_action",
            )
        return await self._controller.write(execution, context)


def register_memory_write_actions(
    builder: ActionEngineBuilder,
    *,
    controller: MemoryWriteSession,
) -> ActionEngineBuilder:
    executor = MemoryWriteExecutor(controller)
    for handler in MEMORY_WRITE_ACTIONS:
        builder.register_executor(handler, executor)
    return builder


def _success(execution: ActionExecution, payload: JsonObject) -> ActionResult:
    return ActionResult.success(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        payload=payload,
    )


def _failed(execution: ActionExecution, feedback: str, reason: str) -> ActionResult:
    return ActionResult.failed(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        stage=ActionResultStage.EXECUTE,
        failure=ActionLocalFailure(
            reason=reason,
            scope="memory.reflection",
            disposition=ActionFailureDisposition.CHANGE_REQUEST,
            feedback=feedback,
        ),
    )
