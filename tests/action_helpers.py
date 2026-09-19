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
from tests.support.catalog import builtin_action_catalog_root

TEST_SCENARIOS = frozenset({"user", "home_reflection", "memory_reflection"})

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
        payload = to_json_object(
            await context.owner_operations.run(
                lambda: self._function(execution, context)
            )
        )
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

    def __init__(self, catalog: ActionCatalog) -> None:
        super().__init__(catalog, scenarios=TEST_SCENARIOS)

    def register_function(
        self, action_name: str, function: ActionFunction, *, handler: str | None = None
    ) -> Self:
        self.register_executor(
            action_name, FunctionActionExecutor(function), handler=handler
        )
        return self
