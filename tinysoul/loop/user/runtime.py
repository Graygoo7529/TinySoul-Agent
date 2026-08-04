"""User Turn Runtime trap policy."""

from __future__ import annotations

from tinysoul.context import ContextEngine
from tinysoul.home import AgentHomeEngine, AgentHomeRuntimeCopyTrapHandler
from tinysoul.runtime import (
    CONTEXT_COMPRESSION_REQUIRED,
    HOME_RUNTIME_COPY_REQUIRED,
    RUNTIME_CYCLE_END,
    RUNTIME_PROGRAM_END,
    RUNTIME_STARTUP_FAILED,
    RUNTIME_TURN_END,
    WORKSPACE_TRASH_RESTORE_REQUIRED,
    RunLevel,
    RuntimeTrap,
    TrapHandlerRegistry,
)
from tinysoul.workspace import WorkspaceEngine

from ..trap_handlers import (
    ContextPressureTrapHandler,
    EndFrameTrapHandler,
    EndTurnOrProgramTrapHandler,
)
from .pressure import UserContextPressureRecovery
from .trap_handlers import WorkspaceTrashRestoreTrapHandler


def build_user_turn_trap(
    *,
    context: ContextEngine,
    home: AgentHomeEngine,
    workspace: WorkspaceEngine,
) -> RuntimeTrap:
    registry = TrapHandlerRegistry()
    registry.register(RUNTIME_TURN_END, EndFrameTrapHandler(RunLevel.TURN))
    registry.register(RUNTIME_CYCLE_END, EndFrameTrapHandler(RunLevel.CYCLE))
    registry.register(RUNTIME_PROGRAM_END, EndFrameTrapHandler(RunLevel.PROGRAM))
    registry.register(RUNTIME_STARTUP_FAILED, EndFrameTrapHandler(RunLevel.PROGRAM))
    registry.register(
        CONTEXT_COMPRESSION_REQUIRED,
        ContextPressureTrapHandler(
            UserContextPressureRecovery(
                context=context,
                workspace=workspace,
                target_ratio=context.compression_target_ratio,
            )
        ),
    )
    registry.register(HOME_RUNTIME_COPY_REQUIRED, AgentHomeRuntimeCopyTrapHandler(home))
    registry.register(
        WORKSPACE_TRASH_RESTORE_REQUIRED,
        WorkspaceTrashRestoreTrapHandler(workspace=workspace, context=context),
    )
    registry.register_fallback(EndTurnOrProgramTrapHandler())
    return RuntimeTrap(registry=registry)
