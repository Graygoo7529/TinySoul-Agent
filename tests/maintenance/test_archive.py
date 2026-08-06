from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import tinysoul.maintenance.archive.engine as daily_module
import tinysoul.workspace.engine as workspace_engine_module
from tinysoul.home import AgentHomeEngine, AgentHomeEngineBuilder, AgentHomeSettings
from tinysoul.infra.time import BusinessDay
from tinysoul.maintenance import DailyLifecycleCoordinator
from tinysoul.memory import MemoryEngine, MemorySettings
from tinysoul.maintenance.errors import (
    MaintenanceContractError as LoopContractError,
    MaintenanceInvariantError as LoopInvariantError,
)
from tinysoul.runtime import (
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    RunLevel,
    RunScope,
)
from tinysoul.session import SessionEngine, SessionOutputRecord, SessionSettings
from tests.session.synthetic import completion
from tinysoul.workspace import WorkspaceEngine, WorkspaceEngineBuilder, WorkspaceSettings
from tinysoul.workspace.errors import WorkspaceIOError


OLD_DAY = BusinessDay.parse("2026-07-11")
NEW_DAY = BusinessDay.parse("2026-07-12")
THIRD_DAY = BusinessDay.parse("2026-07-13")
ROLLOVER_TIME = datetime(
    2026,
    7,
    12,
    0,
    0,
    1,
    123456,
    tzinfo=ZoneInfo("Asia/Shanghai"),
)
SECOND_ROLLOVER_TIME = datetime(
    2026,
    7,
    13,
    0,
    0,
    1,
    123456,
    tzinfo=ZoneInfo("Asia/Shanghai"),
)


def test_daily_lifecycle_initializes_session_workspace_and_active_memory(
    tmp_path: Path,
) -> None:
    session, workspace, home, coordinator = _daily_system(tmp_path)
    home_manifest_before = _home_manifest_bytes(home)

    outcome = coordinator.ensure_active_day(NEW_DAY, now=ROLLOVER_TIME)

    assert outcome.active_day == NEW_DAY
    assert outcome.archives == ()
    assert session.active_day == NEW_DAY
    assert workspace.active_day == NEW_DAY
    assert (session.root / "Memory.md").is_file()
    assert _home_manifest_bytes(home) == home_manifest_before
    assert not (tmp_path / "archive").exists()


def test_daily_rollover_archives_session_workspace_and_trash_but_preserves_home(
    tmp_path: Path,
) -> None:
    session, workspace, home, coordinator = _daily_system(tmp_path)
    coordinator.ensure_active_day(OLD_DAY, now=ROLLOVER_TIME)
    session.record_turn(
        completion("turn_old"),
        output=SessionOutputRecord(text="old answer"),
        exhausted=False,
        day=OLD_DAY,
    )
    workspace.write_text("workspace:kept.md", "old workspace")
    workspace.write_text("workspace:discard.md", "discard")
    workspace.trash_resource(
        "workspace:discard.md",
        reason="explicit_delete",
        source_turn_id="turn_old",
    )
    home.write_resource(
        "home:skills/refactor/references/new.md",
        "runtime-only home resource",
    )
    home_manifest_before = _home_manifest_bytes(home)

    outcome = coordinator.ensure_active_day(NEW_DAY, now=ROLLOVER_TIME)

    assert len(outcome.archives) == 1
    archive = outcome.archives[0].root
    assert archive == tmp_path / "archive" / "20260712T000001.123456+0800"
    assert archive is not None
    assert (archive / "session" / "turns" / "turn_old.json").is_file()
    assert (archive / "workspace" / "kept.md").read_text(encoding="utf-8") == (
        "old workspace"
    )
    assert any((archive / "trash").rglob("*.json"))
    assert not (archive / "home").exists()
    transition = json.loads(
        (archive / "transition.json").read_text(encoding="utf-8")
    )
    assert transition["from_day"] == str(OLD_DAY)
    assert transition["to_day"] == str(NEW_DAY)
    assert "settlement_status" not in transition
    assert transition["completed_steps"] == [
        "session_archived",
        "workspace_archived",
        "active_initialized",
    ]

    assert session.active_day == NEW_DAY
    assert session.revision == 0
    assert workspace.active_day == NEW_DAY
    assert workspace.load_manifest().resources == ()
    assert (
        home.runtime_root / "skills" / "refactor" / "references" / "new.md"
    ).read_text(encoding="utf-8") == "runtime-only home resource"
    assert _home_manifest_bytes(home) == home_manifest_before
    assert coordinator.session_archive_for(OLD_DAY) == archive / "session"
    assert coordinator.session_archive_for(NEW_DAY) is None
    assert not tuple((tmp_path / "archive").glob(".pending-*"))


