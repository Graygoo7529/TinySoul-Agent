"""Archived Session and Workspace context for Memory Maintenance."""

from __future__ import annotations

from threading import RLock
from datetime import date

from tinysoul.context import build_session_sync_signal
from tinysoul.infra.json import JsonObject
from tinysoul.infra.time import BusinessDay
from tinysoul.loop.preparation import TurnPreparationRequest
from tinysoul.runtime import Signal
from tinysoul.runtime.bridge import RuntimeSessionBridge
from tinysoul.session import SessionArchiveView
from tinysoul.session.errors import SessionError
from tinysoul.workspace import WorkspaceArchiveView, workspace_snapshot_signal
from tinysoul.memory import ActiveMemorySnapshot

from ..errors import MaintenanceContractError, MaintenanceInvariantError


class ArchivedMemoryMaintenanceContext:
    """Bind one closed-day projection to a serial Memory Maintenance Turn."""

    def __init__(self, *, session_bridge: RuntimeSessionBridge | None = None) -> None:
        self._session_bridge = session_bridge or RuntimeSessionBridge()
        self._lock = RLock()
        self._target_day: BusinessDay | None = None
        self._session: SessionArchiveView | None = None
        self._workspace: WorkspaceArchiveView | None = None
        self._active_memory: ActiveMemorySnapshot | None = None

    def bind(
        self,
        *,
        target_day: BusinessDay,
        session: SessionArchiveView,
        workspace: WorkspaceArchiveView | None,
        active_memory: ActiveMemorySnapshot,
    ) -> None:
        if not isinstance(target_day, BusinessDay):
            raise MaintenanceContractError(
                "Archived Memory context target must be a BusinessDay"
            )
        if session.day != target_day:
            raise MaintenanceInvariantError(
                "Archived Session day does not match Memory target day"
            )
        if workspace is not None and workspace.day != str(target_day):
            raise MaintenanceInvariantError(
                "Archived Workspace day does not match Memory target day"
            )
        if active_memory.day != target_day.value:
            raise MaintenanceInvariantError(
                "Archived active Memory day does not match target day"
            )
        with self._lock:
            if self._session is not None:
                raise MaintenanceInvariantError(
                    "Archived Memory Maintenance Context is already bound"
                )
            self._target_day = target_day
            self._session = session
            self._workspace = workspace
            self._active_memory = active_memory

    def clear(self) -> None:
        with self._lock:
            self._target_day = None
            self._session = None
            self._workspace = None
            self._active_memory = None

    def memory_target(self) -> tuple[date, ActiveMemorySnapshot]:
        with self._lock:
            target_day, _session, _workspace = self._require_binding()
            if self._active_memory is None:
                raise MaintenanceInvariantError(
                    "Archived active Memory is not bound"
                )
            return target_day.value, self._active_memory

    def prepare(self, request: TurnPreparationRequest) -> tuple[Signal, ...]:
        with self._lock:
            target_day, session, workspace = self._require_binding()
        if request.business_day != target_day:
            raise MaintenanceInvariantError(
                "Memory Turn BusinessDay does not match its archived context"
            )
        try:
            snapshot = session.background_snapshot()
        except SessionError as exc:
            raise self._session_bridge.from_session_error(exc) from exc
        signals: list[Signal] = [
            build_session_sync_signal(
                snapshot,
                call_id=f"{request.turn_id}:archived_session",
                scope=request.scope,
                source="maintenance.memory.session_prepare",
            )
        ]
        if workspace is not None:
            signals.append(
                workspace_snapshot_signal(
                    workspace.manifest,
                    call_id=f"{request.turn_id}:archived_workspace",
                    scope=request.scope,
                    source="maintenance.memory.workspace_prepare",
                )
            )
        return tuple(signals)

    def inspect(
        self,
        ref: str | None = None,
        *,
        action: str | None = None,
        continuation: str | None = None,
    ) -> JsonObject:
        with self._lock:
            _target_day, session, _workspace = self._require_binding()
        return session.inspect(ref, action=action, continuation=continuation)

    def _require_binding(
        self,
    ) -> tuple[BusinessDay, SessionArchiveView, WorkspaceArchiveView | None]:
        if self._target_day is None or self._session is None:
            raise MaintenanceInvariantError(
                "Archived Memory Maintenance Context is not bound"
            )
        return self._target_day, self._session, self._workspace
