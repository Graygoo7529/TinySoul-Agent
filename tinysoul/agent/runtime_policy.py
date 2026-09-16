"""Program-level Runtime trap policy."""

from tinysoul.kernel.loop.trap_handlers import EndFrameTrapHandler, EndTurnOrAgentTrapHandler
from tinysoul.runtime import (
    RUNTIME_AGENT_END,
    RUNTIME_STARTUP_FAILED,
    RunLevel,
    RuntimeTrap,
    TrapHandlerRegistry,
)


def build_agent_trap() -> RuntimeTrap:
    registry = TrapHandlerRegistry()
    registry.register(RUNTIME_AGENT_END, EndFrameTrapHandler(RunLevel.AGENT))
    registry.register(RUNTIME_STARTUP_FAILED, EndFrameTrapHandler(RunLevel.AGENT))
    registry.register_fallback(EndTurnOrAgentTrapHandler())
    return RuntimeTrap(registry=registry)