def test_daily_transition_observations_report_bounded_terminal_facts(
    tmp_path: Path,
) -> None:
    observations = _RecordingObservations()
    _, workspace, _, coordinator = _daily_system(
        tmp_path,
        observations=observations,
    )
    scope = RunScope().push(RunLevel.MODULE, "daily_lifecycle")
    coordinator.ensure_active_day(OLD_DAY, now=ROLLOVER_TIME, scope=scope)
    workspace.write_text("workspace:private.md", "private workspace body")

    coordinator.ensure_active_day(NEW_DAY, now=ROLLOVER_TIME, scope=scope)

    assert [event.name for event in observations.events] == [
        "daily.transition.started",
        "daily.transition.completed",
    ]
    assert [event.level for event in observations.events] == [
        ObservationLevel.VERBOSE,
        ObservationLevel.NORMAL,
    ]
    completed = observations.events[-1]
    assert completed.scope == scope
    assert completed.payload["from_day"] == str(OLD_DAY)
    assert completed.payload["to_day"] == str(NEW_DAY)
    assert "private workspace body" not in repr(observations.events)
    assert str(tmp_path) not in repr(observations.events)


def test_daily_rollover_resume_does_not_touch_home(
    tmp_path: Path,
) -> None:
    session, workspace, home, _ = _daily_system(tmp_path)
    failing_workspace = _FailAfterArchiveWorkspace(workspace)
    coordinator = DailyLifecycleCoordinator(
        archive_root=tmp_path / "archive",
        session=session,
        workspace=failing_workspace,
        memory=_memory(tmp_path, session),
    )
    coordinator.ensure_active_day(OLD_DAY, now=ROLLOVER_TIME)
    workspace.write_text("workspace:old.md", "old")
    home.write_resource("home:skills/refactor/notes.md", "keep home")
    home_manifest_before = _home_manifest_bytes(home)

    with pytest.raises(LoopInvariantError, match="WorkspaceIOError"):
        coordinator.ensure_active_day(NEW_DAY, now=ROLLOVER_TIME)

    pending = tuple((tmp_path / "archive").glob(".pending-*"))
    assert len(pending) == 1
    assert (pending[0] / "workspace" / "old.md").is_file()
    assert workspace.active_day is None
    assert home.read_resource("home:skills/refactor/notes.md").text == "keep home"
    assert _home_manifest_bytes(home) == home_manifest_before

    resumed = DailyLifecycleCoordinator(
        archive_root=tmp_path / "archive",
        session=session,
        workspace=workspace,
        memory=_memory(tmp_path, session),
    ).ensure_active_day(NEW_DAY, now=ROLLOVER_TIME)

    assert resumed.resumed is True
    assert len(resumed.archives) == 1
    assert (resumed.archives[0].root / "workspace" / "old.md").is_file()
    assert not (resumed.archives[0].root / "home").exists()
    assert session.active_day == NEW_DAY
    assert workspace.active_day == NEW_DAY
    assert home.read_resource("home:skills/refactor/notes.md").text == "keep home"
    assert _home_manifest_bytes(home) == home_manifest_before


