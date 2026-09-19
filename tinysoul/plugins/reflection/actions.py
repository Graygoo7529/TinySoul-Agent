"""Reflection profile contributions over the injected action assembly."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from tinysoul.kernel.action import (
    ActionEngine,
    ActionEngineBuilder,
    LoadedActionCatalog,
)
from tinysoul.kernel.action.catalog.specs import ActionSemanticSpec
from tinysoul.kernel.context import ContextEngine
from tinysoul.kernel.registration import PluginDeclaration, ServiceRegistry
from tinysoul.plugins.workspace.engine import WorkspaceArchiveView
from tinysoul.kernel.loop.turn import TurnActivityController

from .errors import ReflectionContractError
from tinysoul.plugins.home.actions import (
    HomeReviewExecutor,
    register_home_review_actions,
)
from tinysoul.plugins.memory.actions import (
    MemoryWriteSession,
    register_memory_write_actions,
)


class ReflectionActionAssembly(Protocol):
    """Capability assembly supplied by the outer composition owner."""

    def prepare(
        self,
        context: ContextEngine,
        catalog: LoadedActionCatalog,
        *,
        plugins: tuple[PluginDeclaration, ...],
        archive_source: Callable[[], WorkspaceArchiveView | None] | None = None,
    ) -> tuple[ActionEngineBuilder, TurnActivityController, ServiceRegistry]: ...


def build_reflection_action(
    *,
    kind: str,
    context: ContextEngine,
    home_controller: HomeReviewExecutor,
    memory_controller: MemoryWriteSession,
    action_catalog: LoadedActionCatalog,
    assembly: ReflectionActionAssembly,
    plugins: tuple[PluginDeclaration, ...],
    archive_source: Callable[[], WorkspaceArchiveView | None] | None = None,
) -> tuple[ActionEngine, TurnActivityController, ServiceRegistry]:
    if kind not in {"home", "memory"}:
        raise ReflectionContractError("Unknown Reflection kind")
    builder, jobs, services = assembly.prepare(
        context, action_catalog, plugins=plugins, archive_source=archive_source
    )
    if kind == "home":
        register_home_review_actions(builder, controller=home_controller)
    else:
        register_memory_write_actions(builder, controller=memory_controller)
    builder.with_action_semantics(
        "core.answer",
        description="Conclude this Reflection with a summary of changes, remaining work and limitations.",
        semantic=ActionSemanticSpec(
            use_when=(
                "The Reflection can conclude, including a bounded partial result.",
            ),
            avoid_when=("Work still needs to be executed within this Reflection.",),
        ),
    )
    return builder.with_scenario(f"{kind}_reflection").build(), jobs, services
