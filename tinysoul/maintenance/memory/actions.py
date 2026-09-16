"""Memory Reflection actions: one validated document per accepted write."""

from __future__ import annotations

from datetime import date

from tinysoul.action import (
    ActionEngineBuilder, ActionExecution, ActionExecutionContext,
    ActionResult, LocalActionExecutor,
)
from tinysoul.infra.json import JsonObject
from tinysoul.infra.time import BusinessDay
from tinysoul.memory import DailyMemoryDocument, MemoryEngine, MemoryLink, MemoryKind
from tinysoul.memory.actions import _failed, _success
from tinysoul.memory.errors import MemoryContractError, MemoryError
from tinysoul.memory.runtime_bridge import RuntimeMemoryBridge

from ..errors import MaintenanceInvariantError

MEMORY_MAINTENANCE_ACTIONS = (
    "memory_reflection.write_daily",
    "memory_reflection.write",
)


class MemoryMaintenanceActionController:
    """Bind the Reflection target; all persistent facts remain with Memory."""

    def __init__(self, *, memory: MemoryEngine) -> None:
        self._memory = memory
        self._target_day: date | None = None

    def begin(self, *, target_day: BusinessDay) -> None:
        if self._target_day is not None:
            raise MaintenanceInvariantError("A Memory Reflection is already active")
        self._target_day = target_day.value

    def finish(self) -> JsonObject:
        day = self.target_day()
        self._target_day = None
        return {"target_day": day.isoformat()}

    def abort(self) -> None:
        self._target_day = None

    def target_day(self) -> date:
        if self._target_day is None:
            raise MaintenanceInvariantError("No Memory Reflection is active")
        return self._target_day

    def write(self, execution: ActionExecution) -> ActionResult:
        day = self.target_day()
        params = execution.call.params
        markdown = params.get("markdown")
        if not isinstance(markdown, str) or not markdown.strip():
            return _failed(execution, "Memory write requires non-empty Markdown.", "invalid_document")
        try:
            if execution.call.action_name == "memory_reflection.write_daily":
                stored = self._memory.write_document(DailyMemoryDocument(
                    day=day, created_on=day, updated_on=day, content=markdown,
                ))
            else:
                raw_link = params.get("memory_link")
                if not isinstance(raw_link, str):
                    raise MemoryContractError("Memory write requires a persistent Link")
                link = MemoryLink.parse(raw_link)
                if link.kind is MemoryKind.DAILY:
                    raise MemoryContractError("Use write_daily for the Reflection target daily")
                stored = self._memory.write_markdown(link, markdown)
        except MemoryContractError:
            return _failed(
                execution,
                "Memory write rejected: check the Link, Markdown schema, existing references and redirect chain.",
                "invalid_document",
            )
        except MemoryError as exc:
            raise RuntimeMemoryBridge().from_memory_error(exc) from exc
        return _success(execution, {"link": str(stored.link), "written": True})


class MemoryReflectionWriteExecutor(LocalActionExecutor):
    def __init__(self, controller: MemoryMaintenanceActionController) -> None:
        self._controller = controller

    def execute_local(
        self, execution: ActionExecution, context: ActionExecutionContext,
    ) -> ActionResult:
        return self._controller.write(execution)


def register_memory_maintenance_actions(
    builder: ActionEngineBuilder, *, controller: MemoryMaintenanceActionController,
) -> ActionEngineBuilder:
    executor = MemoryReflectionWriteExecutor(controller)
    for handler in MEMORY_MAINTENANCE_ACTIONS:
        builder.register_executor(handler, executor)
    return builder
