"""Application command gateway shared by external input adapters."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from tinysoul.infra.json import JsonObject
from tinysoul.kernel.loop import LoopControlKind
from tinysoul.infra.time import CalendarDay
from tinysoul.plugins.reflection import (ReflectionScope)
from tinysoul.runtime import RunLevel, RunScope, RuntimeGatewayError, SignalBus
from tinysoul.plugins.workspace import WorkspaceManifest, workspace_snapshot_signal

from .errors import AgentError
from tinysoul.agent.errors import AgentSDKError
from .inputs import CommandReceipt, InputDispatcher, InputEvent


class AgentIngress:
    """Trusted ingress with no Reflection approval or blocking state."""

    def __init__(
        self,
        *,
        dispatcher: InputDispatcher,
        bus: SignalBus,
        active_turn_scope: Callable[[], RunScope | None],
        agent_scope: RunScope | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._bus = bus
        self._active_turn_scope = active_turn_scope
        self._agent_scope = agent_scope or RunScope().push(
            RunLevel.AGENT, "program"
        )

    @property
    def active_turn_scope(self) -> RunScope | None:
        return self._active_turn_scope()

    @property
    def current_scope(self) -> RunScope:
        return self.active_turn_scope or self._agent_scope

    async def submit(self, event: InputEvent) -> CommandReceipt:
        try:
            return await self._dispatcher.submit(event)
        except (AgentError, AgentSDKError) as exc:
            raise RuntimeGatewayError(type(exc).__name__) from exc

    async def submit_user_input(
        self,
        text: str,
        *,
        source: str,
        metadata: JsonObject,
        command_id: str | None = None,
    ) -> CommandReceipt:
        return await self.submit(
            InputEvent(
                text=text,
                source=source,
                metadata=metadata,
                command_id=command_id or f"command_{uuid4().hex}",
            )
        )

    async def submit_user_event(self, event: InputEvent) -> CommandReceipt:
        return await self.submit(event)

    async def request_control(
        self,
        kind: LoopControlKind,
        *,
        source: str,
        text: str = "",
        metadata: JsonObject | None = None,
    ) -> CommandReceipt:
        try:
            payload = dict(metadata or {})
            payload.setdefault("command_id", f"command_{uuid4().hex}")
            return await self._dispatcher.request_control(
                kind, source=source, text=text, metadata=payload
            )
        except (AgentError, AgentSDKError) as exc:
            raise RuntimeGatewayError(type(exc).__name__) from exc

    async def request_maintenance(
        self,
        scope: ReflectionScope | str,
        *,
        target_day: CalendarDay | None,
        source: str,
        metadata: JsonObject,
        command_id: str | None = None,
    ) -> CommandReceipt:
        try:
            typed_scope = (
                scope if isinstance(scope, ReflectionScope) else ReflectionScope(scope)
            )
            return await self._dispatcher.request_maintenance(
                typed_scope,
                target_day=target_day,
                source=source,
                metadata=metadata,
                command_id=command_id or f"command_{uuid4().hex}",
            )
        except (AgentError, AgentSDKError, ValueError) as exc:
            raise RuntimeGatewayError(type(exc).__name__) from exc

    def sync_workspace_context(
        self,
        manifest: WorkspaceManifest,
        *,
        source: str,
    ) -> None:
        active_scope = self._active_turn_scope()
        if active_scope is None:
            return
        self._bus.emit(
            workspace_snapshot_signal(
                manifest,
                call_id=f"gateway_{uuid4().hex[:12]}",
                scope=active_scope,
                source=source,
            )
        )
