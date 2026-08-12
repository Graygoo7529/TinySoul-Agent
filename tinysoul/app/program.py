"""Typed top-level request queue and Program dispatcher."""

from __future__ import annotations

from collections import deque
from contextlib import AbstractContextManager
from contextlib import contextmanager
from dataclasses import dataclass, field
from queue import Empty, Queue
from threading import RLock
from types import SimpleNamespace
from typing import Generic, Protocol, TypeVar
from uuid import uuid4

from tinysoul.infra.json import JsonObject
from tinysoul.infra.time import BusinessDay
from tinysoul.loop.turn import TurnOutcome
from tinysoul.maintenance import (
    DailyTransitionOutcome,
    MaintenanceAvailability,
    MaintenanceError,
    MaintenanceOutcome,
    MaintenanceRequest,
)
from tinysoul.maintenance.runtime_bridge import MaintenanceRuntimeBridge
from tinysoul.runtime import (
    NullObservationEmitter,
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    RUNTIME_PROGRAM_END,
    RunLevel,
    RunScope,
    RuntimeException,
    RuntimeInvariantError,
    RuntimeTrap,
    RuntimeTransfer,
    RuntimeTransferAction,
    RuntimeTransferInterrupt,
    RuntimeActivity,
    RuntimeHandle,
    SignalBus,
    emit_observation,
    observation_enabled,
)

from .errors import AppContractError
from .requests import AppRequest, ExitRequest, UserTurnRequest


class UserTurnExecutor(Protocol):
    """Narrow Program dependency for dispatching one User Turn."""

    def run(
        self,
        turn_input: str,
        *,
        business_day: BusinessDay,
        scope: RunScope,
        request_id: str,
        input_source: str,
    ) -> TurnOutcome: ...


class ProgramMaintenanceEngine(Protocol):
    """Maintenance facade operations used by Program and Endpoint wiring."""

    def active_day_lease(self) -> AbstractContextManager[BusinessDay]: ...

    def preflight(self, *, scope: RunScope | None = None) -> DailyTransitionOutcome: ...

    def availability(self) -> MaintenanceAvailability: ...

    def run(
        self,
        request: MaintenanceRequest,
        *,
        scope: RunScope | None = None,
    ) -> MaintenanceOutcome: ...


class ProgramGeneration(Protocol):
    @property
    def user_turn(self) -> UserTurnExecutor: ...

    @property
    def maintenance(self) -> ProgramMaintenanceEngine: ...


ProgramGenerationT = TypeVar("ProgramGenerationT", bound=ProgramGeneration)


@dataclass(frozen=True)
class ProgramOutcome:
    """Bounded results retained from one Program run."""

    turns: tuple[TurnOutcome, ...]
    turn_count: int
    maintenance: tuple[MaintenanceOutcome, ...] = field(default_factory=tuple)
    maintenance_count: int = 0
    transfer: RuntimeTransfer | None = None

    def __post_init__(self) -> None:
        if self.turn_count < len(self.turns) or self.maintenance_count < len(
            self.maintenance
        ):
            raise AppContractError("Program outcome counts cannot underflow retention")
        object.__setattr__(self, "turns", tuple(self.turns))
        object.__setattr__(self, "maintenance", tuple(self.maintenance))


