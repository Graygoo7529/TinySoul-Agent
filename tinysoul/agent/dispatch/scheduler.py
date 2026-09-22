"""Single root request scheduler shared by SDK and process adapters."""

from __future__ import annotations

from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from tinysoul.infra.concurrency import AsyncMailbox, JoinedOperations
import asyncio
from types import SimpleNamespace
from typing import Generic, Protocol, TypeVar
from uuid import uuid4

from tinysoul.agent.errors import AgentClosedError, AgentQueueFullError, AgentSDKError
from tinysoul.agent.handles import RequestFailure, TurnHandle, TurnResult, TurnState
from tinysoul.kernel.loop.interaction.inbox import InboxLimits, TurnInbox

from tinysoul.infra.json import JsonObject
from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.loop.turn import TurnExecutionCancelled, TurnOutcome
from tinysoul.plugins.archive import DailyTransitionOutcome
from tinysoul.plugins.reflection import (
    ReflectionAvailability,
    ReflectionError,
    ReflectionOutcome,
    ReflectionRequest,
    ReflectionScope,
)
from tinysoul.plugins.reflection.runtime_bridge import ReflectionRuntimeBridge
from tinysoul.plugins.reflection.models import ReflectionExecutionCancelled
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
from ..lifecycle.day import DayLifecycle


class UserTurnExecutor(Protocol):
    """Narrow Program dependency for dispatching one User Turn."""

    async def run(
        self,
        turn_input: str,
        *,
        active_day: CalendarDay,
        scope: RunScope,
        request_id: str,
        input_source: str,
        inbox: TurnInbox | None = None,
    ) -> TurnOutcome: ...


class ReflectionService(Protocol):
    """Reflection facade operations used by Program and Endpoint wiring."""

    def refresh_availability(
        self, transition: DailyTransitionOutcome, *, scope: RunScope
    ) -> ReflectionAvailability: ...

    def availability(self) -> ReflectionAvailability: ...

    async def run(
        self,
        request: ReflectionRequest,
        *,
        active_day: CalendarDay,
        scope: RunScope | None = None,
        inbox: TurnInbox | None = None,
    ) -> ReflectionOutcome: ...


class GenerationDispatchPort(Protocol):
    @property
    def user_turn(self) -> UserTurnExecutor: ...

    @property
    def reflection(self) -> ReflectionService: ...

    @property
    def day(self) -> DayLifecycle: ...


AgentGenerationT = TypeVar("AgentGenerationT", bound=GenerationDispatchPort)


@dataclass(frozen=True)
class AgentRunResult:
    """Bounded results retained from one Program run."""

    turns: tuple[TurnOutcome, ...]
    turn_count: int
    reflection: tuple[ReflectionOutcome, ...] = field(default_factory=tuple)
    reflection_count: int = 0
    transfer: RuntimeTransfer | None = None

    def __post_init__(self) -> None:
        if self.turn_count < len(self.turns) or self.reflection_count < len(
            self.reflection
        ):
            raise AgentSDKError("Program outcome counts cannot underflow retention")
        object.__setattr__(self, "turns", tuple(self.turns))
        object.__setattr__(self, "reflection", tuple(self.reflection))


