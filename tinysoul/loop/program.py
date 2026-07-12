"""Program-level runner."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from queue import Queue

from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.runtime import (
    NullObservationEmitter,
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    RUNTIME_PROGRAM_END,
    RunLevel,
    RunScope,
    RuntimeException,
    RuntimeTrap,
    RuntimeTransfer,
    RuntimeTransferAction,
    SignalBus,
    emit_observation,
    observation_enabled,
)

from .errors import LoopContractError
from .turn import TurnOutcome, TurnRunner


class ProgramInputKind(StrEnum):
    """Top-level program input event kinds."""

    START_TURN = "start_turn"
    EXIT_PROGRAM = "exit_program"


@dataclass(frozen=True)
class ProgramInputEvent:
    """An input event already classified for ProgramRunner."""

    kind: ProgramInputKind
    text: str = ""
    source: str = ""
    metadata: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ProgramInputKind):
            raise LoopContractError("ProgramInputEvent.kind must be a ProgramInputKind")
        if not isinstance(self.text, str):
            raise LoopContractError("ProgramInputEvent.text must be a string")
        if not isinstance(self.source, str):
            raise LoopContractError("ProgramInputEvent.source must be a string")
        if self.kind is ProgramInputKind.START_TURN and not self.text:
            raise LoopContractError("START_TURN program input requires non-empty text")
        object.__setattr__(self, "metadata", to_json_object(self.metadata))

    @classmethod
    def start_turn(
        cls,
        text: str,
        *,
        source: str = "",
        metadata: JsonObject | None = None,
    ) -> "ProgramInputEvent":
        return cls(
            kind=ProgramInputKind.START_TURN,
            text=text,
            source=source,
            metadata=metadata or {},
        )

    @classmethod
    def exit_program(
        cls,
        *,
        text: str = "",
        source: str = "",
        metadata: JsonObject | None = None,
    ) -> "ProgramInputEvent":
        return cls(
            kind=ProgramInputKind.EXIT_PROGRAM,
            text=text,
            source=source,
            metadata=metadata or {},
        )


@dataclass(frozen=True)
class ProgramOutcome:
    """Outcome of a program run."""

    turns: tuple[TurnOutcome, ...]
    turn_count: int
    transfer: RuntimeTransfer | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.turn_count, bool)
            or not isinstance(self.turn_count, int)
            or self.turn_count < len(self.turns)
        ):
            raise LoopContractError(
                "ProgramOutcome.turn_count cannot be smaller than retained turns"
            )


class ProgramRunner:
    """Top-level program loop."""

    def __init__(
        self,
        *,
        turn_runner: TurnRunner,
        bus: SignalBus,
        trap: RuntimeTrap,
        input_queue: Queue[ProgramInputEvent] | None = None,
        retained_outcomes: int = 32,
        observations: ObservationEmitter | None = None,
    ) -> None:
        if (
            isinstance(retained_outcomes, bool)
            or not isinstance(retained_outcomes, int)
            or retained_outcomes <= 0
        ):
            raise LoopContractError("retained_outcomes must be positive")
        self._turn_runner = turn_runner
        self._bus = bus
        self._trap = trap
        self._input_queue: Queue[ProgramInputEvent] = input_queue or Queue()
        self._scope = RunScope().push(RunLevel.PROGRAM, "program")
        self._retained_outcomes = retained_outcomes
        self._observations = observations or NullObservationEmitter()

    def submit_event(self, event: ProgramInputEvent) -> None:
        self._input_queue.put(event)

    @property
    def scope(self) -> RunScope:
        return self._scope

    @property
    def input_queue(self) -> Queue[ProgramInputEvent]:
        return self._input_queue

    def run_once(self, user_input: str) -> TurnOutcome:
        return self._turn_runner.run(user_input, scope=self._scope)

    def run(self) -> ProgramOutcome:
        outcomes: deque[TurnOutcome] = deque(maxlen=self._retained_outcomes)
        turn_count = 0
        self._emit("program.started", "Program started.", {})
        while True:
            event = self._input_queue.get()
            if event.kind is ProgramInputKind.EXIT_PROGRAM:
                transfer = self._request_program_end(event)
                self._emit(
                    "program.completed",
                    "Program completed.",
                    {"turn_count": turn_count},
                )
                return ProgramOutcome(
                    turns=tuple(outcomes),
                    transfer=transfer,
                    turn_count=turn_count,
                )
            outcomes.append(self.run_once(event.text))
            turn_count += 1
            transfer = outcomes[-1].transfer
            if transfer is not None and transfer.target.level is RunLevel.PROGRAM:
                if transfer.action is RuntimeTransferAction.END:
                    self._emit(
                        "program.completed",
                        "Program completed.",
                        {"turn_count": turn_count},
                    )
                    return ProgramOutcome(
                        turns=tuple(outcomes),
                        transfer=transfer,
                        turn_count=turn_count,
                    )

    def _request_program_end(self, event: ProgramInputEvent) -> RuntimeTransfer:
        result = self._trap.capture(
            RuntimeException(
                reason=RUNTIME_PROGRAM_END,
                message="Program exit requested.",
                payload={
                    "input": event.text,
                    "source": event.source,
                    "metadata": event.metadata,
                },
            ),
            self._scope,
        )
        for signal in result.signals:
            self._bus.emit(signal)
        return result.transfer

    def _emit(self, name: str, message: str, payload: JsonObject) -> None:
        if not observation_enabled(
            self._observations,
            ObservationLevel.VERBOSE,
        ):
            return
        emit_observation(
            self._observations,
            ObservationEvent(
                name=name,
                level=ObservationLevel.VERBOSE,
                source="loop.program",
                scope=self._scope,
                message=message,
                payload=payload,
            ),
        )
