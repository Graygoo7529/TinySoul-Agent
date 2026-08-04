"""External input parsing and dispatch to typed Program requests or Turn signals."""

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
from tinysoul.infra.time import BusinessDay, BusinessDayError
from tinysoul.loop import LoopControlKind, build_control_request_signal
from tinysoul.maintenance import (
    MaintenanceContractError,
    MaintenanceRequest,
    MaintenanceScope,
    MaintenanceTrigger,
)
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
from .requests import AppRequest, ExitRequest, UserTurnRequest


@dataclass(frozen=True)
class InputEvent:
    text: str
    source: str = "api"
    received_at: float = field(default_factory=time)
    metadata: JsonObject = field(default_factory=dict)
    command_id: str = field(default_factory=lambda: f"command_{uuid4().hex}")

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise AppContractError("InputEvent.text must be a string")
        if not isinstance(self.source, str) or not self.source.strip():
            raise AppContractError("InputEvent.source must be non-empty")
        if isinstance(self.received_at, bool) or not isinstance(
            self.received_at, (int, float)
        ):
            raise AppContractError("InputEvent.received_at must be numeric")
        if not isinstance(self.command_id, str) or not self.command_id.strip():
            raise AppContractError("InputEvent.command_id must be non-empty")
        object.__setattr__(self, "source", self.source.strip())
        object.__setattr__(self, "received_at", float(self.received_at))
        object.__setattr__(self, "metadata", to_json_object(self.metadata))
        object.__setattr__(self, "command_id", self.command_id.strip())


class InputIntentKind(StrEnum):
    IGNORE = "ignore"
    USER_TURN = "user_turn"
    APPEND_INPUT = "append_input"
    STOP_TURN = "stop_turn"
    MAINTENANCE = "maintenance"
    REJECTED = "rejected"
    EXIT_PROGRAM = "exit_program"


@dataclass(frozen=True)
class InputIntent:
    kind: InputIntentKind
    text: str = ""
    source: str = ""
    maintenance_scope: MaintenanceScope | None = None
    target_day: BusinessDay | None = None
    rebuild_memory: bool = False
    error: str = ""
    metadata: JsonObject = field(default_factory=dict)
    command_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, InputIntentKind):
            raise AppContractError("Input intent kind is invalid")
        if self.kind is InputIntentKind.MAINTENANCE:
            if not isinstance(self.maintenance_scope, MaintenanceScope):
                raise AppContractError("Maintenance intent requires a scope")
        elif self.maintenance_scope is not None:
            raise AppContractError("Only Maintenance intent can carry a scope")
        if self.target_day is not None and not isinstance(self.target_day, BusinessDay):
            raise AppContractError("Input intent target day is invalid")
        if not isinstance(self.rebuild_memory, bool):
            raise AppContractError("Input intent rebuild flag is invalid")
        if not isinstance(self.command_id, str) or not self.command_id:
            raise AppContractError("Input intent command_id must be non-empty")
        object.__setattr__(self, "metadata", to_json_object(self.metadata))


