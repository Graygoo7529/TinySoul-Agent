"""User Turn Runtime trap policy."""

from __future__ import annotations

from tinysoul.kernel.context import ContextEngine
from tinysoul.llm.failures import LLM_CONTEXT_CAPACITY_EXCEEDED
from tinysoul.plugins.home import AgentHomeEngine, AgentHomeRuntimeCopyTrapHandler
from tinysoul.kernel.context.failures import CONTEXT_COMPRESSION_REQUIRED
from tinysoul.plugins.home.failures import HOME_RUNTIME_COPY_REQUIRED
from tinysoul.plugins.workspace.failures import WORKSPACE_TRASH_RESTORE_REQUIRED
from tinysoul.runtime import (
    RUNTIME_CYCLE_END,
    RUNTIME_AGENT_END,
    RUNTIME_STARTUP_FAILED,
    RUNTIME_TURN_END,
    RunLevel,
    RuntimeTrap,
    TrapHandlerRegistry,
)
from tinysoul.plugins.workspace import WorkspaceEngine

from tinysoul.kernel.loop.trap_handlers import (
    BudgetSuspendTrapHandler,
    ContextPressureTrapHandler,
    EndFrameTrapHandler,
    EndTurnOrAgentTrapHandler,
)
from .pressure import UserContextPressureRecovery
from tinysoul.kernel.loop.failures import LOOP_BUDGET_REQUIRED
from tinysoul.plugins.workspace.trap_handlers import WorkspaceTrashRestoreTrapHandler


def build_user_turn_trap(
    *,
    context: ContextEngine,
    home: AgentHomeEngine,
    workspace: WorkspaceEngine,
) -> RuntimeTrap:
    registry = TrapHandlerRegistry()
    registry.register(LOOP_BUDGET_REQUIRED, BudgetSuspendTrapHandler())
    registry.register(RUNTIME_TURN_END, EndFrameTrapHandler(RunLevel.TURN))
    registry.register(RUNTIME_CYCLE_END, EndFrameTrapHandler(RunLevel.CYCLE))
    registry.register(RUNTIME_AGENT_END, EndFrameTrapHandler(RunLevel.AGENT))
    registry.register(RUNTIME_STARTUP_FAILED, EndFrameTrapHandler(RunLevel.AGENT))
    pressure_handler = ContextPressureTrapHandler(
        UserContextPressureRecovery(
            context=context,
            workspace=workspace,
            target_ratio=context.compression_target_ratio,
        )
    )
    registry.register(CONTEXT_COMPRESSION_REQUIRED, pressure_handler)
    registry.register(LLM_CONTEXT_CAPACITY_EXCEEDED, pressure_handler)
    registry.register(HOME_RUNTIME_COPY_REQUIRED, AgentHomeRuntimeCopyTrapHandler(home))
    registry.register(
        WORKSPACE_TRASH_RESTORE_REQUIRED,
        WorkspaceTrashRestoreTrapHandler(workspace=workspace),
    )
    registry.register_fallback(EndTurnOrAgentTrapHandler())
    return RuntimeTrap(registry=registry)
