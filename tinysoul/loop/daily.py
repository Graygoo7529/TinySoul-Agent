"""Program-level deterministic daily rollover coordination."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
import json
import os
from pathlib import Path
import shutil
from threading import RLock
from typing import Protocol
from uuid import uuid4

from tinysoul.infra.filesystem import atomic_write_text
from tinysoul.infra.json import JsonObject, to_json_object

from .day import BusinessDay
from .errors import LoopContractError, LoopInvariantError


class DailyTransitionStep(StrEnum):
    SESSION_ARCHIVED = "session_archived"
    WORKSPACE_ARCHIVED = "workspace_archived"
    ACTIVE_INITIALIZED = "active_initialized"


@dataclass(frozen=True)
class DailyTransitionJournal:
    operation_id: str
    from_day: str
    to_day: str
    archive_name: str
    started_at: str
    completed_steps: tuple[DailyTransitionStep, ...] = field(default_factory=tuple)
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise LoopContractError("Daily journal schema_version must be 1")
        if not self.operation_id or not self.archive_name or not self.started_at:
            raise LoopContractError("Daily journal identity fields must be non-empty")
        BusinessDay.parse(self.from_day)
        BusinessDay.parse(self.to_day)
        steps = tuple(self.completed_steps)
        if len(steps) != len(set(steps)):
            raise LoopContractError("Daily journal steps must be unique")
        object.__setattr__(self, "completed_steps", steps)

    def completed(self, step: DailyTransitionStep) -> bool:
        return step in self.completed_steps

    def with_step(self, step: DailyTransitionStep) -> "DailyTransitionJournal":
        if self.completed(step):
            return self
        return replace(self, completed_steps=(*self.completed_steps, step))

    def to_json(self) -> JsonObject:
        return {
            "schema_version": self.schema_version,
            "operation_id": self.operation_id,
            "from_day": self.from_day,
            "to_day": self.to_day,
            "archive_name": self.archive_name,
            "started_at": self.started_at,
            "completed_steps": [step.value for step in self.completed_steps],
        }

    @classmethod
    def from_json(cls, value: JsonObject) -> "DailyTransitionJournal":
        steps_value = value.get("completed_steps", [])
        if not isinstance(steps_value, list):
            raise LoopContractError("Daily journal completed_steps must be a list")
        try:
            steps = tuple(
                DailyTransitionStep(item)
                for item in steps_value
                if item != "home_archived"
            )
        except (TypeError, ValueError) as exc:
            raise LoopContractError("Daily journal contains an unknown step") from exc
        return cls(
            schema_version=_required_int(value, "schema_version"),
            operation_id=_required_str(value, "operation_id"),
            from_day=_required_str(value, "from_day"),
            to_day=_required_str(value, "to_day"),
            archive_name=_required_str(value, "archive_name"),
            started_at=_required_str(value, "started_at"),
            completed_steps=steps,
        )


@dataclass(frozen=True)
class DailyTransitionOutcome:
    active_day: BusinessDay
    archive_path: Path | None = None
    resumed: bool = False


class SessionDailyLifecycle(Protocol):
    @property
    def root(self) -> Path:
        ...

    @property
    def active_day(self) -> BusinessDay | None:
        ...

    def initialize_day(self, day: BusinessDay) -> None:
        ...

    def archive_day(self, day: BusinessDay, *, target: Path) -> None:
        ...

    def reconcile_active(self) -> object:
        ...


class WorkspaceDailyLifecycle(Protocol):
    @property
    def root(self) -> Path:
        ...

    @property
    def active_day(self) -> BusinessDay | None:
        ...

    def initialize_day(self, day: BusinessDay) -> object:
        ...

    def archive_day(
        self,
        day: BusinessDay,
        *,
        workspace_target: Path,
        trash_target: Path,
    ) -> None:
        ...


class DailyLifecycleCoordinator:
    """Archive Session and Workspace facts before opening the next day."""

    def __init__(
        self,
        *,
        archive_root: Path,
        session: SessionDailyLifecycle,
        workspace: WorkspaceDailyLifecycle,
    ) -> None:
        self._archive_root = archive_root
        self._session = session
        self._workspace = workspace
        self._lock = RLock()

    def ensure_active_day(
        self,
        target_day: BusinessDay,
        *,
        now: datetime,
    ) -> DailyTransitionOutcome:
        with self._lock:
            if not isinstance(target_day, BusinessDay):
                raise LoopContractError("Daily target must be a BusinessDay")
            if not isinstance(now, datetime) or now.tzinfo is None:
                raise LoopContractError(
                    "Daily rollover timestamp must be timezone-aware"
                )
            try:
                self._validate_layout()
                pending = self._pending_directory()
                if pending is not None:
                    journal = self._load_journal(pending)
                    archive = self._resume(pending, journal)
                    active = BusinessDay.parse(journal.to_day)
                    if active != target_day:
                        return self.ensure_active_day(target_day, now=now)
                    return DailyTransitionOutcome(
                        active_day=target_day,
                        archive_path=archive,
                        resumed=True,
                    )

                active = self._claim_active_day(target_day)
                if active == target_day:
                    self._initialize_all(target_day)
                    return DailyTransitionOutcome(active_day=target_day)
                if active > target_day:
                    raise LoopInvariantError(
                        f"Business clock moved behind active day {active}: {target_day}"
                    )
                pending, journal = self._start(active, target_day, now=now)
                archive = self._resume(pending, journal)
                return DailyTransitionOutcome(
                    active_day=target_day,
                    archive_path=archive,
                )
            except LoopContractError:
                raise
            except LoopInvariantError:
                raise
            except Exception as exc:
                raise LoopInvariantError(f"Daily rollover failed: {exc}") from exc

    def session_archive_for(self, day: BusinessDay) -> Path | None:
        """Resolve one finalized Session archive without reading Session internals."""

        with self._lock:
            if not isinstance(day, BusinessDay):
                raise LoopContractError("Session archive day must be a BusinessDay")
            if not self._archive_root.exists():
                return None
            matches: list[Path] = []
            for directory in sorted(
                self._archive_root.iterdir(),
                key=lambda path: path.name,
            ):
                if not directory.is_dir() or directory.name.startswith(".pending-"):
                    continue
                journal_path = directory / "transition.json"
                if not journal_path.is_file():
                    continue
                journal = self._load_journal(directory)
                if journal.archive_name != directory.name:
                    raise LoopInvariantError(
                        "Daily archive directory identity does not match its journal"
                    )
                if journal.from_day != str(day):
                    continue
                session_root = directory / "session"
                if not session_root.is_dir():
                    raise LoopInvariantError(
                        f"Daily archive is missing Session facts: {directory}"
                    )
                matches.append(session_root)
            if len(matches) > 1:
                raise LoopInvariantError(
                    f"Multiple Session archives exist for Business Day {day}"
                )
            return matches[0] if matches else None

    def _validate_layout(self) -> None:
        roots = {
            "Session": self._session.root.resolve(),
            "Workspace": self._workspace.root.resolve(),
        }
        archive = self._archive_root.resolve()
        for name, root in roots.items():
            if _paths_overlap(archive, root):
                raise LoopContractError(
                    f"Daily archive root overlaps {name} root: {root}"
                )
        items = tuple(roots.items())
        for index, (left_name, left) in enumerate(items):
            for right_name, right in items[index + 1 :]:
                if _paths_overlap(left, right):
                    raise LoopContractError(
                        f"Daily roots overlap: {left_name} and {right_name}"
                    )

    def _claim_active_day(self, target_day: BusinessDay) -> BusinessDay:
        session_day = self._session.active_day
        tagged = {
            day
            for day in (
                session_day,
                self._workspace.active_day,
            )
            if day is not None
        }
        if len(tagged) > 1:
            raise LoopInvariantError("Session and Workspace active days disagree")
        inherited = session_day or (next(iter(tagged)) if tagged else target_day)
        self._initialize_all(inherited)
        return inherited

    def _initialize_all(self, day: BusinessDay) -> None:
        self._session.initialize_day(day)
        self._workspace.initialize_day(day)
        days = {
            self._session.active_day,
            self._workspace.active_day,
        }
        if days != {day}:
            raise LoopInvariantError(
                "Daily participants did not initialize the same active day"
            )

    def _start(
        self,
        from_day: BusinessDay,
        to_day: BusinessDay,
        *,
        now: datetime,
    ) -> tuple[Path, DailyTransitionJournal]:
        self._archive_root.mkdir(parents=True, exist_ok=True)
        archive_name = now.strftime("%Y%m%dT%H%M%S.%f%z")
        if (self._archive_root / archive_name).exists():
            raise LoopInvariantError(
                f"Daily archive timestamp already exists: {archive_name}"
            )
        operation_id = f"daily_{uuid4().hex[:16]}"
        pending = self._archive_root / f".pending-{operation_id}"
        pending.mkdir(parents=False, exist_ok=False)
        journal = DailyTransitionJournal(
            operation_id=operation_id,
            from_day=str(from_day),
            to_day=str(to_day),
            archive_name=archive_name,
            started_at=now.isoformat(),
        )
        try:
            self._save_journal(pending, journal)
        except Exception:
            shutil.rmtree(pending, ignore_errors=True)
            raise
        return pending, journal

    def _resume(
        self,
        pending: Path,
        journal: DailyTransitionJournal,
    ) -> Path:
        from_day = BusinessDay.parse(journal.from_day)
        to_day = BusinessDay.parse(journal.to_day)
        if (pending / "home").exists():
            raise LoopInvariantError(
                "Legacy pending Daily transition already contains Home; "
                "manual recovery is required"
            )

        if not journal.completed(DailyTransitionStep.SESSION_ARCHIVED):
            if (pending / "session").exists() and self._session.active_day is None:
                pass
            else:
                self._session.reconcile_active()
                self._session.archive_day(from_day, target=pending / "session")
            journal = journal.with_step(DailyTransitionStep.SESSION_ARCHIVED)
            self._save_journal(pending, journal)

        if not journal.completed(DailyTransitionStep.WORKSPACE_ARCHIVED):
            if (
                (pending / "workspace").exists()
                and (pending / "trash").exists()
                and self._workspace.active_day is None
            ):
                pass
            else:
                self._workspace.archive_day(
                    from_day,
                    workspace_target=pending / "workspace",
                    trash_target=pending / "trash",
                )
            journal = journal.with_step(DailyTransitionStep.WORKSPACE_ARCHIVED)
            self._save_journal(pending, journal)

        if not journal.completed(DailyTransitionStep.ACTIVE_INITIALIZED):
            self._initialize_all(to_day)
            journal = journal.with_step(DailyTransitionStep.ACTIVE_INITIALIZED)
            self._save_journal(pending, journal)

        archive = self._archive_root / journal.archive_name
        if archive.exists():
            raise LoopInvariantError(f"Daily archive already exists: {archive}")
        try:
            os.replace(pending, archive)
        except OSError as exc:
            raise LoopInvariantError(f"Failed to finalize Daily archive: {exc}") from exc
        return archive

    def _pending_directory(self) -> Path | None:
        if not self._archive_root.exists():
            return None
        pending = tuple(
            path
            for path in self._archive_root.iterdir()
            if path.is_dir() and path.name.startswith(".pending-")
        )
        for path in pending:
            if not (path / "transition.json").exists():
                participant_names = {"session", "workspace", "home", "trash"}
                if any((path / name).exists() for name in participant_names):
                    raise LoopInvariantError(
                        "Pending Daily transition has participant data but no journal"
                    )
                try:
                    shutil.rmtree(path)
                except OSError as exc:
                    raise LoopInvariantError(
                        f"Failed to discard unstarted Daily transition: {exc}"
                    ) from exc
        pending = tuple(path for path in pending if path.exists())
        if len(pending) > 1:
            raise LoopInvariantError("Multiple pending Daily transitions exist")
        return pending[0] if pending else None

    @staticmethod
    def _load_journal(pending: Path) -> DailyTransitionJournal:
        path = pending / "transition.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LoopInvariantError(f"Failed to read Daily journal: {exc}") from exc
        if not isinstance(value, dict):
            raise LoopInvariantError("Daily journal root must be an object")
        try:
            return DailyTransitionJournal.from_json(to_json_object(value))
        except LoopContractError as exc:
            raise LoopInvariantError(
                f"Persisted Daily journal is invalid: {exc}"
            ) from exc

    @staticmethod
    def _save_journal(pending: Path, journal: DailyTransitionJournal) -> None:
        try:
            atomic_write_text(
                pending / "transition.json",
                json.dumps(
                    journal.to_json(),
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                )
                + "\n",
            )
        except OSError as exc:
            raise LoopInvariantError(f"Failed to write Daily journal: {exc}") from exc


def _required_str(value: JsonObject, name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item:
        raise LoopContractError(f"Daily journal field must be text: {name}")
    return item


def _required_int(value: JsonObject, name: str) -> int:
    item = value.get(name)
    if isinstance(item, bool) or not isinstance(item, int):
        raise LoopContractError(f"Daily journal field must be int: {name}")
    return item


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents
