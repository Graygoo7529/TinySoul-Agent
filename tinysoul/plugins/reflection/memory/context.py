"""Archived Session and Workspace context for Memory Reflection."""

from __future__ import annotations

from threading import RLock
from datetime import date

from tinysoul.infra.json import JsonObject
from tinysoul.infra.time import CalendarDay
from tinysoul.plugins.session import SessionArchiveView
from tinysoul.plugins.session.background import SessionBackgroundSnapshot
from tinysoul.plugins.workspace import WorkspaceArchiveView
from tinysoul.plugins.memory import ActiveMemoryDocument

from ..errors import ReflectionContractError, ReflectionInvariantError


class ArchivedMemoryReflectionContext:
    """Bind one closed-day projection to a serial Memory Reflection Turn."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._target_day: CalendarDay | None = None
        self._session: SessionArchiveView | None = None
        self._workspace: WorkspaceArchiveView | None = None
        self._active_memory: ActiveMemoryDocument | None = None

    def bind(
        self,
        *,
        target_day: CalendarDay,
        session: SessionArchiveView,
        workspace: WorkspaceArchiveView | None,
        active_memory: ActiveMemoryDocument,
    ) -> None:
        if not isinstance(target_day, CalendarDay):
            raise ReflectionContractError(
                "Archived Memory context target must be a CalendarDay"
            )
        if session.day != target_day:
            raise ReflectionInvariantError(
                "Archived Session day does not match Memory target day"
            )
        if workspace is not None and workspace.day != str(target_day):
            raise ReflectionInvariantError(
                "Archived Workspace day does not match Memory target day"
            )
        if active_memory.day != target_day.value:
            raise ReflectionInvariantError(
                "Archived active Memory day does not match target day"
            )
        with self._lock:
            if self._session is not None:
                raise ReflectionInvariantError(
                    "Archived Memory Reflection Context is already bound"
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

    def memory_target(self) -> tuple[date, ActiveMemoryDocument]:
        with self._lock:
            target_day, _session, _workspace = self._require_binding()
            if self._active_memory is None:
                raise ReflectionInvariantError(
                    "Archived active Memory is not bound"
                )
            return target_day.value, self._active_memory

    def source_day(self) -> CalendarDay:
        with self._lock:
            return self._require_binding()[0]

    def source_workspace(self) -> WorkspaceArchiveView | None:
        with self._lock:
            return self._require_binding()[2]

    def background_snapshot(self, day: CalendarDay) -> SessionBackgroundSnapshot:
        with self._lock:
            target_day, session, _workspace = self._require_binding()
        if day != target_day:
            raise ReflectionInvariantError("Session source day does not match Memory target")
        return session.background_snapshot()

    def inspect(
        self,
        ref: str | None = None,
        *,
        action: str | None = None,
        continuation: str | None = None,
        expected_revision: int | None = None,
    ) -> JsonObject:
        with self._lock:
            _target_day, session, _workspace = self._require_binding()
        return session.inspect(
            ref, action=action, continuation=continuation, expected_revision=expected_revision,
        )

    def _require_binding(
        self,
    ) -> tuple[CalendarDay, SessionArchiveView, WorkspaceArchiveView | None]:
        if self._target_day is None or self._session is None:
            raise ReflectionInvariantError(
                "Archived Memory Reflection Context is not bound"
            )
        return self._target_day, self._session, self._workspace
