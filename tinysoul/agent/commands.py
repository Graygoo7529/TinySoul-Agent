"""The shared Agent command boundary for SDK and external adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta

from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.interaction import QuestionAnswer
from tinysoul.kernel.loop.interaction.inbox import InboxKind, InboxReceipt, InboxRecord
from tinysoul.plugins.reflection import (
    ReflectionRequest,
    ReflectionScope,
    ReflectionTrigger,
)
from tinysoul.runtime.events import EnvironmentEvent, EventBus, EventReceipt
from tinysoul.runtime.sources import SourceStatus

from .dispatch.router import EventRouter
from .dispatch.scheduler import RootScheduler
from .errors import AgentClosedError, AgentSDKError
from .handles import TurnHandle
from .requests import ExitRequest, UserTurnRequest


class AgentCommands:
    """Accept commands once; the scheduler and Inbox own all mutable work state."""

    def __init__(
        self,
        scheduler: RootScheduler,
        *,
        source_statuses: Callable[[], tuple[SourceStatus, ...]] = lambda: (),
    ) -> None:
        self._scheduler = scheduler
        self._router = EventRouter()
        self._events = EventBus()
        self._source_statuses = source_statuses

    @property
    def active_turn(self) -> TurnHandle | None:
        return self._scheduler.active_turn

    def request(self, request_id: str) -> TurnHandle | None:
        return self._scheduler.request_handle(request_id)

    async def submit_turn(
        self, request: UserTurnRequest | ReflectionRequest
    ) -> TurnHandle:
        if (
            isinstance(request, ReflectionRequest)
            and request.target_day is not None
            and request.target_day > self._scheduler.current_day()
        ):
            raise AgentSDKError("Memory Reflection target day cannot be in the future")
        existing = self.request(request.request_id)
        handle = self._scheduler.submit_turn(request)
        return self._register(handle) if existing is None else handle

    async def request_reflection(
        self, request: ReflectionRequest
    ) -> tuple[TurnHandle, ...]:
        if request.scope is not ReflectionScope.DAILY:
            return (await self.submit_turn(request),)
        # A daily trigger expands into independent profile requests. It never
        # shares an Inbox or execution result across multiple model Turns.
        day = request.scheduled_day or self._scheduler.current_day()
        target = CalendarDay(day.value - timedelta(days=1))
        identity = (
            f"scheduled:{day}"
            if request.trigger is ReflectionTrigger.SCHEDULED
            else request.request_id
        )
        requests = (
            replace(request, scope=ReflectionScope.HOME, request_id=f"{identity}:home"),
            replace(
                request,
                scope=ReflectionScope.MEMORY,
                target_day=target,
                request_id=f"{identity}:memory:{target}",
            ),
        )
        existing = {
            request.request_id
            for request in requests
            if self.request(request.request_id) is not None
        }
        handles = self._scheduler.submit_batch(requests)
        return tuple(
            self._register(handle) if handle.request_id not in existing else handle
            for handle in handles
        )

    def _register(self, handle: TurnHandle) -> TurnHandle:
        handle.inbox.bind_source_status(self._source_statuses)
        self._router.register_target(handle.request_id, handle.deliver)
        self._router.subscribe(
            handle.request_id, handle.request_id, handle.inbox.accepts_event
        )
        handle.on_complete(
            lambda completed: self._router.unregister_target(completed.request_id)
        )
        return handle

    async def cancel_request(self, request_id: str) -> bool:
        return await self._scheduler.cancel_request(request_id)

    def request_exit(self, request: ExitRequest) -> None:
        self._scheduler.request_exit(request)

    async def append_input(
        self, request_id: str, text: str, *, input_id: str = ""
    ) -> InboxReceipt:
        if not isinstance(text, str) or not text.strip():
            raise AgentSDKError("Appended input must be non-empty")
        return await self._open_turn(request_id).inbox.accept(
            InboxRecord(
                kind=InboxKind.INPUT,
                payload={"text": text.strip()},
                record_id=input_id,
            )
        )

    async def grant_cycles(
        self, request_id: str, budget_request_id: str, count: int
    ) -> bool:
        return await self._open_turn(request_id).inbox.grant_cycles(
            budget_request_id, count
        )

    async def reply(
        self, request_id: str, question_id: str, answer: QuestionAnswer
    ) -> InboxReceipt:
        return await self._open_turn(request_id).inbox.reply(question_id, answer)

    async def publish(self, event: EnvironmentEvent) -> EventReceipt:
        if event.source != "host":
            raise AgentSDKError("Host events must use the host source")
        return await self.publish_internal(event)

    async def publish_internal(self, event: EnvironmentEvent) -> EventReceipt:
        return await self._events.publish(event, deliver=self._router.route)

    def _open_turn(self, request_id: str) -> TurnHandle:
        handle = self.request(request_id)
        if handle is None or handle.done or handle.cancel_requested:
            raise AgentClosedError("Turn is no longer accepting commands")
        return handle
