"""Accepted root work and its authoritative completion handle."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from tinysoul.kernel.loop.inbox import BudgetRequest, InboxKind, InboxLimits, InboxRecord, QuestionRequest, TurnInbox, TurnState, WaitReason
from tinysoul.kernel.loop.outcomes import TurnOutcomeStatus
from tinysoul.runtime.events import EnvironmentEvent
from tinysoul.kernel.loop.turn import TurnOutcome
from tinysoul.plugins.reflection.models import ReflectionOutcome, ReflectionRequest, ReflectionStatus

from .errors import AgentClosedError, AgentSDKError
from .requests import UserTurnRequest


class RequestFailure(StrEnum):
    """Rejected execution before an owner could produce a Turn outcome."""

    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True)
class TurnResult:
    turn_id: str
    outcome: TurnOutcome | ReflectionOutcome | None = None
    request_failure: RequestFailure | None = None
    error_type: str | None = None

    def __post_init__(self) -> None:
        if not self.turn_id or (self.outcome is None) == (self.request_failure is None):
            raise AgentSDKError("Result requires exactly one owner outcome or request failure")
        if self.outcome is not None and not isinstance(self.outcome, (TurnOutcome, ReflectionOutcome)):
            raise AgentSDKError("Result requires a typed owner outcome")
        if self.request_failure is not None and not isinstance(self.request_failure, RequestFailure):
            raise AgentSDKError("Request failure must be typed")
        if self.error_type is not None and self.request_failure is not RequestFailure.FAILED:
            raise AgentSDKError("Only request failure may carry an error summary")

    @property
    def status(self) -> TurnOutcomeStatus | ReflectionStatus | RequestFailure:
        if self.outcome is not None:
            return self.outcome.status
        assert self.request_failure is not None
        return self.request_failure


class TurnHandle:
    """Waiting never takes ownership of the scheduler's execution task."""

    def __init__(self, request: UserTurnRequest | ReflectionRequest, *, inbox_limits: InboxLimits = InboxLimits()) -> None:
        self.turn_id = request.request_id
        self.request = request
        self.inbox = TurnInbox(inbox_limits)
        self._future: asyncio.Future[TurnResult] = asyncio.get_running_loop().create_future()
        self._task: asyncio.Task[TurnOutcome | ReflectionOutcome] | None = None
        self._cancel_requested = False

    @property
    def state(self) -> TurnState:
        return self.inbox.activity

    @property
    def done(self) -> bool:
        return self._future.done()

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_requested

    def status(self) -> TurnState:
        return self.state

    @property
    def question(self) -> QuestionRequest | None:
        return self.inbox.question

    @property
    def budget_request(self) -> BudgetRequest | None:
        return self.inbox.budget_request

    @property
    def wait_reason(self) -> WaitReason | None:
        return self.inbox.wait_reason

    async def wait(self) -> TurnResult:
        return await asyncio.shield(self._future)

    def on_complete(self, callback: Callable[[TurnHandle], None]) -> None:
        self._future.add_done_callback(lambda _: callback(self))

    async def deliver(self, event: EnvironmentEvent) -> bool:
        if self.done or self._cancel_requested:
            raise AgentClosedError("Turn is no longer accepting events")
        await self.inbox.accept(InboxRecord(
            InboxKind(event.kind.value), event.payload, event.event_id,
        ))
        return True

    def request_cancel(self) -> bool:
        if (self.done or self.state is TurnState.FINALIZING
                or (self._task is not None and self._task.done())):
            return False
        if not self._cancel_requested:
            self._cancel_requested = True
            if self._task is not None:
                self._task.cancel()
        return True

    def bind(self, task: asyncio.Task[TurnOutcome | ReflectionOutcome]) -> None:
        if self.state is not TurnState.QUEUED:
            raise AgentSDKError("Turn execution can be bound only once")
        self._task = task
        self.inbox.set_activity(TurnState.PREPARING)
        if self._cancel_requested:
            task.cancel()

    async def finish(self, result: TurnResult) -> None:
        if result.turn_id != self.turn_id or self.done:
            raise AgentSDKError("Turn completion identity or lifecycle is invalid")
        await self.inbox.close()
        self.inbox.set_activity(TurnState.FINISHED)
        self._task = None
        self._future.set_result(result)
