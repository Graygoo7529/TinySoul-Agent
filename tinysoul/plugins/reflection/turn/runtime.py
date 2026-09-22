"""Reflection Turn Runtime policy."""

from __future__ import annotations

from collections.abc import Mapping

from tinysoul.kernel.context import ContextEngine
from tinysoul.kernel.context.errors import ContextError
from tinysoul.kernel.registration import ResolvedProfileExtensions
from tinysoul.llm.failures import LLM_CONTEXT_CAPACITY_EXCEEDED
from tinysoul.infra.json import JsonValue
from tinysoul.kernel.loop.pressure import (
    PressureRecoveryResult,
    PressureRecoveryStatus,
    required_chars,
)
from tinysoul.kernel.loop.trap_handlers import (
    BudgetSuspendTrapHandler,
    ContextPressureTrapHandler,
    EndFrameTrapHandler,
    EndTurnOrAgentTrapHandler,
)
from tinysoul.kernel.context.failures import CONTEXT_COMPRESSION_REQUIRED
from tinysoul.kernel.loop.failures import LOOP_BUDGET_REQUIRED
from tinysoul.runtime import (
    RUNTIME_CYCLE_END,
    RUNTIME_AGENT_END,
    RUNTIME_STARTUP_FAILED,
    RUNTIME_TURN_END,
    RunLevel,
    RunScope,
    RuntimeTrap,
    TrapHandlerRegistry,
)


class ReflectionContextPressureRecovery:
    """Recover pressure without touching active Workspace or runtime Home."""

    def __init__(self, context: ContextEngine) -> None:
        self._context = context

    def recover(
        self,
        *,
        payload: Mapping[str, JsonValue],
        scope: RunScope,
    ) -> PressureRecoveryResult:
        del scope
        required = required_chars(
            payload,
            target_ratio=self._context.compression_target_ratio,
        )
        try:
            report = self._context.reclaim_pressure(required_chars=required)
        except ContextError:
            return PressureRecoveryResult(
                status=PressureRecoveryStatus.FAILED,
                reclaimed_chars=0,
                error="Context pressure recovery failed.",
            )
        return PressureRecoveryResult(
            status=(
                PressureRecoveryStatus.RECOVERED
                if report.reclaimed_chars > 0
                else PressureRecoveryStatus.NO_PROGRESS
            ),
            reclaimed_chars=report.reclaimed_chars,
            evicted_background_links=report.evicted_background_links,
        )


def build_reflection_turn_trap(
    context: ContextEngine,
    *,
    plugins: ResolvedProfileExtensions,
) -> RuntimeTrap:
    registry = TrapHandlerRegistry()
    registry.register(LOOP_BUDGET_REQUIRED, BudgetSuspendTrapHandler())
    registry.register(RUNTIME_TURN_END, EndFrameTrapHandler(RunLevel.TURN))
    registry.register(RUNTIME_CYCLE_END, EndFrameTrapHandler(RunLevel.CYCLE))
    registry.register(RUNTIME_AGENT_END, EndFrameTrapHandler(RunLevel.AGENT))
    registry.register(RUNTIME_STARTUP_FAILED, EndFrameTrapHandler(RunLevel.AGENT))
    pressure_handler = ContextPressureTrapHandler(
        ReflectionContextPressureRecovery(context)
    )
    registry.register(CONTEXT_COMPRESSION_REQUIRED, pressure_handler)
    registry.register(LLM_CONTEXT_CAPACITY_EXCEEDED, pressure_handler)
    plugins.install_traps(registry)
    registry.register_fallback(EndTurnOrAgentTrapHandler())
    return RuntimeTrap(registry=registry)
