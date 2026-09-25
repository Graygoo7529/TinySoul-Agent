"""Test-only action executor helpers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from functools import cache
from dataclasses import replace
from importlib.resources import files
import tomllib
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
from tinysoul.kernel.action.config import parse_action_settings
from tinysoul.kernel.retrieval.policy import search_schema

TEST_SCENARIOS = frozenset({"user", "home_reflection", "memory_reflection"})

ActionFunction = Callable[[ActionExecution, ActionExecutionContext], JsonObject]


def load_action_catalog(root: Path) -> ActionCatalog:
    return ActionCatalogLoader().load(root)


@cache
def builtin_catalog() -> ActionCatalog:
    """One immutable assembled catalog per suite, shared by execution tests."""
    with builtin_action_catalog_root() as root:
        catalog = ActionCatalogLoader().load(root)
    routing = (
        files("tinysoul.assets.standard")
        .joinpath("configs/action/routing.toml")
        .read_text(encoding="utf-8")
    )
    policies = parse_action_settings(tomllib.loads(routing)["action"]).search_policies
    return ActionCatalog(
        domains=catalog.domains(),
        actions=tuple(
            replace(
                action,
                tool=replace(
                    action.tool,
                    schema=search_schema(
                        action.tool.schema, policies, action_id=action.name
                    ),
                ),
            )
            if any(policy.action_id == action.name for policy in policies)
            else action
            for action in catalog.actions()
        ),
    )


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
        self,
        action_name: str,
        function: ActionFunction,
        *,
        executor_id: str | None = None,
    ) -> Self:
        self.register_executor(
            action_name, FunctionActionExecutor(function), executor_id=executor_id
        )
        return self
