"""Typed boundaries consumed by the Endpoint engines."""

from __future__ import annotations

from typing import Protocol

from tinysoul.infra.config import ConfigMutation
from tinysoul.infra.json import JsonObject
from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.loop import LoopControlKind
from tinysoul.kernel.registration import ServiceRegistry
from tinysoul.plugins.reflection import ReflectionScope
from tinysoul.runtime import RunScope
from tinysoul.plugins.workspace import WorkspaceManifest


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

    async def request_reflection(
        self,
        scope: ReflectionScope | str,
        *,
        target_day: CalendarDay | None,
        source: str,
        metadata: JsonObject,
        command_id: str | None = None,
        instructions: str = "",
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
