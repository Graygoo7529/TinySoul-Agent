"""TinySoul app runtime entry point."""

from __future__ import annotations

from dataclasses import dataclass, field

from tinysoul.loop import ProgramOutcome, ProgramRunner, TurnOutcome

from .inputs import InputDispatcher, InputEvent, InputSource


@dataclass(frozen=True)
class TinySoulApp:
    """Process-level TinySoul application."""

    program_runner: ProgramRunner
    input_dispatcher: InputDispatcher
    input_sources: tuple[InputSource, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_sources", tuple(self.input_sources))

    def run(self) -> ProgramOutcome:
        for source in self.input_sources:
            source.start(self.input_dispatcher)
        try:
            return self.program_runner.run()
        finally:
            self.stop_input_sources()

    def run_once(self, user_input: str) -> TurnOutcome:
        return self.program_runner.run_once(user_input)

    def submit_input(self, text: str, *, source: str = "api") -> None:
        self.submit_event(InputEvent(text=text, source=source))

    def submit_event(self, event: InputEvent) -> None:
        self.input_dispatcher.submit(event)

    def stop_input_sources(self) -> None:
        for source in self.input_sources:
            source.stop()
