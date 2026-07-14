"""Program-level runner."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from queue import Queue
from threading import RLock

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
from tinysoul.runtime.bridge import RuntimeLoopBridge

from .daily import DailyLifecycleCoordinator
from .day import BusinessClock, BusinessDay, IanaBusinessClock
from .errors import LoopContractError, LoopError
from .maintenance import ProgramMaintenanceRunner
from .turn import TurnOutcome, TurnRunner
from .work import (
    ProgramWorkMode,
    ProgramWorkOutcome,
    ProgramWorkStatus,
)


class ProgramInputKind(StrEnum):
    """Top-level program input event kinds."""

    START_TURN = "start_turn"
    DAILY_ROLLOVER = "daily_rollover"
    HOME_MAINTENANCE = "home_maintenance"
    MEMORY_MAINTENANCE = "memory_maintenance"
    EXIT_PROGRAM = "exit_program"


@dataclass(frozen=True)
class ProgramInputEvent:
    """An input event already classified for ProgramRunner."""

    kind: ProgramInputKind
    text: str = ""
    source: str = ""
    mode: ProgramWorkMode | None = None
    target_day: BusinessDay | None = None
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
        maintenance_kinds = {
            ProgramInputKind.HOME_MAINTENANCE,
            ProgramInputKind.MEMORY_MAINTENANCE,
        }
        if self.kind in maintenance_kinds:
            if not isinstance(self.mode, ProgramWorkMode):
                raise LoopContractError(
                    "Maintenance program input requires a ProgramWorkMode"
                )
        elif self.mode is not None:
            raise LoopContractError(
                "Non-maintenance program input cannot carry a work mode"
            )
        if self.target_day is not None and not isinstance(
            self.target_day,
            BusinessDay,
        ):
            raise LoopContractError("Program input target_day is invalid")
        if (
            self.kind is not ProgramInputKind.MEMORY_MAINTENANCE
            and self.target_day is not None
        ):
            raise LoopContractError(
                "Only Memory Maintenance input can carry target_day"
            )
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

    @classmethod
    def daily_rollover(
        cls,
        *,
        source: str = "",
        metadata: JsonObject | None = None,
    ) -> "ProgramInputEvent":
        return cls(
            kind=ProgramInputKind.DAILY_ROLLOVER,
            source=source,
            metadata=metadata or {},
        )

    @classmethod
    def home_maintenance(
        cls,
        *,
        mode: ProgramWorkMode,
        source: str = "",
        metadata: JsonObject | None = None,
    ) -> "ProgramInputEvent":
        return cls(
            kind=ProgramInputKind.HOME_MAINTENANCE,
            mode=mode,
            source=source,
            metadata=metadata or {},
        )

    @classmethod
    def memory_maintenance(
        cls,
        *,
        mode: ProgramWorkMode,
        target_day: BusinessDay | None = None,
        source: str = "",
        metadata: JsonObject | None = None,
    ) -> "ProgramInputEvent":
        return cls(
            kind=ProgramInputKind.MEMORY_MAINTENANCE,
            mode=mode,
            target_day=target_day,
            source=source,
            metadata=metadata or {},
        )


@dataclass(frozen=True)
class ProgramOutcome:
    """Outcome of a program run."""

    turns: tuple[TurnOutcome, ...]
    turn_count: int
    works: tuple[ProgramWorkOutcome, ...] = field(default_factory=tuple)
    work_count: int = 0
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
        if (
            isinstance(self.work_count, bool)
            or not isinstance(self.work_count, int)
            or self.work_count < len(self.works)
        ):
            raise LoopContractError(
                "ProgramOutcome.work_count cannot be smaller than retained works"
            )
        if any(not isinstance(work, ProgramWorkOutcome) for work in self.works):
            raise LoopContractError("ProgramOutcome.works contains an invalid outcome")
        object.__setattr__(self, "works", tuple(self.works))


class ProgramRunner:
    """Top-level program loop."""

    def __init__(
        self,
        *,
        turn_runner: TurnRunner,
        bus: SignalBus,
        trap: RuntimeTrap,
        daily_lifecycle: DailyLifecycleCoordinator,
        maintenance_runner: ProgramMaintenanceRunner | None = None,
        input_queue: Queue[ProgramInputEvent] | None = None,
        retained_outcomes: int = 32,
        business_clock: BusinessClock | None = None,
        loop_bridge: RuntimeLoopBridge | None = None,
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
        self._daily_lifecycle = daily_lifecycle
        self._maintenance_runner = maintenance_runner
        self._input_queue: Queue[ProgramInputEvent] = input_queue or Queue()
        self._scope = RunScope().push(RunLevel.PROGRAM, "program")
        self._retained_outcomes = retained_outcomes
        self._business_clock = business_clock or IanaBusinessClock()
        self._loop_bridge = loop_bridge or RuntimeLoopBridge()
        self._observations = observations or NullObservationEmitter()
        self._work_lock = RLock()

    def submit_event(self, event: ProgramInputEvent) -> None:
        self._input_queue.put(event)

    @property
    def scope(self) -> RunScope:
        return self._scope

    @property
    def input_queue(self) -> Queue[ProgramInputEvent]:
        return self._input_queue

    def run_once(self, user_input: str) -> TurnOutcome:
        with self._work_lock:
            business_day = self._ensure_active_day()
            return self._turn_runner.run(
                user_input,
                business_day=business_day,
                scope=self._scope,
            )

    def run(self) -> ProgramOutcome:
        outcomes: deque[TurnOutcome] = deque(maxlen=self._retained_outcomes)
        works: deque[ProgramWorkOutcome] = deque(maxlen=self._retained_outcomes)
        turn_count = 0
        work_count = 0
        business_day = self._ensure_active_day()
        self._emit("program.started", "Program started.", {})
        self._emit_availability(business_day)
        while True:
            event = self._input_queue.get()
            if event.kind is ProgramInputKind.EXIT_PROGRAM:
                transfer = self._request_program_end(event)
                self._emit(
                    "program.completed",
                    "Program completed.",
                    {"turn_count": turn_count, "work_count": work_count},
                )
                return ProgramOutcome(
                    turns=tuple(outcomes),
                    works=tuple(works),
                    transfer=transfer,
                    turn_count=turn_count,
                    work_count=work_count,
                )
            if event.kind is ProgramInputKind.DAILY_ROLLOVER:
                with self._work_lock:
                    self._ensure_active_day()
                continue
            if event.kind is ProgramInputKind.START_TURN:
                outcomes.append(self.run_once(event.text))
                turn_count += 1
                transfer = outcomes[-1].transfer
                if transfer is not None and transfer.target.level is RunLevel.PROGRAM:
                    if transfer.action is RuntimeTransferAction.END:
                        self._emit(
                            "program.completed",
                            "Program completed.",
                            {"turn_count": turn_count, "work_count": work_count},
                        )
                        return ProgramOutcome(
                            turns=tuple(outcomes),
                            works=tuple(works),
                            transfer=transfer,
                            turn_count=turn_count,
                            work_count=work_count,
                        )
                continue
            work = self._run_maintenance(event)
            works.append(work)
            work_count += 1
            self._emit_work(work)

    def _ensure_active_day(self) -> BusinessDay:
        now = self._business_clock.now()
        business_day = BusinessDay(now.date())
        try:
            self._daily_lifecycle.ensure_active_day(business_day, now=now)
        except LoopError as exc:
            raise self._loop_bridge.startup_failure(
                message=str(exc),
                payload={
                    "stage": "daily_rollover",
                    "business_day": str(business_day),
                },
            ) from exc
        return business_day

    def _run_maintenance(self, event: ProgramInputEvent) -> ProgramWorkOutcome:
        with self._work_lock:
            business_day = self._ensure_active_day()
            runner = self._maintenance_runner
            if runner is None:
                raise LoopContractError(
                    "Program received Maintenance input without a runner"
                )
            if not isinstance(event.mode, ProgramWorkMode):
                raise LoopContractError("Maintenance event mode disappeared")
            if event.kind is ProgramInputKind.HOME_MAINTENANCE:
                return runner.run_home(
                    business_day=business_day,
                    mode=event.mode,
                    source=event.source,
                    scope=self._scope,
                )
            if event.kind is ProgramInputKind.MEMORY_MAINTENANCE:
                target_day = event.target_day or _previous_day(business_day)
                return runner.run_memory(
                    business_day=business_day,
                    target_day=target_day,
                    mode=event.mode,
                    source=event.source,
                    scope=self._scope,
                )
            raise LoopContractError(
                f"Unsupported Program maintenance input: {event.kind.value}"
            )

    def _emit_availability(self, business_day: BusinessDay) -> None:
        runner = self._maintenance_runner
        if runner is None:
            return
        try:
            availability = runner.availability(business_day)
        except LoopError as exc:
            raise self._loop_bridge.startup_failure(
                message=str(exc),
                payload={
                    "stage": "maintenance_reminder",
                    "business_day": str(business_day),
                },
            ) from exc
        if not availability.pending:
            return
        self._emit(
            "program.maintenance.available",
            "Maintenance work is available. Use /maintenance home or "
            "/maintenance memory to run it.",
            availability.to_json(),
            level=ObservationLevel.NORMAL,
        )

    def _emit_work(self, outcome: ProgramWorkOutcome) -> None:
        failed = outcome.status is ProgramWorkStatus.FAILED
        self._emit(
            "program.work.failed" if failed else "program.work.completed",
            f"Program work {outcome.kind.value} finished with {outcome.status.value}.",
            outcome.to_json(),
            level=ObservationLevel.NORMAL,
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

    def _emit(
        self,
        name: str,
        message: str,
        payload: JsonObject,
        *,
        level: ObservationLevel = ObservationLevel.VERBOSE,
    ) -> None:
        if not observation_enabled(
            self._observations,
            level,
        ):
            return
        emit_observation(
            self._observations,
            ObservationEvent(
                name=name,
                level=level,
                source="loop.program",
                scope=self._scope,
                message=message,
                payload=payload,
            ),
        )


def _previous_day(day: BusinessDay) -> BusinessDay:
    from datetime import timedelta

    return BusinessDay(day.value - timedelta(days=1))
