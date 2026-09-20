"""Typed boundaries consumed by the Endpoint engines."""

from __future__ import annotations

from typing import Protocol

from tinysoul.agent.handles import TurnHandle, TurnSnapshot
from tinysoul.agent.requests import UserTurnRequest
from tinysoul.plugins.reflection import ReflectionRequest
from tinysoul.kernel.jobs import JobSnapshot

from tinysoul.infra.config import ConfigMutation
from tinysoul.infra.json import JsonObject
from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.loop import LoopControlKind
from tinysoul.kernel.loop.interaction.inbox import InboxReceipt
from tinysoul.kernel.registration import ServiceRegistry
from tinysoul.runtime import RunScope


class EndpointCommandReceipt(Protocol):
    def to_json(self) -> JsonObject: ...


class EndpointServices(Protocol):
    @property
    def registry(self) -> ServiceRegistry: ...

    def runtime_status(self, *, credentials: bool = False) -> JsonObject: ...

    async def action_catalog(self, *, scenario: str = "user") -> JsonObject: ...

    async def reflection_status(
        self, *, before: CalendarDay | None = None
    ) -> JsonObject: ...

    def turn_snapshot(self, turn_id: str) -> TurnSnapshot | None: ...

    def turn_jobs(self, turn_id: str) -> tuple[JobSnapshot, ...] | None: ...

    async def stop_job(self, turn_id: str, job_id: str) -> JobSnapshot: ...


class EndpointTurnCommands(Protocol):
    async def submit_turn(
        self, request: UserTurnRequest | ReflectionRequest
    ) -> TurnHandle: ...

    async def append_input(
        self, turn_id: str, text: str, *, input_id: str = ""
    ) -> InboxReceipt: ...

    async def reply(
        self, turn_id: str, question_id: str, response: str
    ) -> InboxReceipt: ...

    async def grant_cycles(self, turn_id: str, request_id: str, count: int) -> bool: ...

    async def cancel_turn(self, turn_id: str) -> bool: ...


class EndpointAgentIngress(Protocol):
    @property
    def commands(self) -> EndpointTurnCommands: ...

    @property
    def active_turn_scope(self) -> RunScope | None: ...

    async def submit_user_input(
        self,
        text: str,
        *,
        source: str,
        metadata: JsonObject,
        command_id: str | None = None,
    ) -> EndpointCommandReceipt: ...

    async def request_control(
        self,
        kind: LoopControlKind,
        *,
        source: str,
        text: str,
        metadata: JsonObject,
    ) -> EndpointCommandReceipt: ...


class EndpointConfigController(Protocol):
    def status(self) -> JsonObject: ...

    def catalog(self) -> JsonObject: ...

    async def patch(self, mutations: tuple[ConfigMutation, ...]) -> JsonObject: ...

    async def reload(self) -> JsonObject: ...
