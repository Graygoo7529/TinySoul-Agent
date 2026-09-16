"""Accepted root work and its authoritative completion handle."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from tinysoul.kernel.loop.inbox import BudgetRequest, InboxKind, InboxLimits, InboxRecord, QuestionRequest, TurnInbox, WaitReason
from tinysoul.runtime.events import EnvironmentEvent
from tinysoul.kernel.loop.turn import TurnOutcome
from tinysoul.plugins.reflection.models import ReflectionOutcome, ReflectionRequest

from .errors import AgentClosedError, AgentSDKError
from .requests import UserTurnRequest


class TurnState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    FINISHED = "finished"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True)
class TurnResult:
    turn_id: str
    state: TurnState
    outcome: TurnOutcome | ReflectionOutcome | None = None
    error_type: str | None = None

    def __post_init__(self) -> None:
        if not self.turn_id or self.state not in {
            TurnState.FINISHED, TurnState.CANCELLED, TurnState.FAILED,
        }:
            raise AgentSDKError("TurnResult requires a terminal state and identity")
        if self.state is TurnState.FINISHED and self.outcome is None:
            raise AgentSDKError("Finished work requires its owner outcome")


class TurnHandle:
    """Waiting never takes ownership of the scheduler's execution task."""

    def __init__(self, request: UserTurnRequest | ReflectionRequest, *, inbox_limits: InboxLimits = InboxLimits()) -> None:
        self.turn_id = request.request_id
        self.request = request
        self.inbox = TurnInbox(inbox_limits)
        self._state = TurnState.QUEUED
        self._future: asyncio.Future[TurnResult] = asyncio.get_running_loop().create_future()
        self._task: asyncio.Task[TurnOutcome | ReflectionOutcome] | None = None
        self._cancel_requested = False

    @property
    def state(self) -> TurnState:
        if self._state is TurnState.RUNNING and self.inbox.wait_reason is not None:
            return TurnState.WAITING
        return self._state

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
        if self.done or (self._task is not None and self._task.done()):
            return False
        if not self._cancel_requested:
            self._cancel_requested = True
            if self._task is not None:
                self._task.cancel()
        return True

    def bind(self, task: asyncio.Task[TurnOutcome | ReflectionOutcome]) -> None:
        if self._state is not TurnState.QUEUED:
            raise AgentSDKError("Turn execution can be bound only once")
        self._task = task
        self._state = TurnState.RUNNING
        if self._cancel_requested:
            task.cancel()

    async def finish(self, result: TurnResult) -> None:
        if result.turn_id != self.turn_id or self.done:
            raise AgentSDKError("Turn completion identity or lifecycle is invalid")
        await self.inbox.close()
        self._state = result.state
        self._task = None
        self._future.set_result(result)