@dataclass(frozen=True)
class CommandReceipt:
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
    """Parse local command syntax without executing application work."""

    def __init__(self, settings: InputCommandSettings | None = None) -> None:
        self._settings = settings or InputCommandSettings()
        self._exit_commands = {item.casefold() for item in self._settings.exit_commands}
        self._stop_commands = {
            item.casefold() for item in self._settings.stop_turn_commands
        }

    def parse(self, event: InputEvent, *, turn_active: bool) -> InputIntent:
        text = event.text.strip()
        if not text:
            return self._intent(InputIntentKind.IGNORE, event)
        normalized = text.casefold()
        if normalized.startswith("/maintenance"):
            return self._maintenance(event, text)
        if normalized in self._exit_commands:
            return self._intent(InputIntentKind.EXIT_PROGRAM, event, text=text)
        if turn_active and normalized in self._stop_commands:
            return self._intent(InputIntentKind.STOP_TURN, event, text=text)
        return self._intent(
            InputIntentKind.APPEND_INPUT if turn_active else InputIntentKind.USER_TURN,
            event,
            text=text,
        )

    def _maintenance(self, event: InputEvent, text: str) -> InputIntent:
        parts = text.split()
        normalized = tuple(part.casefold() for part in parts)
        if normalized == ("/maintenance",) or normalized == (
            "/maintenance",
            "daily",
        ):
            return self._intent(
                InputIntentKind.MAINTENANCE,
                event,
                text=text,
                maintenance_scope=MaintenanceScope.DAILY,
            )
        if normalized == ("/maintenance", "home"):
            return self._intent(
                InputIntentKind.MAINTENANCE,
                event,
                text=text,
                maintenance_scope=MaintenanceScope.HOME,
            )
        if len(parts) >= 2 and normalized[:2] == ("/maintenance", "memory"):
            target: BusinessDay | None = None
            rebuild = False
            try:
                for argument in parts[2:]:
                    if argument.casefold() == "--rebuild":
                        if rebuild:
                            raise MaintenanceContractError("duplicate --rebuild")
                        rebuild = True
                    elif target is None:
                        target = BusinessDay.parse(argument)
                    else:
                        raise MaintenanceContractError("too many arguments")
            except (BusinessDayError, MaintenanceContractError):
                return self._rejected(event, text)
            if target is None:
                return self._rejected(event, text)
            return self._intent(
                InputIntentKind.MAINTENANCE,
                event,
                text=text,
                maintenance_scope=MaintenanceScope.MEMORY,
                target_day=target,
                rebuild_memory=rebuild,
            )
        return self._rejected(event, text)

    def _rejected(self, event: InputEvent, text: str) -> InputIntent:
        return self._intent(
            InputIntentKind.REJECTED,
            event,
            text=text,
            error=(
                "Use /maintenance [daily|home] or "
                "/maintenance memory YYYY-MM-DD [--rebuild]."
            ),
        )

    def _intent(
        self,
        kind: InputIntentKind,
        event: InputEvent,
        *,
        text: str = "",
        maintenance_scope: MaintenanceScope | None = None,
        target_day: BusinessDay | None = None,
        rebuild_memory: bool = False,
        error: str = "",
    ) -> InputIntent:
        return InputIntent(
            kind=kind,
            text=text,
            source=event.source,
            maintenance_scope=maintenance_scope,
            target_day=target_day,
            rebuild_memory=rebuild_memory,
            error=error,
            metadata={**event.metadata, "received_at": event.received_at},
            command_id=event.command_id,
        )


class InputSink(Protocol):
    def submit(self, event: InputEvent) -> CommandReceipt: ...


class InputSource(Protocol):
    def start(self, sink: InputSink) -> None: ...

    def stop(self) -> None: ...


