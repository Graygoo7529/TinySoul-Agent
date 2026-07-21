"""App-owned terminal decision routing for manual Home Maintenance."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from threading import Condition
from typing import Protocol
from uuid import uuid4

from tinysoul.home import HomeMaintenanceChange, HomeMaintenanceDecision
from tinysoul.infra.json import JsonObject
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


@dataclass(frozen=True)
class MaintenanceDecisionSnapshot:
    """One pending manual Home change exposed to external input adapters."""

    decision_id: str
    change: HomeMaintenanceChange

    def __post_init__(self) -> None:
        if not self.decision_id:
            raise AppInvariantError("Maintenance decision id must be non-empty")


class MaintenanceDecisionRoute(StrEnum):
    NOT_CONSUMED = "not_consumed"
    CONSUMED = "consumed"
    CONSUMED_AND_EXIT = "consumed_and_exit"


class MaintenanceDecisionInputRouter(Protocol):
    def route(
        self,
        text: str,
        *,
        source: str,
        command_id: str = "",
    ) -> MaintenanceDecisionRoute: ...

    def stop_pending(self, *, source: str) -> bool: ...


_UNSET = object()


class HomeDecisionBroker:
    """Correlate one manual Home decision with an authenticated input adapter."""

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
        self._decision_id = ""
        self._change: HomeMaintenanceChange | None = None
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
            self._decision_id = f"decision_{uuid4().hex[:12]}"
            self._change = change
            self._decision = _UNSET
        self._emit_prompt(change)
        with self._condition:
            while self._decision is _UNSET:
                self._condition.wait()
            value = self._decision
            self._decision = _UNSET
            self._pending = False
            self._decision_id = ""
            self._change = None
        if value is None:
            return None
        if not isinstance(value, HomeMaintenanceDecision):
            raise AppInvariantError("Manual Home decision broker resolved invalid data")
        return value

    def route(
        self,
        text: str,
        *,
        source: str,
        command_id: str = "",
    ) -> MaintenanceDecisionRoute:
        normalized = text.strip().casefold()
        with self._condition:
            if not self._pending or self._decision is not _UNSET:
                return MaintenanceDecisionRoute.NOT_CONSUMED
            if source == "terminal.eof":
                self._decision = None
                decision_id = self._decision_id
                self._condition.notify_all()
                route = MaintenanceDecisionRoute.CONSUMED_AND_EXIT
                resolved = "stop"
            elif normalized == HomeMaintenanceDecision.APPLY.value:
                self._decision = HomeMaintenanceDecision.APPLY
                decision_id = self._decision_id
                route = MaintenanceDecisionRoute.CONSUMED
                resolved = HomeMaintenanceDecision.APPLY.value
            elif normalized == HomeMaintenanceDecision.DISCARD.value:
                self._decision = HomeMaintenanceDecision.DISCARD
                decision_id = self._decision_id
                route = MaintenanceDecisionRoute.CONSUMED
                resolved = HomeMaintenanceDecision.DISCARD.value
            elif normalized == "stop":
                self._decision = None
                decision_id = self._decision_id
                route = MaintenanceDecisionRoute.CONSUMED
                resolved = "stop"
            else:
                return MaintenanceDecisionRoute.NOT_CONSUMED
            self._condition.notify_all()
        self._emit_resolved(decision_id, resolved, source, command_id)
        return route

    def stop_pending(self, *, source: str) -> bool:
        with self._condition:
            if not self._pending or self._decision is not _UNSET:
                return False
            self._decision = None
            decision_id = self._decision_id
            self._condition.notify_all()
        self._emit_resolved(decision_id, "stop", source, "")
        return True

    def pending_decision(self) -> MaintenanceDecisionSnapshot | None:
        with self._condition:
            if (
                not self._pending
                or self._decision is not _UNSET
                or self._change is None
            ):
                return None
            return MaintenanceDecisionSnapshot(
                decision_id=self._decision_id,
                change=self._change,
            )

    def submit_decision(
        self,
        decision_id: str,
        decision: HomeMaintenanceDecision | None,
        *,
        source: str = "api",
        command_id: str = "",
    ) -> bool:
        with self._condition:
            if (
                not self._pending
                or self._decision is not _UNSET
                or decision_id != self._decision_id
            ):
                return False
            if decision is not None and not isinstance(
                decision,
                HomeMaintenanceDecision,
            ):
                raise AppInvariantError("Maintenance decision value is invalid")
            self._decision = decision
            resolved = decision.value if decision is not None else "stop"
            self._condition.notify_all()
        self._emit_resolved(decision_id, resolved, source, command_id)
        return True

    def _emit_prompt(self, change: HomeMaintenanceChange) -> None:
        if not observation_enabled(self._observations, ObservationLevel.NORMAL):
            return
        emit_observation(
            self._observations,
            ObservationEvent(
                name="home.maintenance.decision.required",
                level=ObservationLevel.NORMAL,
                source="app.maintenance",
                scope=self._scope,
                message=(
                    f"Review {change.link}: enter apply, discard, or stop."
                ),
                payload={
                    "decision_required": True,
                    "decision_id": self._decision_id,
                    "change": change.to_review_json(),
                },
            ),
        )

    def _emit_resolved(
        self,
        decision_id: str,
        decision: str,
        source: str,
        command_id: str,
    ) -> None:
        if not observation_enabled(self._observations, ObservationLevel.NORMAL):
            return
        payload: JsonObject = {
            "decision_id": decision_id,
            "decision": decision,
            "source": source,
        }
        if command_id:
            payload["command_id"] = command_id
        emit_observation(
            self._observations,
            ObservationEvent(
                name="home.maintenance.decision.resolved",
                level=ObservationLevel.NORMAL,
                source="app.maintenance",
                scope=self._scope,
                message=f"Home Maintenance decision resolved as {decision}.",
                payload=payload,
            ),
        )
