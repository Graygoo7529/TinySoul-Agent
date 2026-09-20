"""Committed Workspace changes and their bounded pending publication."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Protocol

from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.runtime import (
    NullObservationEmitter,
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    emit_observation,
)
from tinysoul.runtime.events import EnvironmentEvent, EventKind
from tinysoul.runtime.sources import EventSink, SourceState, SourceStatus

from .errors import WorkspaceError, WorkspaceReconciliationError
from .storage.manifest import WorkspaceManifest

if TYPE_CHECKING:
    from .engine import WorkspaceEngine

WORKSPACE_CHANGED = "workspace.changed"
WORKSPACE_OWNER = "workspace.owner"
WORKSPACE_WATCH = "workspace.fswatch"


class WorkspaceChangeOperation(StrEnum):
    INITIALIZE = "initialize"
    RECONCILE = "reconcile"
    DESCRIBE = "describe"
    WRITE = "write"
    APPEND = "append"
    BUNDLE = "bundle"
    EDIT = "edit"
    MOVE = "move"
    MKDIR = "mkdir"
    TAG = "tag"
    TRASH = "trash"
    RESTORE = "restore"


@dataclass(frozen=True)
class WorkspaceChange:
    operation: WorkspaceChangeOperation
    before: WorkspaceManifest
    after: WorkspaceManifest

    @property
    def created_links(self) -> tuple[str, ...]:
        before = {record.link for record in self.before.resources}
        return tuple(
            record.link for record in self.after.resources if record.link not in before
        )

    @property
    def removed_links(self) -> tuple[str, ...]:
        after = {record.link for record in self.after.resources}
        return tuple(
            record.link for record in self.before.resources if record.link not in after
        )

    @property
    def updated_links(self) -> tuple[str, ...]:
        before = {record.link: record for record in self.before.resources}
        return tuple(
            record.link
            for record in self.after.resources
            if record.link in before and record != before[record.link]
        )

    @property
    def links(self) -> tuple[str, ...]:
        return tuple(sorted({*self.created_links, *self.updated_links, *self.removed_links}))


class WorkspaceEvents:
    """At most one unflushed transition per owner/source; no event history."""

    def __init__(self) -> None:
        self._pending: dict[str, WorkspaceChange] = {}
        self._lock = RLock()
        self._publishing = asyncio.Lock()
        self._sink: EventSink | None = None

    def bind(self, sink: EventSink | None) -> None:
        with self._lock:
            self._pending.clear()
            self._sink = sink

    def stage(self, change: WorkspaceChange, source: str = WORKSPACE_OWNER) -> None:
        with self._lock:
            if self._sink is None or change.before == change.after:
                return
            previous = self._pending.get(source)
            self._pending[source] = WorkspaceChange(
                change.operation,
                previous.before if previous else change.before,
                change.after,
            )

    async def flush(self) -> None:
        async with self._publishing:
            with self._lock:
                pending, self._pending = self._pending, {}
                sink = self._sink
            if sink is None:
                return
            for source, change in pending.items():
                if change.before == change.after:
                    continue
                links = change.links
                await sink(
                    EnvironmentEvent(
                        EventKind.EVENT,
                        {
                            "day": change.after.day,
                            "operation": change.operation.value,
                            "changed_count": len(links),
                            "links": list(links[:16]),
                            "summary": (
                                "Workspace state changed; inspect the current "
                                "workbench for resource summaries."
                            ),
                        },
                        topic=WORKSPACE_CHANGED,
                        source=source,
                    )
                )


class WorkspaceWatcher(Protocol):
    async def start(
        self,
        root: Path,
        *,
        include: Callable[[Path], bool],
        changed: Callable[[], Awaitable[None]],
        failed: Callable[[str], Awaitable[None]],
        debounce_ms: int,
    ) -> None: ...

    async def stop(self) -> None: ...


class WorkspaceRuntime:
    """A generation's one owner publisher and optional active-root listener."""

    def __init__(
        self,
        workspace: WorkspaceEngine,
        watcher: WorkspaceWatcher,
        *,
        observations: ObservationEmitter | None = None,
    ) -> None:
        self._workspace = workspace
        self._watcher = watcher
        self._observations = observations or NullObservationEmitter()
        self._sink: EventSink | None = None
        self._status = SourceStatus(
            WORKSPACE_WATCH, SourceState.STOPPED, topics=(WORKSPACE_CHANGED,)
        )

    @property
    def status(self) -> SourceStatus:
        return self._status

    async def start(self, publish: EventSink) -> None:
        if self._sink is not None:
            return
        self._sink = publish
        self._workspace.events.bind(publish)
        if self._status.state is SourceState.FAILED:
            return  # Explicit reload/restart creates a new native binding.
        settings = self._workspace.settings.watch
        self._status = SourceStatus(
            WORKSPACE_WATCH,
            SourceState.RUNNING if settings.enabled else SourceState.DISABLED,
            topics=(WORKSPACE_CHANGED,),
        )
        if settings.enabled:
            try:
                await self._watcher.start(
                    self._workspace.root,
                    include=self._workspace.watches_path,
                    changed=self._refresh,
                    failed=self._failed,
                    debounce_ms=settings.debounce_ms,
                )
                await self._refresh()
            except BaseException:
                await self.stop()
                raise

    async def _refresh(self) -> None:
        if self._status.state is not SourceState.RUNNING:
            return
        operations = JoinedOperations()
        try:
            result = await operations.run(self._workspace.reconcile_external)
            if not result.complete:
                raise WorkspaceReconciliationError(
                    "File discovery did not produce a complete Workspace state"
                )
        except WorkspaceError as exc:
            self._status = SourceStatus(
                WORKSPACE_WATCH, SourceState.FAILED,
                type(exc).__name__, (WORKSPACE_CHANGED,),
            )
            if self._sink is not None:
                await self._sink(
                    EnvironmentEvent(
                        EventKind.EVENT,
                        {
                            "summary": "Workspace discovery could not complete.",
                            "error_type": type(exc).__name__,
                        },
                        topic="workspace.unavailable",
                        source=WORKSPACE_WATCH,
                    )
                )
            raise
        await operations.finish(self._workspace.events.flush)
        operations.check_cancelled()

    async def _failed(self, error_type: str) -> None:
        self._status = SourceStatus(
            WORKSPACE_WATCH, SourceState.FAILED, error_type,
            topics=(WORKSPACE_CHANGED,),
        )
        summary = (
            "External Workspace file sensing stopped; "
            "formal Workspace operations remain available."
        )
        emit_observation(
            self._observations,
            ObservationEvent(
                name="runtime.source_status",
                source=WORKSPACE_WATCH,
                level=ObservationLevel.NORMAL,
                message=summary,
                payload={
                    "state": "failed",
                    "error_type": error_type,
                    "topics": [WORKSPACE_CHANGED],
                },
            ),
        )
        if self._sink is not None:
            await self._sink(
                EnvironmentEvent(
                    EventKind.EVENT,
                    {
                        "state": "failed",
                        "topics": [WORKSPACE_CHANGED],
                        "summary": summary,
                        "error_type": error_type,
                    },
                    topic="runtime.source_status",
                    source=WORKSPACE_WATCH,
                )
            )

    async def stop(self) -> None:
        try:
            await self._watcher.stop()
        finally:
            self._sink = None
            if self._status.state is not SourceState.FAILED:
                self._status = SourceStatus(
                    WORKSPACE_WATCH, SourceState.STOPPED, topics=(WORKSPACE_CHANGED,)
                )

    async def close(self) -> None:
        """Release publication after Turn/Job finalization has completed."""
        try:
            await self.stop()
        finally:
            self._workspace.events.bind(None)
