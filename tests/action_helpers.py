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
from tinysoul.kernel.retrieval.policy import retrieval_schema
from tinysoul.kernel.retrieval.policy import SearchCapability
from tinysoul.kernel.retrieval.contracts import SourceKind, OperationKind

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
        .joinpath("configs/action/retrieval.toml")
        .read_text(encoding="utf-8")
    )
    policies = parse_action_settings(tomllib.loads(routing)["action"]).retrieval_policies
    capabilities = {
        "core.context.search": SearchCapability(
            "core.context.search", tuple(SourceKind), tuple(OperationKind),
            scopes=("all", "trace", "session"),
            filters=("source", "basis", "kind", "day"),
            ordered_filters=("day",),
        ),
        "home.search": SearchCapability(
            "home.search", tuple(SourceKind), tuple(OperationKind),
            scopes=("all", "agent", "skills"), filters=("space", "file_type"),
        ),
        "memory.search": SearchCapability(
            "memory.search", tuple(SourceKind), tuple(OperationKind),
            scopes=("all", "daily", "entity", "concept", "fact", "note"),
            filters=("kind", "status", "updated_on", "confidence"),
            ordered_filters=("updated_on",), document_query=True,
        ),
        "expand.search": SearchCapability(
            "expand.search",
            (SourceKind.QUERY, SourceKind.DIRECTORY, SourceKind.REFS, SourceKind.RESULT),
            tuple(OperationKind), filters=("server_id", "tool_name"),
            server_scope=True, lexical_syntax=True,
        ),
        "workspace.search": SearchCapability(
            "workspace.search", tuple(SourceKind), tuple(OperationKind),
            filters=("tags", "file_type", "day", "kind"),
            ordered_filters=("day",), resource_scope=True, lexical_syntax=True,
        ),
    }
    return ActionCatalog(
        domains=catalog.domains(),
        actions=tuple(
            replace(
                action,
                tool=replace(
                    action.tool,
                    schema=retrieval_schema(
                        action.tool.schema,
                        replace(
                            next(p for p in policies if p.action_id == action.name),
                            capability=capabilities.get(action.name),
                        ),
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