class RootScheduler(Generic[AgentGenerationT]):
    """Dispatch each app request to a User Turn or ReflectionEngine."""

    def __init__(
        self,
        *,
        user_turn: UserTurnExecutor,
        reflection: ReflectionService,
        day: DayLifecycle,
        bus: SignalBus,
        trap: RuntimeTrap,
        queue_capacity: int = 32,
        retained_outcomes: int = 32,
        reflection_bridge: ReflectionRuntimeBridge | None = None,
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
        self._reflection = reflection
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
        self._reflection_bridge = reflection_bridge or ReflectionRuntimeBridge()
        self._observations = observations or NullObservationEmitter()
        self._request_lock = asyncio.Lock()
        self._prepared_transition: DailyTransitionOutcome | None = None
        self._handles: dict[str, TurnHandle] = {}
        self._completed: deque[str] = deque()
        self._finishing: dict[str, asyncio.Task[None]] = {}
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
        return tuple(
            handle.turn_id
            for handle in self._handles.values()
            if handle.state is TurnState.QUEUED
        )

    def set_capacity(
        self, capacity: int, inbox_limits: InboxLimits = InboxLimits()
    ) -> None:
        if (
            self._handles
            or type(capacity) is not int
            or capacity <= 0
            or not isinstance(inbox_limits, InboxLimits)
        ):
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
        self,
        request: UserTurnRequest | ReflectionRequest,
    ) -> TurnHandle:
        """SDK and process sources share this root queue and dispatcher."""
        return self.submit_batch((request,))[0]

    def submit_batch(
        self,
        requests: tuple[UserTurnRequest | ReflectionRequest, ...],
    ) -> tuple[TurnHandle, ...]:
        """Accept a bounded group atomically, including scheduled Reflection work."""
        if not self._accepting:
            raise AgentClosedError("Root dispatcher is closed")
        pending: dict[str, UserTurnRequest | ReflectionRequest] = {}
        for request in requests:
            self._validate_request(request)
            existing = self._handles.get(request.request_id)
            previous = (
                existing.request
                if existing is not None
                else pending.get(request.request_id)
            )
            if previous is not None and previous != request:
                raise AgentSDKError(
                    "Request identity was reused with different content"
                )
            if existing is None:
                pending[request.request_id] = request
        queued = sum(
            handle.state is TurnState.QUEUED for handle in self._handles.values()
        )
        if queued + len(pending) > self._capacity:
            raise AgentQueueFullError("Agent root queue is full")
        for request in pending.values():
            self._handles[request.request_id] = TurnHandle(
                request, inbox_limits=self._inbox_limits
            )
            self._input_queue.put(request)
        return tuple(self._handles[request.request_id] for request in requests)

    @staticmethod
    def _validate_request(request: UserTurnRequest | ReflectionRequest) -> None:
        if not isinstance(request, (UserTurnRequest, ReflectionRequest)):
            raise AgentSDKError("Agent requires a typed User or Reflection request")
        if (
            isinstance(request, ReflectionRequest)
            and request.scope is ReflectionScope.DAILY
        ):
            raise AgentSDKError(
                "Submit one Home or dated Memory Reflection per SDK Turn"
            )

    def current_day(self) -> CalendarDay:
        day = (
            self._day
            if self._generation_handle is None
            else self._generation_handle.snapshot().generation.day
        )
        return day.current_day()

    def turn_handle(self, turn_id: str) -> TurnHandle | None:
        return self._handles.get(turn_id)

    def stop_accepting(self) -> None:
        self._accepting = False

    async def close_requests(
        self,
        *,
        request_failure: RequestFailure = RequestFailure.CANCELLED,
        error_type: str | None = None,
    ) -> None:
        self._accepting = False
        for handle in tuple(self._handles.values()):
            if not handle.done:
                if request_failure is RequestFailure.CANCELLED:
                    handle.request_cancel()
                self._input_queue.discard(handle.request)
                await self._finish_handle(
                    handle,
                    TurnResult(
                        handle.turn_id,
                        request_failure=request_failure,
                        error_type=error_type,
                    ),
                )

    async def cancel_turn(self, turn_id: str) -> bool:
        handle = self._handles.get(turn_id)
        if handle is None or not handle.request_cancel():
            return False
        if handle.state is TurnState.QUEUED:
            self._input_queue.discard(handle.request)
            await self._finish_handle(
                handle, TurnResult(turn_id, request_failure=RequestFailure.CANCELLED)
            )
        return True

    async def _finish_handle(self, handle: TurnHandle, result: TurnResult) -> None:
        if handle.done:
            return

        async def publish() -> None:
            await handle.finish(result)
            self._completed.append(handle.turn_id)
            while len(self._completed) > self._retained_outcomes:
                del self._handles[self._completed.popleft()]

        task = self._finishing.get(handle.turn_id)
        if task is None:
            handle.inbox.set_activity(TurnState.FINALIZING)
            task = asyncio.create_task(publish())
            self._finishing[handle.turn_id] = task
        operations = JoinedOperations()
        try:
            await operations.run_async(lambda: task)
        finally:
            self._finishing.pop(handle.turn_id, None)
        operations.check_cancelled()

    async def prepare(self) -> DailyTransitionOutcome:
        """Finish startup rollover and availability before services become ready."""

        async with self._request_lock:
            if self._prepared_transition is not None:
                return self._prepared_transition
            transition = await self._preflight()
            self._prepared_transition = transition
            return transition

    async def run(self) -> AgentRunResult:
        turns: deque[TurnOutcome] = deque(maxlen=self._retained_outcomes)
        reflection: deque[ReflectionOutcome] = deque(maxlen=self._retained_outcomes)
        turn_count = 0
        reflection_count = 0
        async with self._request_lock:
            if self._prepared_transition is None:
                await self._preflight()
            self._prepared_transition = None
        self._emit("program.started", "Program started.", {})
        try:
            self._emit_availability(self._reflection_engine().availability())
        except ReflectionError as exc:
            transfer = self._capture_reflection_failure(
                exc,
                stage="availability",
            )
            return self._outcome(
                turns,
                reflection,
                turn_count,
                reflection_count,
                transfer,
            )
        while True:
            request = await self._input_queue.get()
            if isinstance(request, ExitRequest):
                transfer = self._request_agent_end(request)
                return self._outcome(
                    turns,
                    reflection,
                    turn_count,
                    reflection_count,
                    transfer,
                )
            try:
                outcome = await self._dispatch(request)
            except RuntimeTransferInterrupt as interrupt:
                transfer = self._consume_agent_transfer(interrupt.transfer)
                return self._outcome(
                    turns, reflection, turn_count, reflection_count, transfer
                )
            except ReflectionError as exc:
                transfer = self._capture_reflection_failure(
                    exc,
                    stage="root_request",
                    request_id=request.request_id,
                )
                return self._outcome(
                    turns, reflection, turn_count, reflection_count, transfer
                )
            except RuntimeException as exc:
                transfer = self._capture_runtime_failure(exc)
                return self._outcome(
                    turns, reflection, turn_count, reflection_count, transfer
                )
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
                    return self._outcome(
                        turns, reflection, turn_count, reflection_count, transfer
                    )
            else:
                if not isinstance(outcome, ReflectionOutcome):
                    raise AgentSDKError("Reflection work returned an invalid outcome")
                reflection.append(outcome)
                reflection_count += 1

    async def _dispatch(
        self,
        request: UserTurnRequest | ReflectionRequest,
    ) -> TurnOutcome | ReflectionOutcome | None:
        handle = self._handles.get(request.request_id)
        if handle is not None and handle.cancel_requested:
            await self._finish_handle(
                handle,
                TurnResult(handle.turn_id, request_failure=RequestFailure.CANCELLED),
            )
            return None

        async def execute() -> TurnOutcome | ReflectionOutcome:
            async with self._request_lock:
                if isinstance(request, UserTurnRequest):
                    async with self._generation_activity(RuntimeActivity.USER_TURN):
                        transition = await self._prepare_day()
                        return await self._run_user_request(
                            request, transition=transition
                        )
                return await self._run_reflection(request)

        task = asyncio.create_task(
            execute(), name=f"tinysoul-root:{request.request_id}"
        )
        if handle is not None:
            handle.bind(task)
            self._active = handle
        result: TurnResult | None = None
        try:
            outcome = await task
            result = TurnResult(request.request_id, outcome=outcome)
            return outcome
        except asyncio.CancelledError as exc:
            cancelled_outcome = (
                exc.outcome
                if isinstance(
                    exc, (TurnExecutionCancelled, ReflectionExecutionCancelled)
                )
                else None
            )
            result = TurnResult(
                request.request_id,
                outcome=cancelled_outcome,
                request_failure=(
                    RequestFailure.CANCELLED if cancelled_outcome is None else None
                ),
            )
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise
            return cancelled_outcome
        except Exception as exc:
            result = TurnResult(
                request.request_id,
                request_failure=RequestFailure.FAILED,
                error_type=type(exc).__name__,
            )
            raise
        finally:
            self._active = None
            if handle is not None and result is not None:
                await self._finish_handle(handle, result)

    async def _preflight(self) -> DailyTransitionOutcome:
        try:
            async with self._generation_activity(RuntimeActivity.DAILY_TRANSITION):
                return await self._prepare_day()
        except ReflectionError as exc:
            raise self._reflection_bridge.startup_failure(
                message="Daily transition could not be completed.",
                payload={"stage": "daily_rollover", "error_type": type(exc).__name__},
            ) from exc

    async def _prepare_day(self) -> DailyTransitionOutcome:
        async with self._generation_lease() as generation:
            transition = await generation.day.preflight(scope=self._scope)
            operation = JoinedOperations()
            await operation.run(
                lambda: generation.reflection.refresh_availability(
                    transition, scope=self._scope
                )
            )
            operation.check_cancelled()
            return transition

    async def _run_user_request(
        self,
        request: UserTurnRequest,
        *,
        transition: DailyTransitionOutcome,
    ) -> TurnOutcome:
        async with self._generation_lease() as generation:
            async with generation.day.active_day_lease() as leased_day:
                if leased_day != transition.active_day:
                    raise AgentSDKError("Active Business Day changed before User Turn")
                handle = self._handles.get(request.request_id)
                if handle is not None:
                    return await generation.user_turn.run(
                        request.text,
                        active_day=leased_day,
                        scope=self._scope,
                        request_id=request.request_id,
                        input_source=request.source,
                        inbox=handle.inbox,
                    )
                return await generation.user_turn.run(
                    request.text,
                    active_day=leased_day,
                    scope=self._scope,
                    request_id=request.request_id,
                    input_source=request.source,
                )

    async def _run_reflection(self, request: ReflectionRequest) -> ReflectionOutcome:
        async with self._generation_activity(
            RuntimeActivity.REFLECTION_TURN
        ) as generation:
            transition = await self._prepare_day()
            handle = self._handles.get(request.request_id)
            async with generation.day.active_day_lease() as day:
                if day != transition.active_day:
                    raise AgentSDKError("Active day changed before Reflection")
                return await generation.reflection.run(
                    request,
                    active_day=day,
                    scope=self._scope,
                    inbox=handle.inbox if handle is not None else None,
                )

    @asynccontextmanager
    async def _generation_lease(self):
        if self._generation_handle is None:
            yield SimpleNamespace(
                user_turn=self._user_turn,
                reflection=self._reflection,
                day=self._day,
            )
            return
        async with self._generation_handle.read() as generation:
            yield generation

    def _reflection_engine(self) -> ReflectionService:
        if self._generation_handle is None:
            return self._reflection
        return self._generation_handle.snapshot().generation.reflection

    @asynccontextmanager
    async def _generation_activity(self, activity: RuntimeActivity):
        if self._generation_handle is None:
            yield SimpleNamespace(
                user_turn=self._user_turn,
                reflection=self._reflection,
                day=self._day,
            )
            return
        async with self._generation_handle.activity_lease(activity):
            async with self._generation_handle.read() as generation:
                yield generation

    def _capture_reflection_failure(
        self,
        error: ReflectionError,
        *,
        stage: str,
        request_id: str = "",
    ) -> RuntimeTransfer:
        runtime_error = self._reflection_bridge.from_reflection_error(
            error,
            payload={
                "stage": stage,
                **({"request_id": request_id} if request_id else {}),
            },
        )
        return self._capture_runtime_failure(runtime_error)

    def _capture_runtime_failure(
        self, runtime_error: RuntimeException
    ) -> RuntimeTransfer:
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
            "program.reflection.available",
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
        reflection: deque[ReflectionOutcome],
        turn_count: int,
        reflection_count: int,
        transfer: RuntimeTransfer,
    ) -> AgentRunResult:
        self._emit(
            "program.completed",
            "Program completed.",
            {
                "turn_count": turn_count,
                "reflection_count": reflection_count,
            },
        )
        return AgentRunResult(
            turns=tuple(turns),
            turn_count=turn_count,
            reflection=tuple(reflection),
            reflection_count=reflection_count,
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
                source="agent.program",
                scope=self._scope,
                message=message,
                payload=payload,
            ),
        )
