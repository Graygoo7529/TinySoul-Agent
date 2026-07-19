"""TinySoul app runtime entry point."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tinysoul.endpoint import EndpointEngine

from tinysoul.loop import ProgramOutcome, ProgramRunner, TurnOutcome

from .errors import AppInvariantError
from .inputs import InputDispatcher, InputEvent, InputSource
from .gateway import AppCommandGateway
from .outputs import ObservationRouter
from .services import AppService
from .sources import ProgramEventSource


@dataclass(frozen=True)
class TinySoulApp:
    """Process-level TinySoul application."""

    program_runner: ProgramRunner
    input_dispatcher: InputDispatcher
    gateway: AppCommandGateway
    input_sources: tuple[InputSource, ...] = field(default_factory=tuple)
    program_event_sources: tuple[ProgramEventSource, ...] = field(default_factory=tuple)
    services: tuple[AppService, ...] = field(default_factory=tuple)
    observations: ObservationRouter = field(default_factory=ObservationRouter)
    endpoint: EndpointEngine | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_sources", tuple(self.input_sources))
        object.__setattr__(self, "services", tuple(self.services))
        object.__setattr__(
            self,
            "program_event_sources",
            tuple(self.program_event_sources),
        )

    def run(self) -> ProgramOutcome:
        started: list[InputSource | ProgramEventSource | AppService] = []
        for source in self.program_event_sources:
            try:
                source.start(self.program_runner)
            except BaseException:
                self._stop_sources(started, suppress_errors=True)
                raise
            started.append(source)
        for service in self.services:
            try:
                service.start()
            except BaseException:
                self._stop_sources(started, suppress_errors=True)
                raise
            started.append(service)
        for source in self.input_sources:
            try:
                source.start(self.gateway)
            except BaseException:
                self._stop_sources(started, suppress_errors=True)
                raise
            started.append(source)
        try:
            outcome = self.program_runner.run()
        except BaseException:
            self._stop_sources(started, suppress_errors=True)
            raise
        self._stop_sources(started, suppress_errors=False)
        self.observations.raise_if_failed()
        return outcome

    def run_once(self, user_input: str) -> TurnOutcome:
        outcome = self.program_runner.run_once(user_input)
        self.observations.raise_if_failed()
        return outcome

    def submit_input(self, text: str, *, source: str = "api") -> None:
        self.submit_event(InputEvent(text=text, source=source))

    def submit_event(self, event: InputEvent) -> None:
        self.gateway.submit_user_event(event)

    def submit_interactive_event(self, event: InputEvent) -> None:
        """Submit a trusted local command line with decision semantics."""

        self.gateway.submit(event)

    def submit_user_input(self, text: str, *, source: str = "api") -> None:
        self.gateway.submit_user_input(text, source=source, metadata={})

    def stop_input_sources(self) -> None:
        self._stop_sources(self.input_sources, suppress_errors=False)

    def _stop_sources(
        self,
        sources: Sequence[InputSource | ProgramEventSource | AppService],
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
