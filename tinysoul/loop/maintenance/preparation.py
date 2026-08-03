"""Maintenance Turn preparation for archived Session and Workspace context."""

from __future__ import annotations

from threading import RLock

from tinysoul.context import build_session_sync_signal
from tinysoul.infra.json import JsonObject
from tinysoul.runtime import Signal
from tinysoul.runtime.bridge import RuntimeSessionBridge
from tinysoul.session import SessionArchiveView
from tinysoul.session.errors import SessionError
from tinysoul.workspace import WorkspaceManifest, workspace_snapshot_signal

from ..preparation import TurnPreparationRequest
from ..errors import LoopInvariantError


class ArchivedMaintenanceContext:
    """Bind one closed-day read projection to a serial Memory Maintenance Turn."""

    def __init__(self, *, session_bridge: RuntimeSessionBridge | None = None) -> None:
        self._session_bridge = session_bridge or RuntimeSessionBridge()
        self._lock = RLock()
        self._session: SessionArchiveView | None = None
        self._workspace: WorkspaceManifest | None = None

    def bind(
        self,
        *,
        session: SessionArchiveView,
        workspace: WorkspaceManifest | None,
    ) -> None:
        with self._lock:
            if self._session is not None:
                raise LoopInvariantError(
                    "Archived Maintenance Context is already bound"
                )
            self._session = session
            self._workspace = workspace

    def clear(self) -> None:
        with self._lock:
            self._session = None
            self._workspace = None

    def prepare(self, request: TurnPreparationRequest) -> tuple[Signal, ...]:
        with self._lock:
            session = self._require_session()
            workspace = self._workspace
        try:
            snapshot = session.background_snapshot()
        except SessionError as exc:
            raise self._session_bridge.from_session_error(exc) from exc
        signals: list[Signal] = [
            build_session_sync_signal(
                snapshot,
                call_id=f"{request.turn_id}:archived_session",
                scope=request.scope,
                source="maintenance.session_prepare",
            )
        ]
        if workspace is not None:
            signals.append(
                workspace_snapshot_signal(
                    workspace,
                    call_id=f"{request.turn_id}:archived_workspace",
                    scope=request.scope,
                    source="maintenance.workspace_prepare",
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
            session = self._require_session()
        return session.inspect(ref, action=action, continuation=continuation)

    def _require_session(self) -> SessionArchiveView:
        if self._session is None:
            raise LoopInvariantError(
                "Archived Maintenance Context is not bound"
            )
        return self._session
