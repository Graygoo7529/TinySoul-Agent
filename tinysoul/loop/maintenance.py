"""Program-level orchestration for independent Home and Memory work."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.home import (
    AgentHomeEngine,
    HomeMaintenanceDecisionProvider,
    HomeMaintenanceMode,
    HomeMaintenanceReviewer,
    HomeMaintenanceStatus,
    MemoryConsolidator,
    MemoryMaintenanceSkipReason,
    MemoryMaintenanceStatus,
)
from tinysoul.home.errors import AgentHomeError
from tinysoul.infra.json import JsonObject
from tinysoul.runtime import RunLevel, RunScope, RuntimeException
from tinysoul.session import SessionEngine, SessionMemoryFactsProjection
from tinysoul.session.errors import SessionError

from .daily import DailyLifecycleCoordinator
from .day import BusinessDay
from .errors import LoopContractError, LoopError, LoopInvariantError
from .work import (
    ProgramWorkKind,
    ProgramWorkMode,
    ProgramWorkOutcome,
    ProgramWorkStatus,
)


@dataclass(frozen=True)
class MaintenanceAvailability:
    """Non-persisted startup reminder facts after Daily Rollover."""

    home_pending: bool
    home_change_count: int
    home_skill_memory_count: int
    memory_pending: bool
    memory_day: BusinessDay

    def __post_init__(self) -> None:
        if not isinstance(self.home_pending, bool) or not isinstance(
            self.memory_pending,
            bool,
        ):
            raise LoopContractError("Maintenance availability flags must be booleans")
        for value in (self.home_change_count, self.home_skill_memory_count):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise LoopContractError(
                    "Maintenance availability counts must be non-negative integers"
                )
        if not isinstance(self.memory_day, BusinessDay):
            raise LoopContractError("Maintenance availability memory_day is invalid")

    @property
    def pending(self) -> bool:
        return self.home_pending or self.memory_pending

    def to_json(self) -> JsonObject:
        return {
            "home_pending": self.home_pending,
            "home_change_count": self.home_change_count,
            "home_skill_memory_count": self.home_skill_memory_count,
            "memory_pending": self.memory_pending,
            "memory_day": str(self.memory_day),
        }


class ProgramMaintenanceRunner:
    """Call module-owned maintenance services without owning their state."""

    def __init__(
        self,
        *,
        home: AgentHomeEngine,
        session: SessionEngine,
        daily_lifecycle: DailyLifecycleCoordinator,
        timezone: str,
        automatic_home_reviewer: HomeMaintenanceReviewer,
        memory_consolidator: MemoryConsolidator,
        manual_home_decisions: HomeMaintenanceDecisionProvider,
    ) -> None:
        self._home = home
        self._session = session
        self._daily_lifecycle = daily_lifecycle
        self._timezone = timezone
        self._automatic_home_reviewer = automatic_home_reviewer
        self._memory_consolidator = memory_consolidator
        self._manual_home_decisions = manual_home_decisions

    def availability(self, business_day: BusinessDay) -> MaintenanceAvailability:
        target_day = _previous_day(business_day)
        try:
            home_pending = self._home.maintenance_pending()
            memory_pending = False
            if not self._home.memory_exists(target_day):
                projection = self._memory_projection(target_day)
                memory_pending = self._home.memory_maintenance_eligible(projection)
        except (AgentHomeError, SessionError, LoopError, RuntimeException) as exc:
            raise LoopInvariantError(
                f"Maintenance availability check failed: {exc}"
            ) from exc
        return MaintenanceAvailability(
            home_pending=home_pending.pending,
            home_change_count=home_pending.change_count,
            home_skill_memory_count=home_pending.skill_memory_count,
            memory_pending=memory_pending,
            memory_day=target_day,
        )

    def run_home(
        self,
        *,
        business_day: BusinessDay,
        mode: ProgramWorkMode,
        source: str,
        scope: RunScope,
    ) -> ProgramWorkOutcome:
        work_scope = scope.push(RunLevel.MODULE, ProgramWorkKind.HOME_MAINTENANCE.value)
        try:
            outcome = self._home.run_maintenance(
                mode=(
                    HomeMaintenanceMode.MANUAL
                    if mode is ProgramWorkMode.MANUAL
                    else HomeMaintenanceMode.AUTOMATIC
                ),
                automatic_reviewer=(
                    self._automatic_home_reviewer
                    if mode is ProgramWorkMode.AUTOMATIC
                    else None
                ),
                manual_decisions=(
                    self._manual_home_decisions
                    if mode is ProgramWorkMode.MANUAL
                    else None
                ),
                scope=work_scope,
            )
        except (AgentHomeError, RuntimeException) as exc:
            return _failed(
                kind=ProgramWorkKind.HOME_MAINTENANCE,
                mode=mode,
                business_day=business_day,
                source=source,
                error=exc,
            )
        status = {
            HomeMaintenanceStatus.COMPLETED: ProgramWorkStatus.COMPLETED,
            HomeMaintenanceStatus.STOPPED: ProgramWorkStatus.STOPPED,
            HomeMaintenanceStatus.FAILED: ProgramWorkStatus.FAILED,
        }[outcome.status]
        details: JsonObject = {
            "applied": outcome.applied,
            "discarded": outcome.discarded,
            "copied_cleaned": outcome.copied_cleaned,
            "consistent_cleaned": outcome.consistent_cleaned,
            "skill_memories_cleared": outcome.skill_memories_cleared,
            "remaining_changes": outcome.remaining_changes,
        }
        if outcome.failure is not None:
            details["failure"] = outcome.failure.value
        return ProgramWorkOutcome(
            kind=ProgramWorkKind.HOME_MAINTENANCE,
            mode=mode,
            status=status,
            business_day=business_day,
            source=source,
            details=details,
        )

    def run_memory(
        self,
        *,
        business_day: BusinessDay,
        target_day: BusinessDay,
        mode: ProgramWorkMode,
        source: str,
        scope: RunScope,
    ) -> ProgramWorkOutcome:
        work_scope = scope.push(
            RunLevel.MODULE,
            ProgramWorkKind.MEMORY_MAINTENANCE.value,
        )
        try:
            if (
                mode is ProgramWorkMode.AUTOMATIC
                and self._home.memory_exists(target_day)
            ):
                return ProgramWorkOutcome(
                    kind=ProgramWorkKind.MEMORY_MAINTENANCE,
                    mode=mode,
                    status=ProgramWorkStatus.SKIPPED,
                    business_day=business_day,
                    target_day=target_day,
                    source=source,
                    details={
                        "link": f"home:memory@{target_day}",
                        "skip_reason": MemoryMaintenanceSkipReason.MEMORY_EXISTS.value,
                    },
                )
            projection = self._memory_projection(target_day)
            outcome = self._home.run_memory_maintenance(
                projection=projection,
                consolidator=self._memory_consolidator,
                timezone=self._timezone,
                target_day=target_day,
                rewrite_existing=mode is ProgramWorkMode.MANUAL,
                scope=work_scope,
            )
        except (AgentHomeError, SessionError, LoopError, RuntimeException) as exc:
            return _failed(
                kind=ProgramWorkKind.MEMORY_MAINTENANCE,
                mode=mode,
                business_day=business_day,
                target_day=target_day,
                source=source,
                error=exc,
            )
        status = {
            MemoryMaintenanceStatus.COMPLETED: ProgramWorkStatus.COMPLETED,
            MemoryMaintenanceStatus.SKIPPED: ProgramWorkStatus.SKIPPED,
            MemoryMaintenanceStatus.FAILED: ProgramWorkStatus.FAILED,
        }[outcome.status]
        details: JsonObject = {
            "link": outcome.link,
            "fact_count": outcome.fact_count,
            "model_calls": outcome.model_calls,
            "document_digest": outcome.document_digest,
        }
        if outcome.skip_reason is not None:
            details["skip_reason"] = outcome.skip_reason.value
        if outcome.failure is not None:
            details["failure"] = outcome.failure.value
        return ProgramWorkOutcome(
            kind=ProgramWorkKind.MEMORY_MAINTENANCE,
            mode=mode,
            status=status,
            business_day=business_day,
            target_day=target_day,
            source=source,
            details=details,
        )

    def _memory_projection(
        self,
        day: BusinessDay,
    ) -> SessionMemoryFactsProjection | None:
        root = self._daily_lifecycle.session_archive_for(day)
        if root is None:
            return None
        return self._session.memory_facts(day, root=root)


def _failed(
    *,
    kind: ProgramWorkKind,
    mode: ProgramWorkMode,
    business_day: BusinessDay,
    source: str,
    error: Exception,
    target_day: BusinessDay | None = None,
) -> ProgramWorkOutcome:
    return ProgramWorkOutcome(
        kind=kind,
        mode=mode,
        status=ProgramWorkStatus.FAILED,
        business_day=business_day,
        target_day=target_day,
        source=source,
        details={
            "error_type": type(error).__name__,
            "message": str(error)[:1000],
        },
    )


def _previous_day(day: BusinessDay) -> BusinessDay:
    from datetime import timedelta

    return BusinessDay(day.value - timedelta(days=1))
