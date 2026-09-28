"""Typed boundaries consumed by the Endpoint engines."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Protocol

from tinysoul.agent.handles import TurnHandle, TurnSnapshot
from tinysoul.agent.requests import UserTurnRequest
from tinysoul.infra.config import ConfigMutation
from tinysoul.infra.json import JsonObject
from tinysoul.infra.paging import PageOptions
from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.interaction import QuestionAnswer
from tinysoul.kernel.jobs import JobSnapshot
from tinysoul.kernel.loop import LoopControlKind
from tinysoul.kernel.loop.interaction.inbox import InboxReceipt
from tinysoul.kernel.registration import ServiceRegistry
from tinysoul.plugins.reflection import ReflectionRequest
from tinysoul.plugins.workspace.inspection.models import WorkspaceBlobRead
from tinysoul.runtime import RunScope


class EndpointCommandReceipt(Protocol):
    def to_json(self) -> JsonObject: ...


class EndpointLifecycle(Protocol):
    """Host lifecycle operations exposed to the HTTP adapter."""

    async def restart(self) -> JsonObject: ...


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

    async def job_detail(self, turn_id: str, job_id: str) -> JsonObject: ...

    async def job_output(
        self, turn_id: str, job_id: str, page: PageOptions = PageOptions()
    ) -> JsonObject: ...

    async def subagent_status(self) -> JsonObject: ...

    async def resolve_resource(
        self,
        reference: str,
        *,
        origin_link: str | None = None,
        day: CalendarDay | None = None,
        turn_id: str | None = None,
        view: str = "effective",
    ) -> JsonObject: ...

    async def expand_servers(self, page: PageOptions = PageOptions()) -> JsonObject: ...

    async def expand_tools(
        self,
        server_id: str,
        *,
        tool_name: str | None = None,
        page: PageOptions = PageOptions(),
    ) -> JsonObject: ...

    async def expand_refresh(self, server_id: str) -> JsonObject: ...

    async def days(
        self, *, before: CalendarDay | None = None, limit: int = 30
    ) -> JsonObject: ...

    async def turn_interactions(
        self, turn_id: str, page: PageOptions = PageOptions()
    ) -> JsonObject: ...

    async def context_overview(self, turn_id: str) -> JsonObject: ...

    async def context_segment(
        self, turn_id: str, segment_id: str, page: PageOptions = PageOptions()
    ) -> JsonObject: ...

    async def context_inspect(
        self,
        turn_id: str,
        ref: str,
        *,
        query: str | None = None,
        continuation: str | None = None,
    ) -> JsonObject: ...

    async def session_turns(
        self, day: CalendarDay | None = None, page: PageOptions = PageOptions()
    ) -> JsonObject: ...

    async def memory_active(
        self, day: CalendarDay | None = None, page: PageOptions = PageOptions()
    ) -> JsonObject: ...

    async def workspace_manifest(
        self, day: CalendarDay | None = None
    ) -> JsonObject: ...

    async def workspace_text(
        self,
        link: str,
        day: CalendarDay | None = None,
        *,
        page: PageOptions = PageOptions(),
        full: bool = False,
    ) -> JsonObject: ...

    async def workspace_trash(
        self, day: CalendarDay | None = None, page: PageOptions = PageOptions()
    ) -> JsonObject: ...

    def workspace_blob(
        self, link: str, day: CalendarDay | None = None
    ) -> AbstractAsyncContextManager[WorkspaceBlobRead]: ...

    async def session_interactions(
        self, turn_id: str, day: CalendarDay, page: PageOptions = PageOptions()
    ) -> JsonObject: ...

    async def session_inspect(
        self,
        day: CalendarDay | None = None,
        *,
        ref: str | None = None,
        query: str | None = None,
        continuation: str | None = None,
    ) -> JsonObject: ...


class EndpointTurnCommands(Protocol):
    async def submit_turn(
        self, request: UserTurnRequest | ReflectionRequest
    ) -> TurnHandle: ...

    async def append_input(
        self, turn_id: str, text: str, *, input_id: str = ""
    ) -> InboxReceipt: ...

    async def reply(
        self, turn_id: str, question_id: str, answer: QuestionAnswer
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
    def status(self, *, view: str = "saved") -> JsonObject: ...

    def catalog(self) -> JsonObject: ...

    async def patch(self, mutations: tuple[ConfigMutation, ...]) -> JsonObject: ...

    async def reload(self) -> JsonObject: ...

    async def apply(
        self,
        mutations: tuple[ConfigMutation, ...] = (),
        *,
        preset_id: str | None = None,
    ) -> JsonObject: ...

    def presets(self) -> tuple[JsonObject, ...]: ...

    def preset(self, preset_id: str) -> JsonObject: ...

    async def save_preset(
        self,
        *,
        name: str,
        description: str = "",
        source: str = "saved",
        mutations: tuple[ConfigMutation, ...] = (),
        include_budgets: bool = True,
    ) -> JsonObject: ...

    async def update_preset(
        self,
        preset_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        capture_source: str | None = None,
        mutations: tuple[ConfigMutation, ...] = (),
        include_budgets: bool = True,
    ) -> JsonObject: ...

    async def delete_preset(self, preset_id: str) -> None: ...
