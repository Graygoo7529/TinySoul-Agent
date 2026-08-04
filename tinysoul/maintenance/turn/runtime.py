"""Maintenance Turn Runtime policy."""

from __future__ import annotations

from collections.abc import Mapping

from tinysoul.context import ContextEngine
from tinysoul.context.errors import ContextError
from tinysoul.infra.json import JsonValue
from tinysoul.loop.pressure import (
    PressureRecoveryResult,
    PressureRecoveryStatus,
    required_chars,
)
from tinysoul.loop.trap_handlers import (
    ContextPressureTrapHandler,
    EndFrameTrapHandler,
    EndTurnOrProgramTrapHandler,
)
from tinysoul.runtime import (
    CONTEXT_COMPRESSION_REQUIRED,
    RUNTIME_CYCLE_END,
    RUNTIME_PROGRAM_END,
    RUNTIME_STARTUP_FAILED,
    RUNTIME_TURN_END,
    RunLevel,
    RunScope,
    RuntimeTrap,
    TrapHandlerRegistry,
)


class MaintenanceContextPressureRecovery:
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
        except ContextError as exc:
            return PressureRecoveryResult(
                status=PressureRecoveryStatus.FAILED,
                reclaimed_chars=0,
                error=str(exc),
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


def build_maintenance_turn_trap(context: ContextEngine) -> RuntimeTrap:
    registry = TrapHandlerRegistry()
    registry.register(RUNTIME_TURN_END, EndFrameTrapHandler(RunLevel.TURN))
    registry.register(RUNTIME_CYCLE_END, EndFrameTrapHandler(RunLevel.CYCLE))
    registry.register(RUNTIME_PROGRAM_END, EndFrameTrapHandler(RunLevel.PROGRAM))
    registry.register(RUNTIME_STARTUP_FAILED, EndFrameTrapHandler(RunLevel.PROGRAM))
    registry.register(
        CONTEXT_COMPRESSION_REQUIRED,
        ContextPressureTrapHandler(MaintenanceContextPressureRecovery(context)),
    )
    registry.register_fallback(EndTurnOrProgramTrapHandler())
    return RuntimeTrap(registry=registry)
