"""App-level input events, parsing and dispatching."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from queue import Queue
from time import time
from typing import Protocol

from tinysoul.context import build_input_append_signal
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.loop import LoopControlKind, build_control_request_signal
from tinysoul.loop.program import ProgramInputEvent
from tinysoul.runtime import RunLevel, RunScope, SignalBus

from .config import InputCommandSettings
from .errors import AppContractError


@dataclass(frozen=True)
class InputEvent:
    """External input normalized before entering TinySoul runtime."""

    text: str
    source: str = "api"
    received_at: float = field(default_factory=time)
    metadata: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise AppContractError("InputEvent.text must be a string")
        if not isinstance(self.source, str) or not self.source.strip():
            raise AppContractError("InputEvent.source must be a non-empty string")
        if isinstance(self.received_at, bool) or not isinstance(self.received_at, (int, float)):
            raise AppContractError("InputEvent.received_at must be a number")
        object.__setattr__(self, "source", self.source.strip())
        object.__setattr__(self, "received_at", float(self.received_at))
        object.__setattr__(self, "metadata", to_json_object(self.metadata))


class InputIntentKind(StrEnum):
    """Parsed input intent kinds."""

    IGNORE = "ignore"
    START_TURN = "start_turn"
    APPEND_INPUT = "append_input"
    STOP_TURN = "stop_turn"
    EXIT_PROGRAM = "exit_program"


@dataclass(frozen=True)
class InputIntent:
    """An input event classified by app command parsing."""

    kind: InputIntentKind
    text: str = ""
    source: str = ""
    metadata: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, InputIntentKind):
            raise AppContractError("InputIntent.kind must be an InputIntentKind")
        if not isinstance(self.text, str):
            raise AppContractError("InputIntent.text must be a string")
        if not isinstance(self.source, str):
            raise AppContractError("InputIntent.source must be a string")
        object.__setattr__(self, "metadata", to_json_object(self.metadata))


class InputCommandParser:
    """Pure input command parser without side effects."""

    def __init__(self, settings: InputCommandSettings | None = None) -> None:
        self._settings = settings or InputCommandSettings()
        self._exit_commands = {command.lower() for command in self._settings.exit_commands}
        self._stop_turn_commands = {
            command.lower() for command in self._settings.stop_turn_commands
        }

    def parse(self, event: InputEvent, *, turn_active: bool) -> InputIntent:
        stripped = event.text.strip()
        if not stripped:
            return self._intent(InputIntentKind.IGNORE, event, text="")
        normalized = stripped.lower()
        if normalized in self._exit_commands:
            return self._intent(InputIntentKind.EXIT_PROGRAM, event, text=stripped)
        if turn_active and normalized in self._stop_turn_commands:
            return self._intent(InputIntentKind.STOP_TURN, event, text=stripped)
        if turn_active:
            return self._intent(InputIntentKind.APPEND_INPUT, event, text=stripped)
        return self._intent(InputIntentKind.START_TURN, event, text=stripped)

    def _intent(
        self,
        kind: InputIntentKind,
        event: InputEvent,
        *,
        text: str,
    ) -> InputIntent:
        return InputIntent(
            kind=kind,
            text=text,
            source=event.source,
            metadata={
                **event.metadata,
                "received_at": event.received_at,
            },
        )


class InputSink(Protocol):
    """Consumer used by external input sources."""

    def submit(self, event: InputEvent) -> None:
        """Submit one external input event."""
        ...


class InputSource(Protocol):
    """External input event producer."""

    def start(self, sink: InputSink) -> None:
        """Start producing input events."""
        ...

    def stop(self) -> None:
        """Stop producing input events."""
        ...


class InputDispatcher:
    """Dispatch parsed input intents to program queue or runtime signals."""

    def __init__(
        self,
        *,
        parser: InputCommandParser,
        bus: SignalBus,
        program_inputs: Queue[ProgramInputEvent],
        active_turn_scope: Callable[[], RunScope | None],
    ) -> None:
        self._parser = parser
        self._bus = bus
        self._program_inputs = program_inputs
        self._active_turn_scope = active_turn_scope

    def submit(self, event: InputEvent) -> None:
        self.dispatch(event)

    def dispatch(self, event: InputEvent) -> None:
        turn_scope = self._active_turn_scope()
        turn_active = turn_scope is not None
        intent = self._parser.parse(event, turn_active=turn_active)
        if intent.kind is InputIntentKind.IGNORE:
            return
        if intent.kind is InputIntentKind.START_TURN:
            self._program_inputs.put(
                ProgramInputEvent.start_turn(
                    intent.text,
                    source=intent.source,
                    metadata=intent.metadata,
                )
            )
            return
        if intent.kind is InputIntentKind.EXIT_PROGRAM:
            if turn_active:
                self._emit_control(LoopControlKind.EXIT_PROGRAM, intent, turn_scope)
                return
            self._program_inputs.put(
                ProgramInputEvent.exit_program(
                    text=intent.text,
                    source=intent.source,
                    metadata=intent.metadata,
                )
            )
            return
        if intent.kind is InputIntentKind.STOP_TURN:
            self._emit_control(LoopControlKind.STOP_TURN, intent, turn_scope)
            return
        if intent.kind is InputIntentKind.APPEND_INPUT:
            self._bus.emit(
                build_input_append_signal(
                    intent.text,
                    scope=_require_turn_scope(turn_scope),
                    source="app.inputs",
                )
            )
            return
        raise AppContractError(f"Unsupported input intent: {intent.kind.value}")

    def _emit_control(
        self,
        kind: LoopControlKind,
        intent: InputIntent,
        scope: RunScope | None,
    ) -> None:
        self._bus.emit(
            build_control_request_signal(
                kind,
                scope=_require_turn_scope(scope),
                source="app.inputs",
                text=intent.text,
            )
        )


def _require_turn_scope(scope: RunScope | None) -> RunScope:
    if scope is None or scope.nearest(RunLevel.TURN) is None:
        raise AppContractError("Turn-scoped input has no active Turn scope")
    return scope
