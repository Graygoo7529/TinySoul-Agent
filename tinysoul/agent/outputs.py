"""Application output sinks and observation fan-out."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Protocol

from tinysoul.infra.concurrency import CleanupDiagnostic
from tinysoul.runtime import ObservationEvent, ObservationLevel
from tinysoul.agent.observations import ObservationSubscriptions

from .errors import AgentContractError


class OutputSink(Protocol):
    """External output boundary for one observation event."""

    def write(self, event: ObservationEvent) -> None:
        """Render or forward one event."""
        ...


@dataclass(frozen=True)
class ObservationRoute:
    """One output sink with an independent maximum observation level."""

    sink: OutputSink
    mode: ObservationLevel

    def __post_init__(self) -> None:
        if not hasattr(self.sink, "write"):
            raise AgentContractError("Observation route sink must provide write()")
        if not isinstance(self.mode, ObservationLevel):
            raise AgentContractError(
                "Observation route mode must be an ObservationLevel"
            )


class ObservationRouter:
    """Filter observations and fan them out without raising into business code."""

    def __init__(
        self,
        *,
        mode: ObservationLevel = ObservationLevel.NORMAL,
        sinks: tuple[OutputSink, ...] = (),
        routes: tuple[ObservationRoute, ...] = (),
    ) -> None:
        if not isinstance(mode, ObservationLevel):
            raise AgentContractError(
                "ObservationRouter.mode must be an ObservationLevel"
            )
        self._mode = mode
        self._routes = (
            *(ObservationRoute(sink=sink, mode=mode) for sink in sinks),
            *tuple(routes),
        )
        self._disabled: set[int] = set()
        self._failures: list[CleanupDiagnostic] = []
        self._subscriptions_disabled = False
        self._lock = RLock()
        self.subscriptions = ObservationSubscriptions()

    @property
    def mode(self) -> ObservationLevel:
        return max((self._mode, *(route.mode for route in self._routes)), key=_level_rank)

    def add_route(self, route: ObservationRoute) -> None:
        with self._lock:
            self._routes = (*self._routes, route)

    @property
    def failures(self) -> tuple[CleanupDiagnostic, ...]:
        with self._lock:
            return tuple(self._failures)

    def enabled(self, level: ObservationLevel) -> bool:
        with self._lock:
            return self.subscriptions.enabled(level) or any(
                _level_rank(level) <= _level_rank(route.mode)
                for route in self._routes
            )

    def emit(self, event: ObservationEvent) -> None:
        if not self.enabled(event.level):
            return
        with self._lock:
            if not self._subscriptions_disabled:
                try:
                    self.subscriptions.write(event)
                except Exception as exc:
                    self._subscriptions_disabled = True
                    self._failures.append(CleanupDiagnostic("observation.subscriptions", type(exc).__name__))
                    self.subscriptions.close()
            for index, route in enumerate(self._routes):
                if index in self._disabled:
                    continue
                if _level_rank(event.level) > _level_rank(route.mode):
                    continue
                try:
                    route.sink.write(event)
                except Exception as exc:
                    self._disabled.add(index)
                    self._failures.append(CleanupDiagnostic(f"observation.{index}", type(exc).__name__))


def _level_rank(level: ObservationLevel) -> int:
    return {
        ObservationLevel.NORMAL: 0,
        ObservationLevel.VERBOSE: 1,
        ObservationLevel.MODEL: 2,
    }[level]