class InputDispatcher:
    """Route parsed input to the Program queue or the active User Turn."""

    def __init__(
        self,
        *,
        parser: InputCommandParser,
        bus: SignalBus,
        program_inputs: Queue[AppRequest],
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
            RunLevel.PROGRAM, "program"
        )

    def submit(self, event: InputEvent) -> CommandReceipt:
        turn_scope = self._active_turn_scope()
        intent = self._parser.parse(event, turn_active=turn_scope is not None)
        if intent.kind is InputIntentKind.IGNORE:
            return self._receipt(intent, True, "ignored")
        if intent.kind is InputIntentKind.USER_TURN:
            self._program_inputs.put(
                UserTurnRequest(
                    intent.text,
                    source=intent.source,
                    request_id=intent.command_id,
                    metadata=intent.metadata,
                )
            )
            return self._accepted(intent, "queued", self._program_scope)
        if intent.kind is InputIntentKind.MAINTENANCE:
            assert intent.maintenance_scope is not None
            self._program_inputs.put(
                MaintenanceRequest(
                    scope=intent.maintenance_scope,
                    trigger=MaintenanceTrigger.MANUAL,
                    target_day=intent.target_day,
                    rebuild_memory=intent.rebuild_memory,
                    source=intent.source,
                    request_id=intent.command_id,
                    metadata=intent.metadata,
                )
            )
            return self._accepted(intent, "queued", self._program_scope)
        if intent.kind is InputIntentKind.REJECTED:
            self._emit_rejected(intent)
            return self._receipt(intent, False, "rejected")
        if intent.kind is InputIntentKind.EXIT_PROGRAM:
            if turn_scope is not None:
                self._emit_control(LoopControlKind.EXIT_PROGRAM, intent.text, turn_scope)
                return self._accepted(intent, "signaled", turn_scope)
            self._program_inputs.put(
                ExitRequest(
                    text=intent.text,
                    source=intent.source,
                    request_id=intent.command_id,
                    metadata=intent.metadata,
                )
            )
            return self._accepted(intent, "queued", self._program_scope)
        if intent.kind is InputIntentKind.STOP_TURN:
            scope = _require_turn_scope(turn_scope)
            self._emit_control(LoopControlKind.STOP_TURN, intent.text, scope)
            return self._accepted(intent, "signaled", scope)
        if intent.kind is InputIntentKind.APPEND_INPUT:
            scope = _require_turn_scope(turn_scope)
            self._bus.emit(
                build_input_append_signal(
                    intent.text, scope=scope, source="app.inputs"
                )
            )
            return self._accepted(intent, "signaled", scope)
        raise AppContractError(f"Unsupported input intent: {intent.kind.value}")

    def request_maintenance(
        self,
        scope: MaintenanceScope,
        *,
        target_day: BusinessDay | None,
        rebuild_memory: bool,
        source: str,
        metadata: JsonObject,
        command_id: str,
    ) -> CommandReceipt:
        request = MaintenanceRequest(
            scope=scope,
            trigger=MaintenanceTrigger.MANUAL,
            target_day=target_day,
            rebuild_memory=rebuild_memory,
            source=source,
            metadata=metadata,
            request_id=command_id,
        )
        self._program_inputs.put(request)
        intent = InputIntent(
            kind=InputIntentKind.MAINTENANCE,
            source=source,
            maintenance_scope=scope,
            target_day=target_day,
            rebuild_memory=rebuild_memory,
            metadata=metadata,
            command_id=command_id,
        )
        return self._accepted(intent, "queued", self._program_scope)

    def request_control(
        self,
        kind: LoopControlKind,
        *,
        source: str,
        text: str = "",
        metadata: JsonObject | None = None,
    ) -> CommandReceipt:
        if not isinstance(kind, LoopControlKind):
            raise AppContractError("Input control kind is invalid")
        payload = to_json_object(metadata or {})
        turn_scope = self._active_turn_scope()
        command_id = _command_id(payload)
        intent = InputIntent(
            kind=(
                InputIntentKind.STOP_TURN
                if kind is LoopControlKind.STOP_TURN
                else InputIntentKind.EXIT_PROGRAM
            ),
            text=text,
            source=source,
            metadata=payload,
            command_id=command_id,
        )
        if kind is LoopControlKind.STOP_TURN:
            scope = _require_turn_scope(turn_scope)
            self._emit_control(kind, text, scope)
            return self._accepted(intent, "signaled", scope)
        if kind is not LoopControlKind.EXIT_PROGRAM:
            raise AppContractError(f"Unsupported input control: {kind.value}")
        if turn_scope is not None:
            self._emit_control(kind, text, turn_scope)
            return self._accepted(intent, "signaled", turn_scope)
        self._program_inputs.put(
            ExitRequest(
                text=text,
                source=source,
                metadata=payload,
                request_id=command_id,
            )
        )
        return self._accepted(intent, "queued", self._program_scope)

    def _emit_control(self, kind: LoopControlKind, text: str, scope: RunScope) -> None:
        self._bus.emit(
            build_control_request_signal(
                kind, scope=scope, source="app.inputs", text=text
            )
        )

    def _accepted(
        self, intent: InputIntent, state: str, scope: RunScope
    ) -> CommandReceipt:
        receipt = self._receipt(intent, True, state)
        if observation_enabled(self._observations, ObservationLevel.NORMAL):
            emit_observation(
                self._observations,
                ObservationEvent(
                    name="app.command.accepted",
                    level=ObservationLevel.NORMAL,
                    source="app.inputs",
                    scope=scope,
                    message=f"Application command {intent.kind.value} accepted.",
                    payload={**receipt.to_json(), "source": intent.source},
                ),
            )
        return receipt

    def _emit_rejected(self, intent: InputIntent) -> None:
        if observation_enabled(self._observations, ObservationLevel.NORMAL):
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
                        "input": intent.text,
                    },
                ),
            )

    @staticmethod
    def _receipt(intent: InputIntent, accepted: bool, state: str) -> CommandReceipt:
        return CommandReceipt(accepted, intent.command_id, intent.kind.value, state)


def _require_turn_scope(scope: RunScope | None) -> RunScope:
    if scope is None or scope.nearest(RunLevel.TURN) is None:
        raise AppContractError("Turn-scoped input has no active Turn scope")
    return scope


def _command_id(metadata: JsonObject) -> str:
    value = metadata.get("command_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return f"command_{uuid4().hex}"
