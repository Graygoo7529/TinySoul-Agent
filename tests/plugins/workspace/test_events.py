"""The owner publishes committed state independently of observations and watcher I/O."""

import asyncio
from pathlib import Path
from collections.abc import Awaitable, Callable

from tinysoul.infra.time import CalendarDay
from tinysoul.plugins.workspace import WorkspaceEngineBuilder, WorkspaceSettings
from tinysoul.plugins.workspace.config import WorkspaceWatchSettings
from tinysoul.plugins.workspace.events import WorkspaceRuntime, WORKSPACE_CHANGED, WORKSPACE_WATCH
from tinysoul.plugins.workspace.services import WorkspaceService
from tinysoul.runtime.events import EnvironmentEvent, EventReceipt
from tinysoul.runtime.sources import SourceState
from tinysoul.environment.sources.fswatch import FileWatcher


class FakeWatcher:
    starts = 0
    stops = 0
    changed: Callable[[], Awaitable[None]]
    failed: Callable[[str], Awaitable[None]]

    async def start(self, root: Path, *, include: Callable[[Path], bool],
                    changed: Callable[[], Awaitable[None]],
                    failed: Callable[[str], Awaitable[None]], debounce_ms: int) -> None:
        self.starts += 1
        self.changed, self.failed = changed, failed

    async def stop(self) -> None:
        self.stops += 1


async def test_formal_operations_external_refresh_and_disabled_watch_share_owner(tmp_path: Path) -> None:
    owner = WorkspaceEngineBuilder(WorkspaceSettings(root=tmp_path)).build()
    owner.initialize_day(CalendarDay.parse("2026-09-20"))
    watcher = FakeWatcher()
    runtime = WorkspaceRuntime(owner, watcher)
    events: list[EnvironmentEvent] = []

    async def publish(event: EnvironmentEvent) -> EventReceipt:
        events.append(event)
        return EventReceipt(len(events), event.event_id, True)

    await runtime.start(publish)
    service = WorkspaceService(owner)
    try:
        await service.write_text("workspace:a.md", "one")
        await service.set_description("workspace:a.md", "manual description")
        assert len(events) == 2 and all(item.topic == WORKSPACE_CHANGED for item in events)
        await watcher.changed()
        assert len(events) == 2  # Native echo of an owner write has no new fact.
        (tmp_path / "a.md").write_text("externally expanded", encoding="utf-8")
        await watcher.changed()
        assert events[-1].source == WORKSPACE_WATCH
        assert owner.inspect("workspace:a.md").description == "manual description"
        (tmp_path / "a.md").unlink()
        await watcher.changed()
        assert not owner.snapshot().resources
        await watcher.failed("OSError")
        assert runtime.status.state is SourceState.FAILED
        assert events[-1].topic == "runtime.source_status"
        await service.write_text("workspace:b.md", "still works")
        assert events[-1].source == "workspace.owner"
    finally:
        await runtime.stop()
    assert watcher.stops == 1

    disabled = WorkspaceEngineBuilder(WorkspaceSettings(root=tmp_path,
        watch=WorkspaceWatchSettings(enabled=False))).build()
    runtime = WorkspaceRuntime(disabled, watcher)
    await runtime.start(publish)
    try:
        assert runtime.status.state is SourceState.DISABLED and watcher.starts == 1
        await WorkspaceService(disabled).write_text("workspace:c.md", "formal")
        assert events[-1].source == "workspace.owner"
    finally:
        await runtime.stop()


async def test_native_watcher_updates_owner_and_stops_before_root_rebinding(tmp_path: Path) -> None:
    owner = WorkspaceEngineBuilder(WorkspaceSettings(root=tmp_path,
        watch=WorkspaceWatchSettings(debounce_ms=30))).build()
    owner.initialize_day(CalendarDay.parse("2026-09-20"))
    runtime = WorkspaceRuntime(owner, FileWatcher())
    notified = asyncio.Event()

    async def publish(event: EnvironmentEvent) -> EventReceipt:
        if event.topic == WORKSPACE_CHANGED:
            notified.set()
        return EventReceipt(1, event.event_id, True)

    await runtime.start(publish)
    try:
        assert not owner.watches_path(tmp_path / ".tinysoul" / "workspace_manifest.json")
        assert not owner.watches_path(tmp_path / ".note.tmp")
        (tmp_path / "external.txt").write_text("external", encoding="utf-8")
        await asyncio.wait_for(notified.wait(), 5)
        assert owner.inspect("workspace:external.txt").size == 8
    finally:
        await asyncio.wait_for(runtime.stop(), 3)
    assert runtime.status.state is SourceState.STOPPED
