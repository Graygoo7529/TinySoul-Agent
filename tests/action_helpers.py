"""Test-only action executor helpers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from functools import cache
from typing import Self

from tinysoul.kernel.action import (
    ActionEngineBuilder,
    ActionExecution,
    ActionExecutionContext,
    ActionResult,
    ActionCatalog,
    ActionCatalogLoader,
)
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.agent.catalog import builtin_action_catalog_root

ActionFunction = Callable[[ActionExecution, ActionExecutionContext], JsonObject]


def load_action_catalog(root: Path) -> ActionCatalog:
    return ActionCatalogLoader().load(root)


@cache
def builtin_catalog() -> ActionCatalog:
    """One immutable assembled catalog per suite, shared by execution tests."""
    with builtin_action_catalog_root() as root:
        return ActionCatalogLoader().load(root)


class FunctionActionExecutor:
    """Adapt a test function to the production ActionExecutor contract."""

    def __init__(self, function: ActionFunction) -> None:
        self._function = function

    async def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        payload = to_json_object(await context.owner_operations.run(
            lambda: self._function(execution, context)
        ))
        return ActionResult.success(
            call_id=execution.call.call_id,
            invoke_id=execution.framework.invoke_id,
            batch_id=execution.framework.batch_id,
            action_name=execution.call.action_name,
            sequence=execution.call.sequence,
            domain=execution.framework.domain,
            payload=payload,
        )


class FunctionActionEngineBuilder(ActionEngineBuilder):
    """Keep fluent function registration confined to tests."""

    def register_function(self, handler: str, function: ActionFunction) -> Self:
        self.register_executor(handler, FunctionActionExecutor(function))
        return self
