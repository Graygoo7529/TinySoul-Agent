"""Typed boundaries consumed by the Endpoint engines."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol, TypeVar

from tinysoul.infra.config import ConfigMutation
from tinysoul.infra.json import JsonObject
from tinysoul.infra.time import BusinessDay
from tinysoul.loop import LoopControlKind
from tinysoul.maintenance import MaintenanceAvailability, MaintenanceScope
from tinysoul.runtime import RunScope
from tinysoul.workspace import WorkspaceEngine, WorkspaceManifest


class EndpointCommandReceipt(Protocol):
    def to_json(self) -> JsonObject: ...


class EndpointMaintenanceStatus(Protocol):
    def availability(self) -> MaintenanceAvailability: ...

    def active_day_lease(self) -> AbstractContextManager[BusinessDay]: ...


class EndpointAppGateway(Protocol):
    @property
    def active_turn_scope(self) -> RunScope | None: ...

    def submit_user_input(
        self,
        text: str,
        *,
        source: str,
        metadata: JsonObject,
        command_id: str | None = None,
    ) -> EndpointCommandReceipt: ...

    def request_control(
        self,
        kind: LoopControlKind,
        *,
        source: str,
        text: str,
        metadata: JsonObject,
    ) -> EndpointCommandReceipt: ...

    def request_maintenance(
        self,
        scope: MaintenanceScope | str,
        *,
        target_day: BusinessDay | None,
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

    def patch(self, mutations: tuple[ConfigMutation, ...]) -> JsonObject: ...


class EndpointRuntimeGeneration(Protocol):
    @property
    def user_turn(self) -> "EndpointUserTurn": ...

    @property
    def maintenance(self) -> EndpointMaintenanceStatus: ...

    @property
    def workspace(self) -> WorkspaceEngine: ...


class EndpointUserTurn(Protocol):
    def action_catalog(self) -> JsonObject: ...


EndpointGenerationT = TypeVar("EndpointGenerationT", bound=EndpointRuntimeGeneration)
