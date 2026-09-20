"""Accepted root work and its authoritative completion handle."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.kernel.jobs import JobSnapshot

from tinysoul.kernel.loop.interaction.inbox import (
    BudgetRequest,
    InboxKind,
    InboxClosedError,
    InboxLimits,
    InboxRecord,
    QuestionRequest,
    TurnInbox,
    TurnState,
    WaitReason,
)
from tinysoul.kernel.loop.outcomes import TurnOutcomeStatus
from tinysoul.runtime.events import EnvironmentEvent
from tinysoul.kernel.loop.turn import TurnOutcome
from tinysoul.plugins.reflection.models import (
    ReflectionOutcome,
    ReflectionRequest,
    ReflectionStatus,
)

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
            raise AgentSDKError(
                "Result requires exactly one owner outcome or request failure"
            )
        if self.outcome is not None and not isinstance(
            self.outcome, (TurnOutcome, ReflectionOutcome)
        ):
            raise AgentSDKError("Result requires a typed owner outcome")
        if self.request_failure is not None and not isinstance(
            self.request_failure, RequestFailure
        ):
            raise AgentSDKError("Request failure must be typed")
        if (
            self.error_type is not None
            and self.request_failure is not RequestFailure.FAILED
        ):
            raise AgentSDKError("Only request failure may carry an error summary")

    @property
    def status(self) -> TurnOutcomeStatus | ReflectionStatus | RequestFailure:
        if self.outcome is not None:
            return self.outcome.status
        assert self.request_failure is not None
        return self.request_failure

    def to_json(self) -> JsonObject:
        """Expose owner results, never execution trace or Runtime transfers."""
        outcome = self.outcome
        if isinstance(outcome, ReflectionOutcome):
            value = outcome.to_json()
        elif isinstance(outcome, TurnOutcome):
            output = outcome.output
            value: JsonObject = {
                "active_day": str(outcome.active_day),
                "status": outcome.status.value,
                "output": (
                    {
                        "text": output.text,
                        "result_id": output.result_id,
                        "references": list(output.references),
                        "metadata": output.metadata,
                    }
                    if output is not None
                    else None
                ),
                "completion": outcome.completion,
                "failure": outcome.failure.to_json() if outcome.failure else None,
                "finish_failures": [item.to_json() for item in outcome.finish_failures],
                "cleanup": [
                    {"resource": item.resource, "error_type": item.error_type}
                    for item in outcome.cleanup_diagnostics
                ],
            }
        else:
            value = {
                "status": self.status.value,
                "request_failure": self.status.value,
                "error_type": self.error_type,
            }
        return to_json_object({"turn_id": self.turn_id, **value})


class TurnKind(StrEnum):
    USER = "user"
    HOME = "home"
    MEMORY = "memory"


@dataclass(frozen=True)
class TurnSnapshot:
    turn_id: str
    kind: TurnKind
    state: TurnState
    cancel_requested: bool
    wait_reason: WaitReason | None
    question: QuestionRequest | None
    budget_request: BudgetRequest | None
    result: TurnResult | None
    jobs: tuple[JobSnapshot, ...] = ()

    def __post_init__(self) -> None:
        if (
            not self.turn_id
            or not isinstance(self.kind, TurnKind)
            or not isinstance(self.state, TurnState)
        ):
            raise AgentSDKError("Turn snapshot requires typed identity and state")
        if self.result is not None and self.result.turn_id != self.turn_id:
            raise AgentSDKError("Turn snapshot result identity differs")

    def to_json(self) -> JsonObject:
        question, budget = self.question, self.budget_request
        return {
            "turn_id": self.turn_id,
            "kind": self.kind.value,
            "state": self.state.value,
            "cancel_requested": self.cancel_requested,
            "wait_reason": self.wait_reason.value if self.wait_reason else None,
            "question": (
                {
                    "question_id": question.question_id,
                    "text": question.text,
                    "options": list(question.options),
                    "timeout_seconds": question.timeout_seconds,
                }
                if question is not None
                else None
            ),
            "budget_request": (
                {"request_id": budget.request_id, "next_cycle_index": budget.next_cycle_index}
                if budget is not None
                else None
            ),
            "result": self.result.to_json() if self.result is not None else None,
            "jobs": [item.to_json() for item in self.jobs],
        }


class TurnHandle:
    """Waiting never takes ownership of the scheduler's execution task."""

    def __init__(
        self,
        request: UserTurnRequest | ReflectionRequest,
        *,
        inbox_limits: InboxLimits = InboxLimits(),
    ) -> None:
        self.turn_id = request.request_id
        self.request = request
        self.inbox = TurnInbox(inbox_limits)
        self._future: asyncio.Future[TurnResult] = (
            asyncio.get_running_loop().create_future()
        )
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

    def snapshot(self, *, jobs: tuple[JobSnapshot, ...] = ()) -> TurnSnapshot:
        kind = (
            TurnKind.USER
            if isinstance(self.request, UserTurnRequest)
            else TurnKind(self.request.scope.value)
        )
        return TurnSnapshot(
            turn_id=self.turn_id,
            kind=kind,
            state=self.state,
            cancel_requested=self.cancel_requested,
            wait_reason=self.wait_reason,
            question=self.question,
            budget_request=self.budget_request,
            result=self.result,
            jobs=jobs,
        )

    @property
    def question(self) -> QuestionRequest | None:
        return self.inbox.question

    @property
    def budget_request(self) -> BudgetRequest | None:
        return self.inbox.budget_request

    @property
    def result(self) -> TurnResult | None:
        """Return the retained result without exposing the Future."""
        if not self._future.done() or self._future.cancelled():
            return None
        return self._future.result()

    @property
    def wait_reason(self) -> WaitReason | None:
        return self.inbox.wait_reason

    async def wait(self) -> TurnResult:
        return await asyncio.shield(self._future)

    def on_complete(self, callback: Callable[[TurnHandle], None]) -> None:
        self._future.add_done_callback(lambda _: callback(self))

    async def deliver(self, event: EnvironmentEvent) -> bool:
        if self.done or self._cancel_requested:
            return False
        try:
            receipt = await self.inbox.accept_event(event)
        except InboxClosedError:
            return False
        return receipt.accepted

    def request_cancel(self) -> bool:
        if (
            self.done
            or self.state is TurnState.FINALIZING
            or (self._task is not None and self._task.done())
        ):
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
