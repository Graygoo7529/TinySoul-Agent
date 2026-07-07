"""Program-level runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from queue import Queue

from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.runtime import (
    RUNTIME_PROGRAM_END,
    RunLevel,
    RunScope,
    RuntimeException,
    RuntimeTrap,
    RuntimeTransfer,
    RuntimeTransferAction,
    SignalBus,
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
    transfer: RuntimeTransfer | None = None


class ProgramRunner:
    """Top-level program loop."""

    def __init__(
        self,
        *,
        turn_runner: TurnRunner,
        bus: SignalBus,
        trap: RuntimeTrap,
        input_queue: Queue[ProgramInputEvent] | None = None,
    ) -> None:
        self._turn_runner = turn_runner
        self._bus = bus
        self._trap = trap
        self._input_queue: Queue[ProgramInputEvent] = input_queue or Queue()
        self._scope = RunScope().push(RunLevel.PROGRAM, "program")

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
        outcomes: list[TurnOutcome] = []
        while True:
            event = self._input_queue.get()
            if event.kind is ProgramInputKind.EXIT_PROGRAM:
                transfer = self._request_program_end(event)
                return ProgramOutcome(turns=tuple(outcomes), transfer=transfer)
            outcomes.append(self.run_once(event.text))
            transfer = outcomes[-1].transfer
            if transfer is not None and transfer.target.level is RunLevel.PROGRAM:
                if transfer.action is RuntimeTransferAction.END:
                    return ProgramOutcome(turns=tuple(outcomes), transfer=transfer)
        return ProgramOutcome(turns=tuple(outcomes))

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
