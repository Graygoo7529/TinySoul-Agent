"""Application command gateway shared by external input adapters."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from tinysoul.infra.json import JsonObject
from tinysoul.loop import LoopControlKind
from tinysoul.maintenance import BusinessDay, MaintenanceScope
from tinysoul.runtime import RunLevel, RunScope, RuntimeGatewayError, SignalBus
from tinysoul.workspace import WorkspaceManifest, workspace_snapshot_signal

from .errors import AppError
from .inputs import CommandReceipt, InputDispatcher, InputEvent, InputSink


class AppCommandGateway(InputSink):
    """Trusted ingress with no Maintenance approval or blocking state."""

    def __init__(
        self,
        *,
        dispatcher: InputDispatcher,
        bus: SignalBus,
        active_turn_scope: Callable[[], RunScope | None],
        program_scope: RunScope | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._bus = bus
        self._active_turn_scope = active_turn_scope
        self._program_scope = program_scope or RunScope().push(
            RunLevel.PROGRAM, "program"
        )

    @property
    def active_turn_scope(self) -> RunScope | None:
        return self._active_turn_scope()

    @property
    def current_scope(self) -> RunScope:
        return self.active_turn_scope or self._program_scope

    def submit(self, event: InputEvent) -> CommandReceipt:
        try:
            return self._dispatcher.submit(event)
        except AppError as exc:
            raise RuntimeGatewayError(str(exc)) from exc

    def submit_user_input(
        self,
        text: str,
        *,
        source: str,
        metadata: JsonObject,
        command_id: str | None = None,
    ) -> CommandReceipt:
        return self.submit(
            InputEvent(
                text=text,
                source=source,
                metadata=metadata,
                command_id=command_id or f"command_{uuid4().hex}",
            )
        )

    def submit_user_event(self, event: InputEvent) -> CommandReceipt:
        return self.submit(event)

    def request_control(
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
            return self._dispatcher.request_control(
                kind, source=source, text=text, metadata=payload
            )
        except AppError as exc:
            raise RuntimeGatewayError(str(exc)) from exc

    def request_maintenance(
        self,
        scope: MaintenanceScope | str,
        *,
        target_day: BusinessDay | None,
        rebuild_memory: bool = False,
        source: str,
        metadata: JsonObject,
        command_id: str | None = None,
    ) -> CommandReceipt:
        try:
            typed_scope = (
                scope if isinstance(scope, MaintenanceScope) else MaintenanceScope(scope)
            )
            return self._dispatcher.request_maintenance(
                typed_scope,
                target_day=target_day,
                rebuild_memory=rebuild_memory,
                source=source,
                metadata=metadata,
                command_id=command_id or f"command_{uuid4().hex}",
            )
        except (AppError, ValueError) as exc:
            raise RuntimeGatewayError(str(exc)) from exc

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
