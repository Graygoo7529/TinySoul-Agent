"""Typed boundaries consumed by the Endpoint engines."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol, TypeVar

from tinysoul.infra.config import ConfigMutation
from tinysoul.infra.json import JsonObject
from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.loop import LoopControlKind
from tinysoul.agent.services import AgentRuntimeServices
from tinysoul.plugins.reflection import (ReflectionAvailability, ReflectionScope)
from tinysoul.runtime import RunScope
from tinysoul.plugins.workspace import WorkspaceEngine, WorkspaceManifest


class EndpointCommandReceipt(Protocol):
    def to_json(self) -> JsonObject: ...


class EndpointReflectionStatus(Protocol):
    def availability(self) -> ReflectionAvailability: ...


class EndpointDayStatus(Protocol):
    def active_day_lease(self) -> AbstractContextManager[CalendarDay]: ...


class EndpointAgentIngress(Protocol):
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

    async def request_maintenance(
        self,
        scope: ReflectionScope | str,
        *,
        target_day: CalendarDay | None,
        source: str,
        metadata: JsonObject,
        command_id: str | None = None,
    ) -> EndpointCommandReceipt: ...

    def sync_workspace_context(
        self,
        manifest: WorkspaceManifest,
        *,
        source: str,
    ) -> None: ...


class EndpointConfigController(Protocol):
    def status(self) -> JsonObject: ...

    def catalog(self) -> JsonObject: ...

    async def patch(self, mutations: tuple[ConfigMutation, ...]) -> JsonObject: ...

    async def reload(self) -> JsonObject: ...


EndpointGenerationT = TypeVar("EndpointGenerationT", bound=AgentRuntimeServices)
