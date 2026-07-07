"""Program-level runner."""

from __future__ import annotations

from dataclasses import dataclass
from queue import Queue

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

from .config import LoopSettings
from .signals import LoopControlKind, build_control_request_signal, consume_control_requests
from .turn import TurnOutcome, TurnRunner


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
        settings: LoopSettings,
        input_queue: Queue[str] | None = None,
    ) -> None:
        self._turn_runner = turn_runner
        self._bus = bus
        self._trap = trap
        self._settings = settings
        self._input_queue: Queue[str] = input_queue or Queue()
        self._scope = RunScope().push(RunLevel.PROGRAM, "program")

    def submit_input(self, text: str) -> None:
        self._input_queue.put(text)

    @property
    def scope(self) -> RunScope:
        return self._scope

    @property
    def input_queue(self) -> Queue[str]:
        return self._input_queue

    def run_once(self, user_input: str) -> TurnOutcome:
        return self._turn_runner.run(user_input, scope=self._scope)

    def run(self) -> ProgramOutcome:
        outcomes: list[TurnOutcome] = []
        while True:
            transfer = self._consume_program_control()
            if transfer is not None:
                return ProgramOutcome(turns=tuple(outcomes), transfer=transfer)
            text = self._input_queue.get()
            if self._is_exit_command(text):
                transfer = self._request_program_end(text)
                return ProgramOutcome(turns=tuple(outcomes), transfer=transfer)
            outcomes.append(self.run_once(text))
            transfer = outcomes[-1].transfer
            if transfer is not None and transfer.target.level is RunLevel.PROGRAM:
                if transfer.action is RuntimeTransferAction.END:
                    return ProgramOutcome(turns=tuple(outcomes), transfer=transfer)
        return ProgramOutcome(turns=tuple(outcomes))

    def _consume_program_control(self) -> RuntimeTransfer | None:
        requests = consume_control_requests(self._bus)
        if any(request.kind is LoopControlKind.EXIT_PROGRAM for request in requests):
            return self._request_program_end("control")
        return None

    def _request_program_end(self, text: str) -> RuntimeTransfer:
        result = self._trap.capture(
            RuntimeException(
                reason=RUNTIME_PROGRAM_END,
                message="Program exit requested.",
                payload={"input": text},
            ),
            self._scope,
        )
        for signal in result.signals:
            self._bus.emit(signal)
        return result.transfer

    def _is_exit_command(self, text: str) -> bool:
        normalized = text.strip().lower()
        return normalized in {command.lower() for command in self._settings.exit_commands}
