"""Small test-owned action inputs and adapters for kernel contracts."""

from __future__ import annotations

from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Self

from tests.support.catalog import builtin_action_catalog_root
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.kernel.action import (
    ActionCatalog,
    ActionCatalogLoader,
    ActionEngineBuilder,
    ActionExecution,
    ActionExecutionContext,
    ActionResult,
)
from tinysoul.kernel.action.catalog.loader import ActionTomlParser
from tinysoul.kernel.action.catalog.specs import ActionDomainSpec

TEST_SCENARIOS = frozenset({"user", "home_reflection", "memory_reflection"})
ActionFunction = Callable[[ActionExecution, ActionExecutionContext], JsonObject]


def load_action_catalog(root: Path) -> ActionCatalog:
    return ActionCatalogLoader().load(root)


@cache
def packaged_catalog() -> ActionCatalog:
    """Raw package schema for representative real plugin collaboration only."""
    with builtin_action_catalog_root() as root:
        return ActionCatalogLoader().load(root)


@cache
def sample_catalog() -> ActionCatalog:
    """The fixture owns these inputs; no bundled prose, models or policy defaults."""
    declarations = (
        (
            "core.answer",
            {"guide_blocks": {"type": "array", "items": {"type": "object"}}},
            ["guide_blocks"],
            23,
        ),
        (
            "core.reason",
            {
                "guide_blocks": {"type": "array", "items": {"type": "object"}},
                "output_blocks": {"type": "array", "items": {"type": "object"}},
            },
            ["guide_blocks"],
            23,
        ),
        ("core.ask", {}, [], 23),
        ("core.context.inspect", {"ref": {"type": "string"}}, ["ref"], 17),
        ("workspace.list", {}, [], 17),
        ("workspace.compose", {}, [], 29),
        ("home.inspect", {}, [], 17),
        ("execution.run", {}, [], 17),
    )
    parser = ActionTomlParser()
    actions = tuple(
        parser.parse_action(
            {
                "name": name,
                "domain": name.split(".")[0],
                "tool": {
                    "description": f"Test {name}",
                    "schema": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                        "additionalProperties": name != "workspace.list",
                    },
                },
                "runtime": {"timeout_seconds": timeout},
                "execution": {
                    "executor": "context.inspect"
                    if name == "core.context.inspect"
                    else name
                },
            },
            source=f"fixture:{name}",
        )
        for name, properties, required, timeout in declarations
    )
    return ActionCatalog(
        domains=tuple(
            ActionDomainSpec(name=domain, description=f"Test {domain}")
            for domain in ("core", "home", "workspace", "execution")
        ),
        actions=actions,
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
