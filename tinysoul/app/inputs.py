"""App-level input events, parsing and dispatching."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from queue import Queue
from time import time
from typing import Protocol
from uuid import uuid4

from tinysoul.context import build_input_append_signal
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.loop import LoopContractError, LoopControlKind, build_control_request_signal
from tinysoul.maintenance import BusinessDay, ProgramWorkMode

from .program import ProgramInputEvent
from tinysoul.runtime import (
    NullObservationEmitter,
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    RunLevel,
    RunScope,
    SignalBus,
    emit_observation,
    observation_enabled,
)

from .config import InputCommandSettings
from .errors import AppContractError


@dataclass(frozen=True)
class InputEvent:
    """External input normalized before entering TinySoul runtime."""

    text: str
    source: str = "api"
    received_at: float = field(default_factory=time)
    metadata: JsonObject = field(default_factory=dict)
    command_id: str = field(default_factory=lambda: f"command_{uuid4().hex}")

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
        if not isinstance(self.command_id, str) or not self.command_id.strip():
            raise AppContractError("InputEvent.command_id must be non-empty")
        if len(self.command_id) > 128:
            raise AppContractError("InputEvent.command_id is too long")
        object.__setattr__(self, "command_id", self.command_id.strip())


class InputIntentKind(StrEnum):
    """Parsed input intent kinds."""

    IGNORE = "ignore"
    START_TURN = "start_turn"
    APPEND_INPUT = "append_input"
    STOP_TURN = "stop_turn"
    HOME_MAINTENANCE = "home_maintenance"
    MEMORY_MAINTENANCE = "memory_maintenance"
    REJECTED = "rejected"
    EXIT_PROGRAM = "exit_program"


class MaintenanceRequestKind(StrEnum):
    HOME = "home"
    MEMORY = "memory"


@dataclass(frozen=True)
class InputIntent:
    """An input event classified by app command parsing."""

    kind: InputIntentKind
    text: str = ""
    source: str = ""
    target_day: BusinessDay | None = None
    error: str = ""
    metadata: JsonObject = field(default_factory=dict)
    command_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, InputIntentKind):
            raise AppContractError("InputIntent.kind must be an InputIntentKind")
        if not isinstance(self.text, str):
            raise AppContractError("InputIntent.text must be a string")
        if not isinstance(self.source, str):
            raise AppContractError("InputIntent.source must be a string")
        if self.target_day is not None and not isinstance(
            self.target_day,
            BusinessDay,
        ):
            raise AppContractError("InputIntent.target_day is invalid")
        if not isinstance(self.error, str):
            raise AppContractError("InputIntent.error must be a string")
        object.__setattr__(self, "metadata", to_json_object(self.metadata))
        if not isinstance(self.command_id, str) or not self.command_id:
            raise AppContractError("InputIntent.command_id must be non-empty")


@dataclass(frozen=True)
class CommandReceipt:
    """Stable acknowledgement for one external application command."""

    accepted: bool
    command_id: str
    kind: str
    state: str

    def to_json(self) -> JsonObject:
        return {
            "accepted": self.accepted,
            "command_id": self.command_id,
            "kind": self.kind,
            "state": self.state,
        }


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
        if normalized.startswith("/maintenance"):
            return self._maintenance_intent(event, stripped)
        if normalized in self._exit_commands:
            return self._intent(InputIntentKind.EXIT_PROGRAM, event, text=stripped)
        if turn_active and normalized in self._stop_turn_commands:
            return self._intent(InputIntentKind.STOP_TURN, event, text=stripped)
        if turn_active:
            return self._intent(InputIntentKind.APPEND_INPUT, event, text=stripped)
        return self._intent(InputIntentKind.START_TURN, event, text=stripped)

    def _maintenance_intent(self, event: InputEvent, text: str) -> InputIntent:
        parts = text.split()
        normalized = tuple(part.casefold() for part in parts)
        if normalized == ("/maintenance", "home"):
            return self._intent(InputIntentKind.HOME_MAINTENANCE, event, text=text)
        if len(parts) in {2, 3} and normalized[:2] == (
            "/maintenance",
            "memory",
        ):
            target_day = None
            if len(parts) == 3:
                try:
                    target_day = BusinessDay.parse(parts[2])
                except LoopContractError:
                    return self._intent(
                        InputIntentKind.REJECTED,
                        event,
                        text=text,
                        error="Memory Maintenance date must use YYYY-MM-DD.",
                    )
            return self._intent(
                InputIntentKind.MEMORY_MAINTENANCE,
                event,
                text=text,
                target_day=target_day,
            )
        return self._intent(
            InputIntentKind.REJECTED,
            event,
            text=text,
            error=(
                "Maintenance command must be /maintenance home or "
                "/maintenance memory [YYYY-MM-DD]."
            ),
        )

    def _intent(
        self,
        kind: InputIntentKind,
        event: InputEvent,
        *,
        text: str,
        target_day: BusinessDay | None = None,
        error: str = "",
    ) -> InputIntent:
        return InputIntent(
            kind=kind,
            text=text,
            source=event.source,
            target_day=target_day,
            error=error,
            metadata={
                **event.metadata,
                "received_at": event.received_at,
            },
            command_id=event.command_id,
        )


class InputSink(Protocol):
    """Consumer used by external input sources."""

    def submit(self, event: InputEvent) -> CommandReceipt:
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
        observations: ObservationEmitter | None = None,
        program_scope: RunScope | None = None,
    ) -> None:
        self._parser = parser
        self._bus = bus
        self._program_inputs = program_inputs
        self._active_turn_scope = active_turn_scope
        self._observations = observations or NullObservationEmitter()
        self._program_scope = program_scope or RunScope().push(
            RunLevel.PROGRAM,
            "program",
        )

    def submit(self, event: InputEvent) -> CommandReceipt:
        return self.dispatch(event)

    def dispatch(self, event: InputEvent) -> CommandReceipt:
        turn_scope = self._active_turn_scope()
        turn_active = turn_scope is not None
        intent = self._parser.parse(event, turn_active=turn_active)
        if intent.kind is InputIntentKind.IGNORE:
            return self._receipt(intent, accepted=True, state="ignored")
        if intent.kind is InputIntentKind.START_TURN:
            self._program_inputs.put(
                ProgramInputEvent.start_turn(
                    intent.text,
                    source=intent.source,
                    metadata=intent.metadata,
                    request_id=intent.command_id,
                )
            )
            return self._accepted(intent, state="queued", scope=self._program_scope)
        if intent.kind is InputIntentKind.HOME_MAINTENANCE:
            self._program_inputs.put(
                ProgramInputEvent.home_maintenance(
                    mode=ProgramWorkMode.MANUAL,
                    source=intent.source,
                    metadata=intent.metadata,
                    request_id=intent.command_id,
                )
            )
            return self._accepted(intent, state="queued", scope=self._program_scope)
        if intent.kind is InputIntentKind.MEMORY_MAINTENANCE:
            self._program_inputs.put(
                ProgramInputEvent.memory_maintenance(
                    mode=ProgramWorkMode.MANUAL,
                    target_day=intent.target_day,
                    source=intent.source,
                    metadata=intent.metadata,
                    request_id=intent.command_id,
                )
            )
            return self._accepted(intent, state="queued", scope=self._program_scope)
        if intent.kind is InputIntentKind.REJECTED:
            self._emit_rejected(intent)
            return self._receipt(intent, accepted=False, state="rejected")
        if intent.kind is InputIntentKind.EXIT_PROGRAM:
            if turn_active:
                self._emit_control(
                    LoopControlKind.EXIT_PROGRAM,
                    text=intent.text,
                    scope=turn_scope,
                )
                return self._accepted(
                    intent,
                    state="signaled",
                    scope=_require_turn_scope(turn_scope),
                )
            self._program_inputs.put(
                ProgramInputEvent.exit_program(
                    text=intent.text,
                    source=intent.source,
                    metadata=intent.metadata,
                    request_id=intent.command_id,
                )
            )
            return self._accepted(intent, state="queued", scope=self._program_scope)
        if intent.kind is InputIntentKind.STOP_TURN:
            self._emit_control(
                LoopControlKind.STOP_TURN,
                text=intent.text,
                scope=turn_scope,
            )
            return self._accepted(
                intent,
                state="signaled",
                scope=_require_turn_scope(turn_scope),
            )
        if intent.kind is InputIntentKind.APPEND_INPUT:
            self._bus.emit(
                build_input_append_signal(
                    intent.text,
                    scope=_require_turn_scope(turn_scope),
                    source="app.inputs",
                )
            )
            return self._accepted(
                intent,
                state="signaled",
                scope=_require_turn_scope(turn_scope),
            )
        raise AppContractError(f"Unsupported input intent: {intent.kind.value}")

    def request_maintenance(
        self,
        kind: MaintenanceRequestKind,
        *,
        target_day: BusinessDay | None,
        source: str,
        metadata: JsonObject,
        command_id: str,
    ) -> CommandReceipt:
        if not isinstance(kind, MaintenanceRequestKind):
            raise AppContractError("Maintenance request kind is invalid")
        if kind is MaintenanceRequestKind.HOME and target_day is not None:
            raise AppContractError("Home Maintenance cannot target a day")
        event = InputEvent(
            text=f"/maintenance {kind.value}",
            source=source,
            metadata=metadata,
            command_id=command_id,
        )
        intent = InputIntent(
            kind=(
                InputIntentKind.HOME_MAINTENANCE
                if kind is MaintenanceRequestKind.HOME
                else InputIntentKind.MEMORY_MAINTENANCE
            ),
            text=event.text,
            source=event.source,
            target_day=target_day,
            metadata={**event.metadata, "received_at": event.received_at},
            command_id=event.command_id,
        )
        if intent.kind is InputIntentKind.HOME_MAINTENANCE:
            self._program_inputs.put(
                ProgramInputEvent.home_maintenance(
                    mode=ProgramWorkMode.MANUAL,
                    source=source,
                    metadata=intent.metadata,
                    request_id=command_id,
                )
            )
        else:
            self._program_inputs.put(
                ProgramInputEvent.memory_maintenance(
                    mode=ProgramWorkMode.MANUAL,
                    target_day=target_day,
                    source=source,
                    metadata=intent.metadata,
                    request_id=command_id,
                )
            )
        return self._accepted(intent, state="queued", scope=self._program_scope)

    def request_control(
        self,
        kind: LoopControlKind,
        *,
        source: str,
        text: str = "",
        metadata: JsonObject | None = None,
    ) -> CommandReceipt:
        """Submit a typed external control without command-string parsing."""

        if not isinstance(kind, LoopControlKind):
            raise AppContractError("Input control kind is invalid")
        if not isinstance(source, str) or not source.strip():
            raise AppContractError("Input control source must be non-empty")
        payload = to_json_object(metadata or {})
        turn_scope = self._active_turn_scope()
        if kind is LoopControlKind.STOP_TURN:
            if turn_scope is None:
                raise AppContractError("No active Turn can be stopped")
            self._emit_control(kind, text=text, scope=turn_scope)
            intent = self._control_intent(kind, source, text, payload)
            return self._accepted(intent, state="signaled", scope=turn_scope)
        if kind is not LoopControlKind.EXIT_PROGRAM:
            raise AppContractError(f"Unsupported input control: {kind.value}")
        if turn_scope is not None:
            self._emit_control(kind, text=text, scope=turn_scope)
            intent = self._control_intent(kind, source, text, payload)
            return self._accepted(intent, state="signaled", scope=turn_scope)
        command_id = _command_id(payload)
        self._program_inputs.put(
            ProgramInputEvent.exit_program(
                text=text,
                source=source,
                metadata=payload,
                request_id=command_id,
            )
        )
        intent = self._control_intent(kind, source, text, payload, command_id=command_id)
        return self._accepted(intent, state="queued", scope=self._program_scope)

    def _emit_rejected(self, intent: InputIntent) -> None:
        if not observation_enabled(self._observations, ObservationLevel.NORMAL):
            return
        emit_observation(
            self._observations,
            ObservationEvent(
                name="app.command.rejected",
                level=ObservationLevel.NORMAL,
                source="app.inputs",
                scope=self._program_scope,
                message=intent.error,
                payload={
                    "command_id": intent.command_id,
                    "kind": intent.kind.value,
                    "input": intent.text,
                },
            ),
        )

    def _emit_control(
        self,
        kind: LoopControlKind,
        *,
        text: str,
        scope: RunScope | None,
    ) -> None:
        self._bus.emit(
            build_control_request_signal(
                kind,
                scope=_require_turn_scope(scope),
                source="app.inputs",
                text=text,
            )
        )

    def _accepted(
        self,
        intent: InputIntent,
        *,
        state: str,
        scope: RunScope,
    ) -> CommandReceipt:
        receipt = self._receipt(intent, accepted=True, state=state)
        if observation_enabled(self._observations, ObservationLevel.NORMAL):
            payload: JsonObject = receipt.to_json()
            payload["source"] = intent.source
            if intent.kind in {InputIntentKind.START_TURN, InputIntentKind.APPEND_INPUT}:
                payload["text"] = intent.text
            if intent.target_day is not None:
                payload["target_day"] = str(intent.target_day)
            emit_observation(
                self._observations,
                ObservationEvent(
                    name="app.command.accepted",
                    level=ObservationLevel.NORMAL,
                    source="app.inputs",
                    scope=scope,
                    message=f"Application command {intent.kind.value} accepted.",
                    payload=payload,
                ),
            )
        return receipt

    @staticmethod
    def _receipt(
        intent: InputIntent,
        *,
        accepted: bool,
        state: str,
    ) -> CommandReceipt:
        return CommandReceipt(
            accepted=accepted,
            command_id=intent.command_id,
            kind=intent.kind.value,
            state=state,
        )

    @staticmethod
    def _control_intent(
        kind: LoopControlKind,
        source: str,
        text: str,
        metadata: JsonObject,
        *,
        command_id: str | None = None,
    ) -> InputIntent:
        return InputIntent(
            kind=(
                InputIntentKind.STOP_TURN
                if kind is LoopControlKind.STOP_TURN
                else InputIntentKind.EXIT_PROGRAM
            ),
            text=text,
            source=source,
            metadata=metadata,
            command_id=command_id or _command_id(metadata),
        )


def _require_turn_scope(scope: RunScope | None) -> RunScope:
    if scope is None or scope.nearest(RunLevel.TURN) is None:
        raise AppContractError("Turn-scoped input has no active Turn scope")
    return scope


def _command_id(metadata: JsonObject) -> str:
    value = metadata.get("command_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return f"command_{uuid4().hex}"
