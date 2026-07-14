"""App-owned terminal decision routing for manual Home Maintenance."""

from __future__ import annotations

from enum import StrEnum
from threading import Condition
from typing import Protocol

from tinysoul.home import HomeMaintenanceChange, HomeMaintenanceDecision
from tinysoul.runtime import (
    NullObservationEmitter,
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    RunLevel,
    RunScope,
    emit_observation,
    observation_enabled,
)

from .errors import AppInvariantError


class MaintenanceDecisionRoute(StrEnum):
    NOT_CONSUMED = "not_consumed"
    CONSUMED = "consumed"
    CONSUMED_AND_EXIT = "consumed_and_exit"


class MaintenanceDecisionInputRouter(Protocol):
    def route(self, text: str, *, source: str) -> MaintenanceDecisionRoute: ...

    def stop_pending(self, *, source: str) -> bool: ...


_UNSET = object()


class TerminalHomeDecisionBroker:
    """Correlate one manual Home decision with terminal input."""

    def __init__(
        self,
        *,
        observations: ObservationEmitter | None = None,
        scope: RunScope | None = None,
    ) -> None:
        self._observations = observations or NullObservationEmitter()
        self._scope = scope or RunScope().push(RunLevel.PROGRAM, "program")
        self._condition = Condition()
        self._pending = False
        self._decision: object = _UNSET

    @property
    def pending(self) -> bool:
        with self._condition:
            return self._pending and self._decision is _UNSET

    def decide(
        self,
        change: HomeMaintenanceChange,
    ) -> HomeMaintenanceDecision | None:
        with self._condition:
            if self._pending:
                raise AppInvariantError(
                    "Manual Home decision broker already has a pending change"
                )
            self._pending = True
            self._decision = _UNSET
        self._emit_prompt(change)
        with self._condition:
            while self._decision is _UNSET:
                self._condition.wait()
            value = self._decision
            self._decision = _UNSET
            self._pending = False
        if value is None:
            return None
        if not isinstance(value, HomeMaintenanceDecision):
            raise AppInvariantError("Manual Home decision broker resolved invalid data")
        return value

    def route(self, text: str, *, source: str) -> MaintenanceDecisionRoute:
        normalized = text.strip().casefold()
        with self._condition:
            if not self._pending or self._decision is not _UNSET:
                return MaintenanceDecisionRoute.NOT_CONSUMED
            if source == "terminal.eof":
                self._decision = None
                self._condition.notify_all()
                return MaintenanceDecisionRoute.CONSUMED_AND_EXIT
            if normalized == HomeMaintenanceDecision.APPLY.value:
                self._decision = HomeMaintenanceDecision.APPLY
            elif normalized == HomeMaintenanceDecision.DISCARD.value:
                self._decision = HomeMaintenanceDecision.DISCARD
            elif normalized == "stop":
                self._decision = None
            else:
                return MaintenanceDecisionRoute.NOT_CONSUMED
            self._condition.notify_all()
            return MaintenanceDecisionRoute.CONSUMED

    def stop_pending(self, *, source: str) -> bool:
        with self._condition:
            if not self._pending or self._decision is not _UNSET:
                return False
            self._decision = None
            self._condition.notify_all()
            return True

    def _emit_prompt(self, change: HomeMaintenanceChange) -> None:
        if not observation_enabled(self._observations, ObservationLevel.NORMAL):
            return
        emit_observation(
            self._observations,
            ObservationEvent(
                name="program.maintenance.available",
                level=ObservationLevel.NORMAL,
                source="app.maintenance",
                scope=self._scope,
                message=(
                    f"Review {change.link}: enter apply, discard, or stop."
                ),
                payload={
                    "decision_required": True,
                    "change": change.to_review_json(),
                },
            ),
        )
