"""Single root request scheduler shared by SDK and process adapters."""

from __future__ import annotations

from collections import deque
from contextlib import AbstractContextManager
from contextlib import contextmanager
from dataclasses import dataclass, field
from tinysoul.infra.concurrency import AsyncMailbox, JoinedOperations
import asyncio
from types import SimpleNamespace
from typing import Generic, Protocol, TypeVar
from uuid import uuid4

from tinysoul.agent.errors import AgentClosedError, AgentQueueFullError, AgentSDKError
from tinysoul.agent.handles import TurnHandle, TurnResult, TurnState
from tinysoul.kernel.loop.inbox import InboxLimits, TurnInbox

from tinysoul.infra.json import JsonObject
from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.loop.turn import TurnExecutionCancelled, TurnOutcome
from tinysoul.plugins.archive import DailyTransitionOutcome
from tinysoul.plugins.reflection import (ReflectionAvailability, ReflectionError, ReflectionOutcome, ReflectionRequest, ReflectionScope)
from tinysoul.plugins.reflection.runtime_bridge import ReflectionRuntimeBridge
from tinysoul.runtime import (
    NullObservationEmitter,
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    RUNTIME_AGENT_END,
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

from tinysoul.agent.requests import AgentRequest, ExitRequest, UserTurnRequest
from .day import DayLifecycle


class UserTurnExecutor(Protocol):
    """Narrow Program dependency for dispatching one User Turn."""

    async def run(
        self,
        turn_input: str,
        *,
        business_day: CalendarDay,
        scope: RunScope,
        request_id: str,
        input_source: str,
        inbox: TurnInbox | None = None,
    ) -> TurnOutcome: ...


class ReflectionService(Protocol):
    """Reflection facade operations used by Program and Endpoint wiring."""

    def refresh_availability(self, transition: DailyTransitionOutcome, *, scope: RunScope) -> ReflectionAvailability: ...

    def availability(self) -> ReflectionAvailability: ...

    async def run(
        self,
        request: ReflectionRequest,
        *,
        business_day: CalendarDay,
        scope: RunScope | None = None,
        inbox: TurnInbox | None = None,
    ) -> ReflectionOutcome: ...


class AgentGeneration(Protocol):
    @property
    def user_turn(self) -> UserTurnExecutor: ...

    @property
    def maintenance(self) -> ReflectionService: ...

    @property
    def day(self) -> DayLifecycle: ...


AgentGenerationT = TypeVar("AgentGenerationT", bound=AgentGeneration)


@dataclass(frozen=True)
class AgentRunResult:
    """Bounded results retained from one Program run."""

    turns: tuple[TurnOutcome, ...]
    turn_count: int
    maintenance: tuple[ReflectionOutcome, ...] = field(default_factory=tuple)
    maintenance_count: int = 0
    transfer: RuntimeTransfer | None = None

    def __post_init__(self) -> None:
        if self.turn_count < len(self.turns) or self.maintenance_count < len(
            self.maintenance
        ):
            raise AgentSDKError("Program outcome counts cannot underflow retention")
        object.__setattr__(self, "turns", tuple(self.turns))
        object.__setattr__(self, "maintenance", tuple(self.maintenance))


class RootScheduler(Generic[AgentGenerationT]):
    """Dispatch each app request to a User Turn or ReflectionEngine."""

    def __init__(
        self,
        *,
        user_turn: UserTurnExecutor,
        maintenance: ReflectionService,
        day: DayLifecycle,
        bus: SignalBus,
        trap: RuntimeTrap,
        queue_capacity: int = 32,
        retained_outcomes: int = 32,
        maintenance_bridge: ReflectionRuntimeBridge | None = None,
        observations: ObservationEmitter | None = None,
        generation_handle: RuntimeHandle[AgentGenerationT] | None = None,
    ) -> None:
        if (
            isinstance(retained_outcomes, bool)
            or not isinstance(retained_outcomes, int)
            or retained_outcomes <= 0
        ):
            raise AgentSDKError("retained_outcomes must be positive")
        self._user_turn = user_turn
        self._maintenance = maintenance
        self._day = day
        self._generation_handle = generation_handle
        self._bus = bus
        self._trap = trap
        if type(queue_capacity) is not int or queue_capacity <= 0:
            raise AgentSDKError("queue_capacity must be a positive integer")
        self._capacity = queue_capacity
        self._inbox_limits = InboxLimits()
        self._input_queue: AsyncMailbox[AgentRequest] = AsyncMailbox()
        self._scope = RunScope().push(RunLevel.AGENT, "program")
        self._retained_outcomes = retained_outcomes
        self._maintenance_bridge = maintenance_bridge or ReflectionRuntimeBridge()
        self._observations = observations or NullObservationEmitter()
        self._request_lock = asyncio.Lock()
        self._prepared_transition: DailyTransitionOutcome | None = None
        self._handles: dict[str, TurnHandle] = {}
        self._accepting = True
        self._active: TurnHandle | None = None
        self._exit_request: ExitRequest | None = None

    @property
    def scope(self) -> RunScope:
        return self._scope

    @property
    def active_turn(self) -> TurnHandle | None:
        return self._active

    @property
    def queued_turn_ids(self) -> tuple[str, ...]:
        return tuple(handle.turn_id for handle in self._handles.values() if handle.state is TurnState.QUEUED)

    def set_capacity(self, capacity: int, inbox_limits: InboxLimits = InboxLimits()) -> None:
        if self._handles or type(capacity) is not int or capacity <= 0 or not isinstance(inbox_limits, InboxLimits):
            raise AgentSDKError("Queue capacity must be set before accepting requests")
        self._capacity = capacity
        self._inbox_limits = inbox_limits

    def request_exit(self, request: ExitRequest) -> None:
        if self._exit_request is not None:
            return
        if not self._accepting:
            raise AgentClosedError("Root dispatcher is closed")
        self._exit_request = request
        self._accepting = False
        for handle in self._handles.values():
            handle.request_cancel()
        self._input_queue.put(request)

    def submit_turn(
        self, request: UserTurnRequest | ReflectionRequest,
    ) -> TurnHandle:
        """SDK and process sources share this root queue and dispatcher."""
        return self.submit_batch((request,))[0]

    def submit_batch(
        self, requests: tuple[UserTurnRequest | ReflectionRequest, ...],
    ) -> tuple[TurnHandle, ...]:
        """Accept a bounded group atomically, including scheduled Reflection work."""
        if not self._accepting:
            raise AgentClosedError("Root dispatcher is closed")
        pending: dict[str, UserTurnRequest | ReflectionRequest] = {}
        for request in requests:
            self._validate_request(request)
            existing = self._handles.get(request.request_id)
            previous = existing.request if existing is not None else pending.get(request.request_id)
            if previous is not None and previous != request:
                raise AgentSDKError("Request identity was reused with different content")
            if existing is None:
                pending[request.request_id] = request
        queued = sum(handle.state is TurnState.QUEUED for handle in self._handles.values())
        if queued + len(pending) > self._capacity:
            raise AgentQueueFullError("Agent root queue is full")
        for request in pending.values():
            self._handles[request.request_id] = TurnHandle(request, inbox_limits=self._inbox_limits)
            self._input_queue.put(request)
        return tuple(self._handles[request.request_id] for request in requests)

    @staticmethod
    def _validate_request(request: UserTurnRequest | ReflectionRequest) -> None:
        if not isinstance(request, (UserTurnRequest, ReflectionRequest)):
            raise AgentSDKError("Agent requires a typed User or Reflection request")
        if isinstance(request, ReflectionRequest) and request.scope is ReflectionScope.DAILY:
            raise AgentSDKError("Submit one Home or dated Memory Reflection per SDK Turn")

    def current_day(self) -> CalendarDay:
        with self._generation_lease() as generation:
            return generation.day.current_day()

    def turn_handle(self, turn_id: str) -> TurnHandle | None:
        return self._handles.get(turn_id)

    async def close_requests(self) -> None:
        self._accepting = False
        for handle in tuple(self._handles.values()):
            if not handle.done:
                handle.request_cancel()
                await handle.finish(TurnResult(handle.turn_id, TurnState.CANCELLED))

    async def prepare(self) -> DailyTransitionOutcome:
        """Finish startup rollover and availability before services become ready."""

        async with self._request_lock:
            if self._prepared_transition is not None:
                return self._prepared_transition
            transition = await self._preflight()
            self._prepared_transition = transition
            return transition

    async def run_once(
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
        async with self._request_lock:
            with self._generation_activity(RuntimeActivity.USER_TURN):
                transition = await self._prepare_day()
                return (await self._run_user_request(request, transition=transition))

    async def run(self) -> AgentRunResult:
        turns: deque[TurnOutcome] = deque(maxlen=self._retained_outcomes)
        maintenance: deque[ReflectionOutcome] = deque(
            maxlen=self._retained_outcomes
        )
        turn_count = 0
        maintenance_count = 0
        async with self._request_lock:
            if self._prepared_transition is None:
                await self._preflight()
            self._prepared_transition = None
        self._emit("program.started", "Program started.", {})
        try:
            self._emit_availability(self._maintenance_engine().availability())
        except ReflectionError as exc:
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
            request = await self._input_queue.get()
            if isinstance(request, ExitRequest):
                transfer = self._request_agent_end(request)
                return self._outcome(
                    turns,
                    maintenance,
                    turn_count,
                    maintenance_count,
                    transfer,
                )
            try:
                outcome = await self._dispatch(request)
            except RuntimeTransferInterrupt as interrupt:
                transfer = self._consume_agent_transfer(interrupt.transfer)
                return self._outcome(turns, maintenance, turn_count, maintenance_count, transfer)
            except ReflectionError as exc:
                transfer = self._capture_maintenance_failure(
                    exc, stage="root_request", request_id=request.request_id,
                )
                return self._outcome(turns, maintenance, turn_count, maintenance_count, transfer)
            except RuntimeException as exc:
                transfer = self._capture_runtime_failure(exc)
                return self._outcome(turns, maintenance, turn_count, maintenance_count, transfer)
            if outcome is None:
                continue
            if isinstance(request, UserTurnRequest):
                if not isinstance(outcome, TurnOutcome):
                    raise AgentSDKError("User work returned an invalid outcome")
                turns.append(outcome)
                turn_count += 1
                transfer = outcome.transfer
                if transfer is not None and transfer.target.level is not RunLevel.TURN:
                    transfer = self._consume_agent_transfer(transfer)
                    return self._outcome(turns, maintenance, turn_count, maintenance_count, transfer)
            else:
                if not isinstance(outcome, ReflectionOutcome):
                    raise AgentSDKError("Reflection work returned an invalid outcome")
                maintenance.append(outcome)
                maintenance_count += 1

    async def _dispatch(
        self, request: UserTurnRequest | ReflectionRequest,
    ) -> TurnOutcome | ReflectionOutcome | None:
        handle = self._handles.get(request.request_id)
        if handle is not None and handle.cancel_requested:
            await handle.finish(TurnResult(handle.turn_id, TurnState.CANCELLED))
            return None

        async def execute() -> TurnOutcome | ReflectionOutcome:
            async with self._request_lock:
                if isinstance(request, UserTurnRequest):
                    with self._generation_activity(RuntimeActivity.USER_TURN):
                        transition = await self._prepare_day()
                        return await self._run_user_request(request, transition=transition)
                return await self._run_maintenance(request)

        task = asyncio.create_task(execute(), name=f"tinysoul-root:{request.request_id}")
        if handle is not None:
            handle.bind(task)
            self._active = handle
        result: TurnResult | None = None
        try:
            outcome = await task
            state = TurnState.FAILED if outcome.status.value in {"failed", "partial"} else TurnState.FINISHED
            result = TurnResult(request.request_id, state, outcome=outcome)
            return outcome
        except asyncio.CancelledError as exc:
            cancelled_outcome = exc.outcome if isinstance(exc, TurnExecutionCancelled) else None
            state = (TurnState.FAILED if cancelled_outcome is not None
                     and cancelled_outcome.status.value == "failed" else TurnState.CANCELLED)
            result = TurnResult(request.request_id, state, outcome=cancelled_outcome)
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise
            return None
        except Exception as exc:
            result = TurnResult(request.request_id, TurnState.FAILED, error_type=type(exc).__name__)
            raise
        finally:
            self._active = None
            if handle is not None and result is not None:
                closing_cancellation: asyncio.CancelledError | None = None
                closer = asyncio.create_task(handle.finish(result))
                while not closer.done():
                    try:
                        await asyncio.shield(closer)
                    except asyncio.CancelledError as exc:
                        closing_cancellation = exc
                closer.result()
                completed = [key for key, item in self._handles.items() if item.done]
                for key in completed[:-self._retained_outcomes]:
                    del self._handles[key]
                if closing_cancellation is not None:
                    raise closing_cancellation

    async def _preflight(self) -> DailyTransitionOutcome:
        try:
            with self._generation_activity(RuntimeActivity.DAILY_TRANSITION):
                return await self._prepare_day()
        except ReflectionError as exc:
            raise self._maintenance_bridge.startup_failure(
                message="Daily transition could not be completed.",
                payload={"stage": "daily_rollover", "error_type": type(exc).__name__},
            ) from exc

    async def _prepare_day(self) -> DailyTransitionOutcome:
        with self._generation_lease() as generation:
            def prepare() -> DailyTransitionOutcome:
                transition = generation.day.preflight(scope=self._scope)
                generation.maintenance.refresh_availability(transition, scope=self._scope)
                return transition

            operation = JoinedOperations()
            transition = await operation.run(prepare)
            operation.check_cancelled()
            return transition

    async def _run_user_request(
        self,
        request: UserTurnRequest,
        *,
        transition: DailyTransitionOutcome,
    ) -> TurnOutcome:
        with self._generation_lease() as generation:
            with generation.day.active_day_lease() as leased_day:
                if leased_day != transition.active_day:
                    raise AgentSDKError("Active Business Day changed before User Turn")
                handle = self._handles.get(request.request_id)
                if handle is not None:
                    return await generation.user_turn.run(
                        request.text,
                        business_day=leased_day,
                        scope=self._scope,
                        request_id=request.request_id,
                        input_source=request.source,
                        inbox=handle.inbox,
                    )
                return (await generation.user_turn.run(
                    request.text,
                    business_day=leased_day,
                    scope=self._scope,
                    request_id=request.request_id,
                    input_source=request.source,
                ))

    async def _run_maintenance(self, request: ReflectionRequest) -> ReflectionOutcome:
        with self._generation_activity(RuntimeActivity.MAINTENANCE_TURN) as generation:
            transition = await self._prepare_day()
            handle = self._handles.get(request.request_id)
            with generation.day.active_day_lease() as day:
                if day != transition.active_day:
                    raise AgentSDKError("Active day changed before Reflection")
                return await generation.maintenance.run(
                    request, business_day=day, scope=self._scope,
                    inbox=handle.inbox if handle is not None else None,
                )

    @contextmanager
    def _generation_lease(self):
        if self._generation_handle is None:
            yield SimpleNamespace(
                user_turn=self._user_turn,
                maintenance=self._maintenance,
                day=self._day,
            )
            return
        with self._generation_handle.read() as generation:
            yield generation

    def _maintenance_engine(self) -> ReflectionService:
        if self._generation_handle is None:
            return self._maintenance
        return self._generation_handle.snapshot().generation.maintenance

    @contextmanager
    def _generation_activity(self, activity: RuntimeActivity):
        if self._generation_handle is None:
            yield SimpleNamespace(
                user_turn=self._user_turn,
                maintenance=self._maintenance,
                day=self._day,
            )
            return
        with self._generation_handle.activity_lease(activity):
            with self._generation_handle.read() as generation:
                yield generation

    def _capture_maintenance_failure(
        self,
        error: ReflectionError,
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
        return self._capture_runtime_failure(runtime_error)

    def _capture_runtime_failure(self, runtime_error: RuntimeException) -> RuntimeTransfer:
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
        return self._consume_agent_transfer(result.transfer)

    def _consume_agent_transfer(
        self,
        transfer: RuntimeTransfer,
    ) -> RuntimeTransfer:
        agent_frame = self._scope.current()
        if transfer.target != agent_frame:
            raise RuntimeInvariantError(
                f"Program received a transfer for another frame: {transfer}"
            )
        if transfer.action is not RuntimeTransferAction.END:
            raise RuntimeInvariantError(
                f"Program frame is not replayable and cannot consume: {transfer}"
            )
        return transfer

    def _emit_availability(self, availability: ReflectionAvailability) -> None:
        if not availability.pending:
            return
        self._emit(
            "program.maintenance.available",
            "Reflection work is available.",
            availability.to_json(),
            level=ObservationLevel.NORMAL,
        )

    def _request_agent_end(self, request: ExitRequest) -> RuntimeTransfer:
        result = self._trap.capture(
            RuntimeException(
                reason=RUNTIME_AGENT_END,
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
        maintenance: deque[ReflectionOutcome],
        turn_count: int,
        maintenance_count: int,
        transfer: RuntimeTransfer,
    ) -> AgentRunResult:
        self._emit(
            "program.completed",
            "Program completed.",
            {
                "turn_count": turn_count,
                "maintenance_count": maintenance_count,
            },
        )
        return AgentRunResult(
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
