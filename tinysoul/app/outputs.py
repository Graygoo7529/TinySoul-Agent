"""Application output sinks and observation fan-out."""

from __future__ import annotations

from dataclasses import dataclass, field
import sys
from threading import RLock
from typing import Protocol, TextIO

from tinysoul.infra.json import dumps_json
from tinysoul.runtime import ObservationEvent, ObservationLevel

from .errors import AppContractError, AppOutputError


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
            raise AppContractError("Observation route sink must provide write()")
        if not isinstance(self.mode, ObservationLevel):
            raise AppContractError(
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
            raise AppContractError(
                "ObservationRouter.mode must be an ObservationLevel"
            )
        self._mode = mode
        self._routes = (
            *(ObservationRoute(sink=sink, mode=mode) for sink in sinks),
            *tuple(routes),
        )
        self._disabled: set[int] = set()
        self._failures: list[Exception] = []
        self._lock = RLock()

    @property
    def mode(self) -> ObservationLevel:
        return self._mode

    @property
    def failures(self) -> tuple[Exception, ...]:
        with self._lock:
            return tuple(self._failures)

    def enabled(self, level: ObservationLevel) -> bool:
        with self._lock:
            return any(
                _level_rank(level) <= _level_rank(route.mode)
                for route in self._routes
            )

    def emit(self, event: ObservationEvent) -> None:
        if not self.enabled(event.level):
            return
        with self._lock:
            for index, route in enumerate(self._routes):
                if index in self._disabled:
                    continue
                if _level_rank(event.level) > _level_rank(route.mode):
                    continue
                try:
                    route.sink.write(event)
                except Exception as exc:
                    self._disabled.add(index)
                    self._failures.append(exc)

    def raise_if_failed(self) -> None:
        with self._lock:
            if not self._failures:
                return
            detail = "; ".join(
                f"{type(error).__name__}: {error}" for error in self._failures
            )
            self._failures.clear()
        raise AppOutputError(f"Output sink failed: {detail}")


@dataclass
class ConsoleOutputSink:
    """Plain terminal renderer with stdout reserved for final answers."""

    stdout: TextIO = field(default_factory=lambda: sys.stdout)
    stderr: TextIO = field(default_factory=lambda: sys.stderr)
    max_chars: int = 20000

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_chars, bool)
            or not isinstance(self.max_chars, int)
            or self.max_chars <= 0
        ):
            raise AppOutputError("Console output max_chars must be positive")
        self._lock = RLock()

    def write(self, event: ObservationEvent) -> None:
        with self._lock:
            if event.name == "turn.output":
                text = event.payload.get("text", event.message)
                rendered = text if isinstance(text, str) else event.message
                self.stdout.write(rendered.rstrip() + "\n")
                self.stdout.flush()
                return
            detail = event.message or event.name
            if event.payload:
                detail = f"{detail} | {dumps_json(event.payload)}"
            rendered = f"[{event.name}] {_clip(detail, self.max_chars)}"
            self.stderr.write(rendered.rstrip() + "\n")
            self.stderr.flush()


def _level_rank(level: ObservationLevel) -> int:
    return {
        ObservationLevel.NORMAL: 0,
        ObservationLevel.VERBOSE: 1,
        ObservationLevel.MODEL: 2,
    }[level]


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: limit - 3] + "..."
