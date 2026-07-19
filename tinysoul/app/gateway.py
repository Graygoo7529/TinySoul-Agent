"""Application command gateway shared by external input adapters."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from tinysoul.home import HomeMaintenanceDecision
from tinysoul.infra.json import JsonObject
from tinysoul.loop import LoopControlKind
from tinysoul.runtime import (
    RunLevel,
    RunScope,
    RuntimeGatewayError,
    RuntimeInputBlockedError,
    SignalBus,
)
from tinysoul.workspace import WorkspaceManifest, workspace_snapshot_signal

from .errors import AppError
from .inputs import InputDispatcher, InputEvent, InputSink
from .maintenance import (
    HomeDecisionBroker,
    MaintenanceDecisionRoute,
    MaintenanceDecisionSnapshot,
)


class AppCommandGateway(InputSink):
    """Trusted application ingress for interactive and structured adapters."""

    def __init__(
        self,
        *,
        dispatcher: InputDispatcher,
        decisions: HomeDecisionBroker,
        bus: SignalBus,
        active_turn_scope: Callable[[], RunScope | None],
        program_scope: RunScope | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._decisions = decisions
        self._bus = bus
        self._active_turn_scope = active_turn_scope
        self._program_scope = program_scope or RunScope().push(
            RunLevel.PROGRAM,
            "program",
        )

    @property
    def active_turn_scope(self) -> RunScope | None:
        return self._active_turn_scope()

    @property
    def current_scope(self) -> RunScope:
        return self.active_turn_scope or self._program_scope

    def submit(self, event: InputEvent) -> None:
        """Submit one trusted interactive line, including local decisions."""

        route = self._decisions.route(event.text, source=event.source)
        if route is MaintenanceDecisionRoute.CONSUMED:
            return
        if route is MaintenanceDecisionRoute.CONSUMED_AND_EXIT:
            self._dispatcher.request_control(
                LoopControlKind.EXIT_PROGRAM,
                source=event.source,
                text=event.text,
                metadata=event.metadata,
            )
            return
        self._dispatcher.submit(event)

    def submit_user_input(
        self,
        text: str,
        *,
        source: str,
        metadata: JsonObject,
    ) -> None:
        """Submit ordinary text without interpreting maintenance decisions."""

        self.submit_user_event(
            InputEvent(text=text, source=source, metadata=metadata)
        )

    def submit_user_event(self, event: InputEvent) -> None:
        """Submit one normalized ordinary input event."""

        if self._decisions.pending_decision() is not None:
            raise RuntimeInputBlockedError(
                "A Maintenance decision must be resolved before submitting input"
            )
        try:
            self._dispatcher.submit(event)
        except AppError as exc:
            raise RuntimeGatewayError(str(exc)) from exc

    def request_control(
        self,
        kind: LoopControlKind,
        *,
        source: str,
        text: str = "",
        metadata: JsonObject | None = None,
    ) -> None:
        if kind is LoopControlKind.EXIT_PROGRAM:
            self._decisions.stop_pending(source=source)
        try:
            self._dispatcher.request_control(
                kind,
                source=source,
                text=text,
                metadata=metadata,
            )
        except AppError as exc:
            raise RuntimeGatewayError(str(exc)) from exc

    def pending_maintenance_decision(
        self,
    ) -> MaintenanceDecisionSnapshot | None:
        return self._decisions.pending_decision()

    def resolve_maintenance_decision(
        self,
        decision_id: str,
        decision: HomeMaintenanceDecision | None,
    ) -> bool:
        return self._decisions.submit_decision(decision_id, decision)

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
