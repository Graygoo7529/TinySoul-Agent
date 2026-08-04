"""Program-level Runtime trap policy."""

from tinysoul.loop.trap_handlers import EndFrameTrapHandler, EndTurnOrProgramTrapHandler
from tinysoul.runtime import (
    RUNTIME_PROGRAM_END,
    RUNTIME_STARTUP_FAILED,
    RunLevel,
    RuntimeTrap,
    TrapHandlerRegistry,
)


def build_program_trap() -> RuntimeTrap:
    registry = TrapHandlerRegistry()
    registry.register(RUNTIME_PROGRAM_END, EndFrameTrapHandler(RunLevel.PROGRAM))
    registry.register(RUNTIME_STARTUP_FAILED, EndFrameTrapHandler(RunLevel.PROGRAM))
    registry.register_fallback(EndTurnOrProgramTrapHandler())
    return RuntimeTrap(registry=registry)