class ProgramRunner(Generic[ProgramGenerationT]):
    """Dispatch each app request to a User Turn or MaintenanceEngine."""

    def __init__(
        self,
        *,
        user_turn: UserTurnExecutor,
        maintenance: ProgramMaintenanceEngine,
        bus: SignalBus,
        trap: RuntimeTrap,
        input_queue: Queue[AppRequest] | None = None,
        retained_outcomes: int = 32,
        maintenance_bridge: MaintenanceRuntimeBridge | None = None,
        observations: ObservationEmitter | None = None,
        generation_handle: RuntimeHandle[ProgramGenerationT] | None = None,
    ) -> None:
        if (
            isinstance(retained_outcomes, bool)
            or not isinstance(retained_outcomes, int)
            or retained_outcomes <= 0
        ):
            raise AppContractError("retained_outcomes must be positive")
        self._user_turn = user_turn
        self._maintenance = maintenance
        self._generation_handle = generation_handle
        self._bus = bus
        self._trap = trap
        self._input_queue: Queue[AppRequest] = input_queue or Queue()
        self._scope = RunScope().push(RunLevel.PROGRAM, "program")
        self._retained_outcomes = retained_outcomes
        self._maintenance_bridge = maintenance_bridge or MaintenanceRuntimeBridge()
        self._observations = observations or NullObservationEmitter()
        self._request_lock = RLock()
        self._prepared_transition: DailyTransitionOutcome | None = None

    @property
    def scope(self) -> RunScope:
        return self._scope

    @property
    def input_queue(self) -> Queue[AppRequest]:
        return self._input_queue

    def submit_request(self, request: AppRequest) -> None:
        if not isinstance(request, (UserTurnRequest, MaintenanceRequest, ExitRequest)):
            raise AppContractError("Program received an invalid request")
        self._input_queue.put(request)

    def prepare(self) -> DailyTransitionOutcome:
        """Finish startup rollover and availability before services become ready."""

        with self._request_lock:
            transition = self._preflight()
            self._prepared_transition = transition
            return transition

    def run_once(
        self,
        user_input: str,
        *,
        request_id: str = "",
        source: str = "",
    ) -> TurnOutcome:
        request = UserTurnRequest(
            user_input,
            source=source,
            request_id=request_id or f"request_{uuid4().hex}",
        )
        with self._request_lock:
            with self._generation_activity(RuntimeActivity.USER_TURN):
                transition = self._maintenance_engine().preflight(scope=self._scope)
                return self._run_user_request(request, transition=transition)

    def run(self) -> ProgramOutcome:
        turns: deque[TurnOutcome] = deque(maxlen=self._retained_outcomes)
        maintenance: deque[MaintenanceOutcome] = deque(
            maxlen=self._retained_outcomes
        )
        turn_count = 0
        maintenance_count = 0
        with self._request_lock:
            if self._prepared_transition is None:
                self._preflight()
            self._prepared_transition = None
        self._emit("program.started", "Program started.", {})
        try:
            self._emit_availability(self._maintenance_engine().availability())
        except MaintenanceError as exc:
            transfer = self._capture_maintenance_failure(
                exc,
                stage="availability",
            )
            return self._outcome(
                turns,
                maintenance,
                turn_count,
                maintenance_count,
                transfer,
            )
        while True:
            request = self._next_request()
            if isinstance(request, ExitRequest):
                transfer = self._request_program_end(request)
                return self._outcome(
                    turns,
                    maintenance,
                    turn_count,
                    maintenance_count,
                    transfer,
                )
            if isinstance(request, UserTurnRequest):
                try:
                    with self._request_lock:
                        with self._generation_activity(RuntimeActivity.USER_TURN):
                            transition = self._maintenance_engine().preflight(
                                scope=self._scope
                            )
                            outcome = self._run_user_request(
                                request,
                                transition=transition,
                            )
                except MaintenanceError as exc:
                    transfer = self._capture_maintenance_failure(
                        exc,
                        stage="user_preflight",
                        request_id=request.request_id,
                    )
                    return self._outcome(
                        turns,
                        maintenance,
                        turn_count,
                        maintenance_count,
                        transfer,
                    )
                turns.append(outcome)
                turn_count += 1
                transfer = outcome.transfer
                if transfer is not None and transfer.target.level is not RunLevel.TURN:
                    transfer = self._consume_program_transfer(transfer)
                    return self._outcome(
                        turns,
                        maintenance,
                        turn_count,
                        maintenance_count,
                        transfer,
                    )
                continue
            if isinstance(request, MaintenanceRequest):
                try:
                    with self._request_lock:
                        outcome = self._run_maintenance(request)
                except RuntimeTransferInterrupt as interrupt:
                    transfer = self._consume_program_transfer(interrupt.transfer)
                    return self._outcome(
                        turns,
                        maintenance,
                        turn_count,
                        maintenance_count,
                        transfer,
                    )
                except MaintenanceError as exc:
                    transfer = self._capture_maintenance_failure(
                        exc,
                        stage="maintenance_request",
                        request_id=request.request_id,
                    )
                    return self._outcome(
                        turns,
                        maintenance,
                        turn_count,
                        maintenance_count,
                        transfer,
                    )
                maintenance.append(outcome)
                maintenance_count += 1
                continue
            raise AppContractError("Program queue contained an unknown request")

    def _next_request(self) -> AppRequest:
        """Wait for the next request in slices so signal handlers can run.

        An unbounded ``Queue.get()`` on Windows blocks in a native wait
        that never yields to the interpreter, so a Ctrl-C handler would
        not run until the next request arrives. Sliced waits keep the
        main thread responsive to SIGINT while idle.
        """

        while True:
            try:
                return self._input_queue.get(timeout=0.5)
            except Empty:
                continue

    def _preflight(self) -> DailyTransitionOutcome:
        try:
            with self._generation_activity(RuntimeActivity.DAILY_TRANSITION) as generation:
                return generation.maintenance.preflight(scope=self._scope)
        except MaintenanceError as exc:
            raise self._maintenance_bridge.startup_failure(
                message=str(exc),
                payload={"stage": "daily_rollover"},
            ) from exc

    def _run_user_request(
        self,
        request: UserTurnRequest,
        *,
        transition: DailyTransitionOutcome,
    ) -> TurnOutcome:
        with self._generation_lease() as generation:
            with generation.maintenance.active_day_lease() as leased_day:
                if leased_day != transition.active_day:
                    raise AppContractError("Active Business Day changed before User Turn")
                return generation.user_turn.run(
                    request.text,
                    business_day=leased_day,
                    scope=self._scope,
                    request_id=request.request_id,
                    input_source=request.source,
                )

    def _run_maintenance(self, request: MaintenanceRequest) -> MaintenanceOutcome:
        with self._generation_activity(RuntimeActivity.MAINTENANCE_TURN) as generation:
            return generation.maintenance.run(request, scope=self._scope)

    @contextmanager
    def _generation_lease(self):
        if self._generation_handle is None:
            yield SimpleNamespace(
                user_turn=self._user_turn,
                maintenance=self._maintenance,
            )
            return
        with self._generation_handle.read() as generation:
            yield generation

    def _maintenance_engine(self) -> ProgramMaintenanceEngine:
        if self._generation_handle is None:
            return self._maintenance
        return self._generation_handle.snapshot().generation.maintenance

    @contextmanager
    def _generation_activity(self, activity: RuntimeActivity):
        if self._generation_handle is None:
            yield SimpleNamespace(
                user_turn=self._user_turn,
                maintenance=self._maintenance,
            )
            return
        with self._generation_handle.activity_lease(activity):
            with self._generation_handle.read() as generation:
                yield generation

    def _capture_maintenance_failure(
        self,
        error: MaintenanceError,
        *,
        stage: str,
        request_id: str = "",
    ) -> RuntimeTransfer:
        runtime_error = self._maintenance_bridge.from_maintenance_error(
            error,
            payload={
                "stage": stage,
                **({"request_id": request_id} if request_id else {}),
            },
        )
        result = self._trap.capture(runtime_error, self._scope)
        for signal in result.signals:
            self._bus.emit(signal)
        self._emit(
            "runtime.trap",
            runtime_error.message,
            {
                "reason": runtime_error.reason,
                "transfer_action": result.transfer.action.value,
                "transfer_target": str(result.transfer.target),
            },
        )
        return self._consume_program_transfer(result.transfer)

    def _consume_program_transfer(
        self,
        transfer: RuntimeTransfer,
    ) -> RuntimeTransfer:
        program_frame = self._scope.current()
        if transfer.target != program_frame:
            raise RuntimeInvariantError(
                f"Program received a transfer for another frame: {transfer}"
            )
        if transfer.action is not RuntimeTransferAction.END:
            raise RuntimeInvariantError(
                f"Program frame is not replayable and cannot consume: {transfer}"
            )
        return transfer

    def _emit_availability(self, availability: MaintenanceAvailability) -> None:
        if not availability.pending:
            return
        self._emit(
            "program.maintenance.available",
            "Maintenance work is available.",
            availability.to_json(),
            level=ObservationLevel.NORMAL,
        )

    def _request_program_end(self, request: ExitRequest) -> RuntimeTransfer:
        result = self._trap.capture(
            RuntimeException(
                reason=RUNTIME_PROGRAM_END,
                message="Program exit requested.",
                payload={
                    "input": request.text,
                    "source": request.source,
                    "metadata": request.metadata,
                    "request_id": request.request_id,
                },
            ),
            self._scope,
        )
        for signal in result.signals:
            self._bus.emit(signal)
        return result.transfer

    def _outcome(
        self,
        turns: deque[TurnOutcome],
        maintenance: deque[MaintenanceOutcome],
        turn_count: int,
        maintenance_count: int,
        transfer: RuntimeTransfer,
    ) -> ProgramOutcome:
        self._emit(
            "program.completed",
            "Program completed.",
            {
                "turn_count": turn_count,
                "maintenance_count": maintenance_count,
            },
        )
        return ProgramOutcome(
            turns=tuple(turns),
            turn_count=turn_count,
            maintenance=tuple(maintenance),
            maintenance_count=maintenance_count,
            transfer=transfer,
        )

    def _emit(
        self,
        name: str,
        message: str,
        payload: JsonObject,
        *,
        level: ObservationLevel = ObservationLevel.VERBOSE,
    ) -> None:
        if not observation_enabled(self._observations, level):
            return
        emit_observation(
            self._observations,
            ObservationEvent(
                name=name,
                level=level,
                source="app.program",
                scope=self._scope,
                message=message,
                payload=payload,
            ),
        )
