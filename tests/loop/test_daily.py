from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tinysoul.context import TurnSummary
from tinysoul.home import AgentHomeEngine, AgentHomeEngineBuilder, AgentHomeSettings
from tinysoul.loop import BusinessDay, DailyLifecycleCoordinator
from tinysoul.loop.errors import LoopContractError, LoopInvariantError
from tinysoul.session import SessionEngine, SessionSettings
from tinysoul.workspace import WorkspaceEngine, WorkspaceEngineBuilder, WorkspaceSettings
from tinysoul.workspace.errors import WorkspaceIOError


OLD_DAY = BusinessDay.parse("2026-07-11")
NEW_DAY = BusinessDay.parse("2026-07-12")
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


def test_daily_lifecycle_initializes_session_and_workspace_only(
    tmp_path: Path,
) -> None:
    session, workspace, home, coordinator = _daily_system(tmp_path)
    home_manifest_before = _home_manifest_bytes(home)

    outcome = coordinator.ensure_active_day(NEW_DAY, now=ROLLOVER_TIME)

    assert outcome.active_day == NEW_DAY
    assert outcome.archive_path is None
    assert session.active_day == NEW_DAY
    assert workspace.active_day == NEW_DAY
    assert _home_manifest_bytes(home) == home_manifest_before
    assert not (tmp_path / "archive").exists()


def test_daily_rollover_archives_session_workspace_and_trash_but_preserves_home(
    tmp_path: Path,
) -> None:
    session, workspace, home, coordinator = _daily_system(tmp_path)
    coordinator.ensure_active_day(OLD_DAY, now=ROLLOVER_TIME)
    session.record_turn(
        summary=TurnSummary(turn_id="turn_old"),
        output={"text": "old answer"},
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
        "home:how/refactor/references/new.md",
        "runtime-only home resource",
    )
    home_manifest_before = _home_manifest_bytes(home)

    outcome = coordinator.ensure_active_day(NEW_DAY, now=ROLLOVER_TIME)

    archive = outcome.archive_path
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
        home.runtime_root / "how" / "refactor" / "references" / "new.md"
    ).read_text(encoding="utf-8") == "runtime-only home resource"
    assert _home_manifest_bytes(home) == home_manifest_before
    assert coordinator.session_archive_for(OLD_DAY) == archive / "session"
    assert coordinator.session_archive_for(NEW_DAY) is None
    assert not tuple((tmp_path / "archive").glob(".pending-*"))


def test_daily_rollover_resume_does_not_touch_home(
    tmp_path: Path,
) -> None:
    session, workspace, home, _ = _daily_system(tmp_path)
    failing_workspace = _FailAfterArchiveWorkspace(workspace)
    coordinator = DailyLifecycleCoordinator(
        archive_root=tmp_path / "archive",
        session=session,
        workspace=failing_workspace,
    )
    coordinator.ensure_active_day(OLD_DAY, now=ROLLOVER_TIME)
    workspace.write_text("workspace:old.md", "old")
    home.write_resource("home:how/refactor/notes.md", "keep home")
    home_manifest_before = _home_manifest_bytes(home)

    with pytest.raises(LoopInvariantError, match="injected Workspace failure"):
        coordinator.ensure_active_day(NEW_DAY, now=ROLLOVER_TIME)

    pending = tuple((tmp_path / "archive").glob(".pending-*"))
    assert len(pending) == 1
    assert (pending[0] / "workspace" / "old.md").is_file()
    assert workspace.active_day is None
    assert home.read_resource("home:how/refactor/notes.md").text == "keep home"
    assert _home_manifest_bytes(home) == home_manifest_before

    resumed = DailyLifecycleCoordinator(
        archive_root=tmp_path / "archive",
        session=session,
        workspace=workspace,
    ).ensure_active_day(NEW_DAY, now=ROLLOVER_TIME)

    assert resumed.resumed is True
    assert resumed.archive_path is not None
    assert (resumed.archive_path / "workspace" / "old.md").is_file()
    assert not (resumed.archive_path / "home").exists()
    assert session.active_day == NEW_DAY
    assert workspace.active_day == NEW_DAY
    assert home.read_resource("home:how/refactor/notes.md").text == "keep home"
    assert _home_manifest_bytes(home) == home_manifest_before


def test_finalized_legacy_transition_still_resolves_session_archive(
    tmp_path: Path,
) -> None:
    _, _, _, coordinator = _daily_system(tmp_path)
    coordinator.ensure_active_day(OLD_DAY, now=ROLLOVER_TIME)
    outcome = coordinator.ensure_active_day(NEW_DAY, now=ROLLOVER_TIME)
    assert outcome.archive_path is not None
    transition_path = outcome.archive_path / "transition.json"
    transition = json.loads(transition_path.read_text(encoding="utf-8"))
    transition["completed_steps"].insert(2, "home_archived")
    transition["settlement_status"] = "pending"
    transition_path.write_text(
        json.dumps(transition, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    assert coordinator.session_archive_for(OLD_DAY) == (
        outcome.archive_path / "session"
    )


def test_legacy_pending_transition_with_home_requires_manual_recovery(
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
                "completed_steps": ["session_archived", "home_archived"],
                "settlement_status": "pending",
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
    legacy_home = home.runtime_root / "how" / "legacy" / "notes.txt"
    legacy_home.parent.mkdir(parents=True, exist_ok=True)
    legacy_home.write_text("legacy home", encoding="utf-8")

    outcome = coordinator.ensure_active_day(NEW_DAY, now=ROLLOVER_TIME)

    assert outcome.archive_path is not None
    assert (outcome.archive_path / "workspace" / "legacy.md").is_file()
    assert not (outcome.archive_path / "home").exists()
    assert legacy_home.read_text(encoding="utf-8") == "legacy home"
    home.reconcile()
    assert home.read_resource("home:how/legacy/notes.txt").text == "legacy home"
    transition = json.loads(
        (outcome.archive_path / "transition.json").read_text(encoding="utf-8")
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
    )
    return session, workspace, home, coordinator


def _home_manifest_bytes(home: AgentHomeEngine) -> bytes:
    return (
        home.runtime_root / ".tinysoul" / "home_overlay.json"
    ).read_bytes()
