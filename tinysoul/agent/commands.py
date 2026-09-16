"""The shared Agent command boundary for SDK and external adapters."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.loop.inbox import InboxKind, InboxRecord, InboxReceipt
from tinysoul.plugins.reflection import (ReflectionRequest, ReflectionScope, ReflectionTrigger)
from tinysoul.runtime.events import EnvironmentEvent, EventBus, EventKind, EventReceipt

from .errors import AgentClosedError, AgentSDKError
from .handles import TurnHandle
from .requests import ExitRequest, UserTurnRequest
from .router import EventRouter
from .scheduler import RootScheduler


class AgentCommands:
    """Accept commands once; the scheduler and Inbox own all mutable work state."""

    def __init__(self, scheduler: RootScheduler) -> None:
        self._scheduler = scheduler
        self._router = EventRouter()
        self._events = EventBus()
        for kind in EventKind:
            self._router.subscribe(f"active.{kind.value}", kind, self._deliver_active)

    async def _deliver_active(self, event: EnvironmentEvent) -> bool:
        active = self.active_turn
        if active is None or active.done or active.cancel_requested:
            return False
        return await active.deliver(event)

    @property
    def active_turn(self) -> TurnHandle | None:
        return self._scheduler.active_turn

    def turn(self, turn_id: str) -> TurnHandle | None:
        return self._scheduler.turn_handle(turn_id)

    async def submit_turn(self, request: UserTurnRequest | ReflectionRequest) -> TurnHandle:
        existing = self.turn(request.request_id)
        handle = self._scheduler.submit_turn(request)
        return self._register(handle) if existing is None else handle

    async def request_reflection(self, request: ReflectionRequest) -> tuple[TurnHandle, ...]:
        if request.scope is not ReflectionScope.DAILY:
            return (await self.submit_turn(request),)
        # A daily trigger expands into independent profile requests. It never
        # shares an Inbox or execution result across multiple model Turns.
        day = self._scheduler.current_day()
        target = CalendarDay(day.value - timedelta(days=1))
        identity = (f"scheduled:{day}" if request.trigger is ReflectionTrigger.SCHEDULED
                    else request.request_id)
        requests = (
            replace(request, scope=ReflectionScope.HOME, request_id=f"{identity}:home"),
            replace(request, scope=ReflectionScope.MEMORY, target_day=target,
                    request_id=f"{identity}:memory:{target}"),
        )
        existing = {request.request_id for request in requests if self.turn(request.request_id) is not None}
        handles = self._scheduler.submit_batch(requests)
        return tuple(self._register(handle) if handle.turn_id not in existing else handle for handle in handles)

    def _register(self, handle: TurnHandle) -> TurnHandle:
        self._router.register_target(handle.turn_id, handle.deliver)
        handle.on_complete(lambda completed: self._router.unregister_target(completed.turn_id))
        return handle

    def cancel_turn(self, turn_id: str) -> bool:
        handle = self.turn(turn_id)
        return handle.request_cancel() if handle is not None else False

    def request_exit(self, request: ExitRequest) -> None:
        self._scheduler.request_exit(request)

    async def append_input(self, turn_id: str, text: str, *, input_id: str = "") -> InboxReceipt:
        if not isinstance(text, str) or not text.strip():
            raise AgentSDKError("Appended input must be non-empty")
        return await self._open_turn(turn_id).inbox.accept(InboxRecord(
            kind=InboxKind.INPUT, payload={"text": text.strip()}, record_id=input_id,
        ))

    async def grant_cycles(self, turn_id: str, request_id: str, count: int) -> bool:
        return await self._open_turn(turn_id).inbox.grant_cycles(request_id, count)

    async def reply(self, turn_id: str, question_id: str, response: str) -> InboxReceipt:
        return await self._open_turn(turn_id).inbox.reply(question_id, response)

    async def publish(self, event: EnvironmentEvent) -> EventReceipt:
        return await self._events.publish(event, deliver=self._router.route)

    def _open_turn(self, turn_id: str) -> TurnHandle:
        handle = self.turn(turn_id)
        if handle is None or handle.done or handle.cancel_requested:
            raise AgentClosedError("Turn is no longer accepting commands")
        return handle
