"""TinySoul app runtime entry point."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from tinysoul.loop import ProgramOutcome, ProgramRunner, TurnOutcome

from .errors import AppInvariantError
from .inputs import InputDispatcher, InputEvent, InputSource
from .outputs import ObservationRouter
from .sources import ProgramEventSource


@dataclass(frozen=True)
class TinySoulApp:
    """Process-level TinySoul application."""

    program_runner: ProgramRunner
    input_dispatcher: InputDispatcher
    input_sources: tuple[InputSource, ...] = field(default_factory=tuple)
    program_event_sources: tuple[ProgramEventSource, ...] = field(default_factory=tuple)
    observations: ObservationRouter = field(default_factory=ObservationRouter)

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_sources", tuple(self.input_sources))
        object.__setattr__(
            self,
            "program_event_sources",
            tuple(self.program_event_sources),
        )

    def run(self) -> ProgramOutcome:
        started: list[InputSource] = []
        program_started: list[ProgramEventSource] = []
        for source in self.program_event_sources:
            try:
                source.start(self.program_runner)
            except BaseException:
                self._stop_sources(program_started, suppress_errors=True)
                raise
            program_started.append(source)
        for source in self.input_sources:
            try:
                source.start(self.input_dispatcher)
            except BaseException:
                self._stop_sources(started, suppress_errors=True)
                self._stop_sources(program_started, suppress_errors=True)
                raise
            started.append(source)
        try:
            outcome = self.program_runner.run()
        except BaseException:
            self._stop_sources(started, suppress_errors=True)
            self._stop_sources(program_started, suppress_errors=True)
            raise
        self._stop_sources((*started, *program_started), suppress_errors=False)
        self.observations.raise_if_failed()
        return outcome

    def run_once(self, user_input: str) -> TurnOutcome:
        outcome = self.program_runner.run_once(user_input)
        self.observations.raise_if_failed()
        return outcome

    def submit_input(self, text: str, *, source: str = "api") -> None:
        self.submit_event(InputEvent(text=text, source=source))

    def submit_event(self, event: InputEvent) -> None:
        self.input_dispatcher.submit(event)

    def stop_input_sources(self) -> None:
        self._stop_sources(self.input_sources, suppress_errors=False)

    def _stop_sources(
        self,
        sources: Sequence[InputSource | ProgramEventSource],
        *,
        suppress_errors: bool,
    ) -> None:
        errors: list[Exception] = []
        for source in reversed(tuple(sources)):
            try:
                source.stop()
            except Exception as exc:
                errors.append(exc)
        if errors and not suppress_errors:
            detail = "; ".join(
                f"{type(error).__name__}: {error}" for error in errors
            )
            raise AppInvariantError(f"Failed to stop app sources: {detail}")
