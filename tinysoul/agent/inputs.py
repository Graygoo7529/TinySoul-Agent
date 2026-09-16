"""External input parsing and dispatch to typed Program requests or Turn signals."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from uuid import uuid4
from tinysoul.environment.inputs import CommandReceipt, InputEvent, InputSource, InputSink

from tinysoul.agent.commands import AgentCommands
from tinysoul.agent.errors import AgentClosedError, AgentQueueFullError, AgentSDKError
from tinysoul.kernel.loop.inbox import InboxError, InboxCapacityError
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.infra.time import CalendarDay, CalendarDayError
from tinysoul.kernel.loop import LoopControlKind
from tinysoul.plugins.reflection import (ReflectionContractError, ReflectionRequest, ReflectionScope, ReflectionTrigger)
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

from .config import InputCommandSettings
from .errors import AgentContractError
from tinysoul.agent.requests import ExitRequest, UserTurnRequest


class InputIntentKind(StrEnum):
    IGNORE = "ignore"
    USER_TURN = "user_turn"
    APPEND_INPUT = "append_input"
    STOP_TURN = "stop_turn"
    MAINTENANCE = "maintenance"
    REJECTED = "rejected"
    EXIT_PROGRAM = "exit_program"
    REPLY = "reply"
    GRANT = "grant"


@dataclass(frozen=True)
class InputIntent:
    kind: InputIntentKind
    text: str = ""
    source: str = ""
    maintenance_scope: ReflectionScope | None = None
    target_day: CalendarDay | None = None
    error: str = ""
    metadata: JsonObject = field(default_factory=dict)
    command_id: str = ""
    correlation_id: str = ""
    cycles: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.kind, InputIntentKind):
            raise AgentContractError("Input intent kind is invalid")
        if self.kind is InputIntentKind.MAINTENANCE:
            if not isinstance(self.maintenance_scope, ReflectionScope):
                raise AgentContractError("Reflection intent requires a scope")
        elif self.maintenance_scope is not None:
            raise AgentContractError("Only Reflection intent can carry a scope")
        if self.target_day is not None and not isinstance(self.target_day, CalendarDay):
            raise AgentContractError("Input intent target day is invalid")
        if not isinstance(self.command_id, str) or not self.command_id:
            raise AgentContractError("Input intent command_id must be non-empty")
        object.__setattr__(self, "metadata", to_json_object(self.metadata))


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
        if normalized.split()[0] in {"/reply", "/grant"}:
            parts = text.split(maxsplit=2)
            if len(parts) != 3:
                return self._intent(InputIntentKind.REJECTED, event, error="Use /reply QUESTION_ID TEXT or /grant REQUEST_ID COUNT.")
            if parts[0].casefold() == "/reply":
                return replace(self._intent(InputIntentKind.REPLY, event, text=parts[2]), correlation_id=parts[1])
            if not parts[2].isascii() or not parts[2].isdigit() or len(parts[2]) > 6 or int(parts[2]) <= 0:
                return self._intent(InputIntentKind.REJECTED, event, error="Cycle grant must be a positive integer.")
            return replace(self._intent(InputIntentKind.GRANT, event), correlation_id=parts[1], cycles=int(parts[2]))
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
                maintenance_scope=ReflectionScope.DAILY,
            )
        if normalized == ("/maintenance", "home"):
            return self._intent(
                InputIntentKind.MAINTENANCE,
                event,
                text=text,
                maintenance_scope=ReflectionScope.HOME,
            )
        if len(parts) >= 2 and normalized[:2] == ("/maintenance", "memory"):
            target: CalendarDay | None = None
            try:
                for argument in parts[2:]:
                    if target is None:
                        target = CalendarDay.parse(argument)
                    else:
                        raise ReflectionContractError("too many arguments")
            except (CalendarDayError, ReflectionContractError):
                return self._rejected(event, text)
            if target is None:
                return self._rejected(event, text)
            return self._intent(
                InputIntentKind.MAINTENANCE,
                event,
                text=text,
                maintenance_scope=ReflectionScope.MEMORY,
                target_day=target,
            )
        return self._rejected(event, text)

    def _rejected(self, event: InputEvent, text: str) -> InputIntent:
        return self._intent(
            InputIntentKind.REJECTED,
            event,
            text=text,
            error=(
                "Use /maintenance [daily|home] or "
                "/maintenance memory YYYY-MM-DD."
            ),
        )

    def _intent(
        self,
        kind: InputIntentKind,
        event: InputEvent,
        *,
        text: str = "",
        maintenance_scope: ReflectionScope | None = None,
        target_day: CalendarDay | None = None,
        error: str = "",
    ) -> InputIntent:
        return InputIntent(
            kind=kind,
            text=text,
            source=event.source,
            maintenance_scope=maintenance_scope,
            target_day=target_day,
            error=error,
            metadata=event.metadata,
            command_id=event.command_id,
        )


class InputDispatcher:
    """Parse commands and call the same Agent facade used by SDK consumers."""

    def __init__(
        self, *, parser: InputCommandParser, commands: AgentCommands,
        observations: ObservationEmitter | None = None,
        agent_scope: RunScope | None = None,
        parser_provider: Callable[[], InputCommandParser] | None = None,
    ) -> None:
        self._parser = parser
        self._commands = commands
        self._observations = observations or NullObservationEmitter()
        self._agent_scope = agent_scope or RunScope().push(RunLevel.AGENT, "program")
        self._parser_provider = parser_provider

    @property
    def active_turn_scope(self) -> RunScope | None:
        active = self._commands.active_turn
        return self._agent_scope.push(RunLevel.TURN, active.turn_id) if active is not None else None

    async def submit(self, event: InputEvent) -> CommandReceipt:
        active = self._commands.active_turn
        parser = self._parser_provider() if self._parser_provider is not None else self._parser
        intent = parser.parse(event, turn_active=active is not None)
        scope = self.active_turn_scope or self._agent_scope
        try:
            if intent.kind is InputIntentKind.IGNORE:
                return self._receipt(intent, True, "ignored")
            if intent.kind is InputIntentKind.REJECTED:
                self._emit_rejected(intent)
                return self._receipt(intent, False, "rejected")
            if intent.kind is InputIntentKind.USER_TURN:
                await self._commands.submit_turn(UserTurnRequest(
                    intent.text, source=intent.source, request_id=intent.command_id,
                    metadata=intent.metadata,
                ))
                return self._accepted(intent, "queued", scope)
            if intent.kind is InputIntentKind.MAINTENANCE:
                assert intent.maintenance_scope is not None
                await self._commands.request_reflection(ReflectionRequest(
                    scope=intent.maintenance_scope, trigger=ReflectionTrigger.MANUAL,
                    target_day=intent.target_day, source=intent.source,
                    request_id=intent.command_id, metadata=intent.metadata,
                ))
                return self._accepted(intent, "queued", scope)
            if intent.kind is InputIntentKind.EXIT_PROGRAM:
                self._commands.request_exit(ExitRequest(
                    text=intent.text, source=intent.source, request_id=intent.command_id,
                    metadata=intent.metadata,
                ))
                return self._accepted(intent, "signaled", scope)
            if active is None:
                raise AgentClosedError("There is no active Turn")
            if intent.kind is InputIntentKind.STOP_TURN:
                if not self._commands.cancel_turn(active.turn_id):
                    raise AgentClosedError("Turn is already finished")
            elif intent.kind is InputIntentKind.APPEND_INPUT:
                await self._commands.append_input(active.turn_id, intent.text, input_id=intent.command_id)
            elif intent.kind is InputIntentKind.REPLY:
                await self._commands.reply(active.turn_id, intent.correlation_id, intent.text)
            elif intent.kind is InputIntentKind.GRANT:
                await self._commands.grant_cycles(active.turn_id, intent.correlation_id, intent.cycles)
            else:
                raise AgentContractError("Unsupported input intent")
            return self._accepted(intent, "signaled", scope)
        except (AgentSDKError, InboxError) as exc:
            rejected = replace(intent, error=type(exc).__name__)
            self._emit_rejected(rejected)
            state = "full" if isinstance(exc, (AgentQueueFullError, InboxCapacityError)) else "rejected"
            return self._receipt(intent, False, state)

    async def request_maintenance(
        self, scope: ReflectionScope, *, target_day: CalendarDay | None,
        source: str, metadata: JsonObject, command_id: str,
    ) -> CommandReceipt:
        request = ReflectionRequest(
            scope=scope, trigger=ReflectionTrigger.MANUAL, target_day=target_day,
            source=source, metadata=metadata, request_id=command_id,
        )
        try:
            await self._commands.request_reflection(request)
        except AgentQueueFullError:
            return CommandReceipt(False, command_id, InputIntentKind.MAINTENANCE.value, "full")
        return CommandReceipt(True, command_id, InputIntentKind.MAINTENANCE.value, "queued")

    async def request_control(
        self, kind: LoopControlKind, *, source: str, text: str = "",
        metadata: JsonObject | None = None,
    ) -> CommandReceipt:
        if not isinstance(kind, LoopControlKind):
            raise AgentContractError("Input control kind is invalid")
        payload = to_json_object(metadata or {})
        command_id = _command_id(payload)
        if kind is LoopControlKind.EXIT_PROGRAM:
            self._commands.request_exit(ExitRequest(
                text=text, source=source, metadata=payload, request_id=command_id,
            ))
            accepted = True
        else:
            active = self._commands.active_turn
            accepted = active is not None and self._commands.cancel_turn(active.turn_id)
        return CommandReceipt(accepted, command_id, kind.value, "signaled" if accepted else "rejected")

    def _accepted(
        self, intent: InputIntent, state: str, scope: RunScope
    ) -> CommandReceipt:
        receipt = self._receipt(intent, True, state)
        if observation_enabled(self._observations, ObservationLevel.NORMAL):
            text_payload = (
                {"text": intent.text}
                if intent.kind
                in {InputIntentKind.USER_TURN, InputIntentKind.APPEND_INPUT}
                and intent.text
                else {}
            )
            emit_observation(
                self._observations,
                ObservationEvent(
                    name="app.command.accepted",
                    level=ObservationLevel.NORMAL,
                    source="app.inputs",
                    scope=scope,
                    message=f"Application command {intent.kind.value} accepted.",
                    payload={
                        **receipt.to_json(),
                        "source": intent.source,
                        **text_payload,
                    },
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
                    scope=self._agent_scope,
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


def _command_id(metadata: JsonObject) -> str:
    value = metadata.get("command_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return f"command_{uuid4().hex}"