def test_daily_initial_journal_failure_discards_empty_pending_and_keeps_old_day(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, workspace, home, coordinator = _daily_system(tmp_path)
    coordinator.ensure_active_day(OLD_DAY, now=ROLLOVER_TIME)
    marker, protected_before = _protected_state(tmp_path, home)
    original_write = daily_module.atomic_write_text

    def fail_initial_journal(path: Path, text: str, *, encoding: str = "utf-8") -> None:
        raise OSError("injected initial journal failure")

    monkeypatch.setattr(daily_module, "atomic_write_text", fail_initial_journal)
    with pytest.raises(LoopInvariantError, match="journal"):
        coordinator.ensure_active_day(NEW_DAY, now=ROLLOVER_TIME)

    assert session.active_day == OLD_DAY
    assert workspace.active_day == OLD_DAY
    assert not tuple((tmp_path / "archive").glob(".pending-*"))
    _assert_protected_state(home, marker, protected_before)

    monkeypatch.setattr(daily_module, "atomic_write_text", original_write)
    assert coordinator.ensure_active_day(NEW_DAY, now=ROLLOVER_TIME).archives


def test_daily_resumes_session_move_when_step_journal_write_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, workspace, home, coordinator = _daily_system(tmp_path)
    coordinator.ensure_active_day(OLD_DAY, now=ROLLOVER_TIME)
    session.record_turn(
        completion("turn_session_window"),
        output=SessionOutputRecord(text="saved"),
        exhausted=False,
        day=OLD_DAY,
    )
    marker, protected_before = _protected_state(tmp_path, home)
    original_write = daily_module.atomic_write_text
    writes = 0

    def fail_second_journal(path: Path, text: str, *, encoding: str = "utf-8") -> None:
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("injected session step journal failure")
        original_write(path, text, encoding=encoding)

    monkeypatch.setattr(daily_module, "atomic_write_text", fail_second_journal)
    with pytest.raises(LoopInvariantError, match="journal"):
        coordinator.ensure_active_day(NEW_DAY, now=ROLLOVER_TIME)

    pending = _only_pending(tmp_path)
    assert (pending / "session" / "turns" / "turn_session_window.json").is_file()
    assert session.active_day is None
    assert workspace.active_day == OLD_DAY
    _assert_protected_state(home, marker, protected_before)

    monkeypatch.setattr(daily_module, "atomic_write_text", original_write)
    resumed = coordinator.ensure_active_day(NEW_DAY, now=ROLLOVER_TIME)
    assert resumed.resumed is True
    assert resumed.archives
    assert session.active_day == NEW_DAY
    assert workspace.active_day == NEW_DAY
    _assert_protected_state(home, marker, protected_before)


def test_daily_resumes_after_trash_move_before_workspace_move(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, workspace, home, coordinator = _daily_system(tmp_path)
    coordinator.ensure_active_day(OLD_DAY, now=ROLLOVER_TIME)
    workspace.write_text("workspace:trash-window.md", "trash me")
    workspace.trash_resource(
        "workspace:trash-window.md",
        reason="explicit_delete",
        source_turn_id="turn_trash_window",
    )
    workspace.write_text("workspace:keep-window.md", "keep me")
    marker, protected_before = _protected_state(tmp_path, home)
    original_replace = workspace_engine_module.os.replace
    failed = False

    def fail_workspace_move(source: Path, target: Path) -> None:
        nonlocal failed
        if not failed and Path(source).resolve() == workspace.root.resolve():
            failed = True
            raise OSError("injected workspace move failure")
        original_replace(source, target)

    monkeypatch.setattr(workspace_engine_module.os, "replace", fail_workspace_move)
    with pytest.raises(LoopInvariantError, match="Workspace"):
        coordinator.ensure_active_day(NEW_DAY, now=ROLLOVER_TIME)

    pending = _only_pending(tmp_path)
    assert (pending / "trash").is_dir()
    assert not (workspace.root / ".tinysoul" / "trash").exists()
    assert (workspace.root / "keep-window.md").is_file()
    _assert_protected_state(home, marker, protected_before)

    monkeypatch.setattr(workspace_engine_module.os, "replace", original_replace)
    resumed = coordinator.ensure_active_day(NEW_DAY, now=ROLLOVER_TIME)
    assert resumed.resumed is True
    assert resumed.archives
    assert (resumed.archives[0].root / "workspace" / "keep-window.md").is_file()
    assert (resumed.archives[0].root / "trash").is_dir()
    _assert_protected_state(home, marker, protected_before)


def test_daily_resumes_after_active_init_before_step_journal_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, workspace, home, coordinator = _daily_system(tmp_path)
    coordinator.ensure_active_day(OLD_DAY, now=ROLLOVER_TIME)
    marker, protected_before = _protected_state(tmp_path, home)
    original_write = daily_module.atomic_write_text
    writes = 0

    def fail_active_step(path: Path, text: str, *, encoding: str = "utf-8") -> None:
        nonlocal writes
        writes += 1
        if writes == 4:
            raise OSError("injected active init journal failure")
        original_write(path, text, encoding=encoding)

    monkeypatch.setattr(daily_module, "atomic_write_text", fail_active_step)
    with pytest.raises(LoopInvariantError, match="journal"):
        coordinator.ensure_active_day(NEW_DAY, now=ROLLOVER_TIME)

    assert session.active_day == NEW_DAY
    assert workspace.active_day == NEW_DAY
    assert _only_pending(tmp_path).is_dir()
    _assert_protected_state(home, marker, protected_before)

    monkeypatch.setattr(daily_module, "atomic_write_text", original_write)
    resumed = coordinator.ensure_active_day(NEW_DAY, now=ROLLOVER_TIME)
    assert resumed.resumed is True
    assert resumed.archives
    _assert_protected_state(home, marker, protected_before)


def test_daily_resumes_final_archive_rename_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = _RecordingObservations()
    session, workspace, home, coordinator = _daily_system(
        tmp_path,
        observations=observations,
    )
    coordinator.ensure_active_day(OLD_DAY, now=ROLLOVER_TIME)
    marker, protected_before = _protected_state(tmp_path, home)
    original_replace = daily_module.os.replace
    failed = False

    def fail_final_replace(source: Path, target: Path) -> None:
        nonlocal failed
        if not failed and Path(source).name.startswith(".pending-"):
            failed = True
            raise OSError("injected final archive rename failure")
        original_replace(source, target)

    monkeypatch.setattr(daily_module.os, "replace", fail_final_replace)
    with pytest.raises(LoopInvariantError, match="finalize"):
        coordinator.ensure_active_day(NEW_DAY, now=ROLLOVER_TIME)

    pending = _only_pending(tmp_path)
    transition = json.loads((pending / "transition.json").read_text(encoding="utf-8"))
    assert transition["completed_steps"] == [
        "session_archived",
        "workspace_archived",
        "active_initialized",
    ]
    assert session.active_day == NEW_DAY
    assert workspace.active_day == NEW_DAY
    _assert_protected_state(home, marker, protected_before)
    assert [event.name for event in observations.events] == [
        "daily.transition.started",
        "daily.transition.failed",
    ]

    monkeypatch.setattr(daily_module.os, "replace", original_replace)
    resumed = coordinator.ensure_active_day(NEW_DAY, now=ROLLOVER_TIME)
    assert resumed.resumed is True
    assert resumed.archives
    assert [event.name for event in observations.events[-2:]] == [
        "daily.transition.started",
        "daily.transition.recovered",
    ]
    assert observations.events[-1].level is ObservationLevel.NORMAL
    _assert_protected_state(home, marker, protected_before)


def test_daily_recovers_pending_then_rolls_forward_again_for_current_day(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, workspace, home, coordinator = _daily_system(tmp_path)
    coordinator.ensure_active_day(OLD_DAY, now=ROLLOVER_TIME)
    marker, protected_before = _protected_state(tmp_path, home)
    original_write = daily_module.atomic_write_text
    writes = 0

    def fail_session_step(path: Path, text: str, *, encoding: str = "utf-8") -> None:
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("injected old pending transition")
        original_write(path, text, encoding=encoding)

    monkeypatch.setattr(daily_module, "atomic_write_text", fail_session_step)
    with pytest.raises(LoopInvariantError):
        coordinator.ensure_active_day(NEW_DAY, now=ROLLOVER_TIME)

    monkeypatch.setattr(daily_module, "atomic_write_text", original_write)
    outcome = coordinator.ensure_active_day(THIRD_DAY, now=SECOND_ROLLOVER_TIME)

    archives = tuple(
        path
        for path in (tmp_path / "archive").iterdir()
        if path.is_dir() and not path.name.startswith(".pending-")
    )
    assert len(archives) == 2
    assert outcome.active_day == THIRD_DAY
    assert tuple(item.day for item in outcome.archives) == (OLD_DAY, NEW_DAY)
    assert session.active_day == THIRD_DAY
    assert workspace.active_day == THIRD_DAY
    assert not tuple((tmp_path / "archive").glob(".pending-*"))
    _assert_protected_state(home, marker, protected_before)


def test_finalized_legacy_transition_is_rejected(
    tmp_path: Path,
) -> None:
    _, _, _, coordinator = _daily_system(tmp_path)
    coordinator.ensure_active_day(OLD_DAY, now=ROLLOVER_TIME)
    outcome = coordinator.ensure_active_day(NEW_DAY, now=ROLLOVER_TIME)
    assert outcome.archives
    transition_path = outcome.archives[0].root / "transition.json"
    transition = json.loads(transition_path.read_text(encoding="utf-8"))
    transition["completed_steps"].insert(2, "home_archived")
    transition["settlement_status"] = "pending"
    transition_path.write_text(
        json.dumps(transition, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(LoopInvariantError, match="journal fields are invalid"):
        coordinator.session_archive_for(OLD_DAY)


def test_pending_transition_with_home_requires_manual_recovery(
    tmp_path: Path,
) -> None:
    _, _, home, coordinator = _daily_system(tmp_path)
    coordinator.ensure_active_day(OLD_DAY, now=ROLLOVER_TIME)
    pending = tmp_path / "archive" / ".pending-daily_legacy"
    pending_home = pending / "home"
    pending_home.mkdir(parents=True)
    (pending_home / "legacy.md").write_text("preserve", encoding="utf-8")
    (pending / "transition.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "operation_id": "daily_legacy",
                "from_day": str(OLD_DAY),
                "to_day": str(NEW_DAY),
                "archive_name": "20260712T000001.123456+0800",
                "started_at": ROLLOVER_TIME.isoformat(),
                "completed_steps": ["session_archived"],
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    home_manifest_before = _home_manifest_bytes(home)

    with pytest.raises(LoopInvariantError, match="manual recovery"):
        coordinator.ensure_active_day(NEW_DAY, now=ROLLOVER_TIME)

    assert (pending_home / "legacy.md").read_text(encoding="utf-8") == "preserve"
    assert _home_manifest_bytes(home) == home_manifest_before


def test_legacy_untagged_workspace_inherits_session_day_without_moving_home(
    tmp_path: Path,
) -> None:
    session, workspace, home, coordinator = _daily_system(tmp_path)
    session.initialize_day(OLD_DAY)
    legacy_workspace = workspace.root / "legacy.md"
    legacy_workspace.parent.mkdir(parents=True, exist_ok=True)
    legacy_workspace.write_text("legacy workspace", encoding="utf-8")
    legacy_home = home.runtime_root / "skills" / "legacy" / "notes.txt"
    legacy_home.parent.mkdir(parents=True, exist_ok=True)
    legacy_home.write_text("legacy home", encoding="utf-8")

    outcome = coordinator.ensure_active_day(NEW_DAY, now=ROLLOVER_TIME)

    assert outcome.archives
    assert (outcome.archives[0].root / "workspace" / "legacy.md").is_file()
    assert not (outcome.archives[0].root / "home").exists()
    assert legacy_home.read_text(encoding="utf-8") == "legacy home"
    home.reconcile()
    assert home.read_resource("home:skills/legacy/notes.txt").text == "legacy home"
    transition = json.loads(
        (outcome.archives[0].root / "transition.json").read_text(encoding="utf-8")
    )
    assert transition["from_day"] == str(OLD_DAY)


def test_daily_lifecycle_rejects_overlapping_archive_before_initialization(
    tmp_path: Path,
) -> None:
    session, workspace, home, _ = _daily_system(tmp_path)
    home_manifest_before = _home_manifest_bytes(home)
    coordinator = DailyLifecycleCoordinator(
        archive_root=tmp_path / "runtime",
        session=session,
        workspace=workspace,
        memory=_memory(tmp_path, session),
    )

    with pytest.raises(LoopContractError, match="overlaps"):
        coordinator.ensure_active_day(NEW_DAY, now=ROLLOVER_TIME)

    assert session.active_day is None
    assert workspace.active_day is None
    assert _home_manifest_bytes(home) == home_manifest_before


@dataclass
class _FailAfterArchiveWorkspace:
    engine: WorkspaceEngine
    failed: bool = False

    @property
    def root(self) -> Path:
        return self.engine.root

    @property
    def active_day(self) -> BusinessDay | None:
        return self.engine.active_day

    def initialize_day(self, day: BusinessDay) -> object:
        return self.engine.initialize_day(day)

    def archive_day(
        self,
        day: BusinessDay,
        *,
        workspace_target: Path,
        trash_target: Path,
    ) -> None:
        self.engine.archive_day(
            day,
            workspace_target=workspace_target,
            trash_target=trash_target,
        )
        if not self.failed:
            self.failed = True
            raise WorkspaceIOError("injected Workspace failure after archive")


def _daily_system(
    root: Path,
    *,
    observations: ObservationEmitter | None = None,
) -> tuple[
    SessionEngine,
    WorkspaceEngine,
    AgentHomeEngine,
    DailyLifecycleCoordinator,
]:
    original_home = root / "home"
    core = original_home / "agent" / "AGENT.md"
    core.parent.mkdir(parents=True)
    core.write_text("core", encoding="utf-8")
    session = SessionEngine(SessionSettings(root=root / "runtime" / "session"))
    workspace = WorkspaceEngineBuilder(
        WorkspaceSettings(root=root / "runtime" / "workspace")
    ).build()
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=original_home,
            runtime_root=root / "runtime" / "home",
        )
    ).build()
    coordinator = DailyLifecycleCoordinator(
        archive_root=root / "archive",
        session=session,
        workspace=workspace,
        memory=_memory(root, session),
        observations=observations,
    )
    return session, workspace, home, coordinator


def _home_manifest_bytes(home: AgentHomeEngine) -> bytes:
    return (
        home.runtime_root / ".tinysoul" / "home_overlay.json"
    ).read_bytes()


def _memory(root: Path, session: SessionEngine) -> MemoryEngine:
    return MemoryEngine(
        settings=MemorySettings(root=root / "memory"),
        active_session_root=session.root,
    )


def _protected_state(
    root: Path,
    home: AgentHomeEngine,
) -> tuple[Path, tuple[bytes, bytes]]:
    marker = root / "memory" / ".tinysoul" / "lifecycle-probe"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("memory must stay unchanged", encoding="utf-8")
    return marker, (_home_manifest_bytes(home), marker.read_bytes())


def _assert_protected_state(
    home: AgentHomeEngine,
    marker: Path,
    expected: tuple[bytes, bytes],
) -> None:
    assert (_home_manifest_bytes(home), marker.read_bytes()) == expected


def _only_pending(root: Path) -> Path:
    pending = tuple((root / "archive").glob(".pending-*"))
    assert len(pending) == 1
    return pending[0]


@dataclass
class _RecordingObservations:
    events: list[ObservationEvent] = field(default_factory=list)

    def enabled(self, level: ObservationLevel) -> bool:
        return True

    def emit(self, event: ObservationEvent) -> None:
        self.events.append(event)
