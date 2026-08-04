"""Deterministic daily rollover coordination and archive catalog."""

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

from tinysoul.infra.filesystem import atomic_write_text, read_text_prefix
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.infra.time import BusinessDay, BusinessDayError
from tinysoul.runtime import (
    NullObservationEmitter,
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    RunScope,
    emit_observation,
    observation_enabled,
)
from tinysoul.session import SessionIOError, SessionInvariantError
from tinysoul.workspace import WorkspaceIOError, WorkspaceInvariantError

from ..errors import MaintenanceContractError, MaintenanceInvariantError


_CATALOG_SCHEMA_VERSION = 1
_CATALOG_FIELDS = {"schema_version", "entries"}
_CATALOG_ENTRY_FIELDS = {"day", "archive_name"}
_MAX_CATALOG_CHARS = 4 * 1024 * 1024


@dataclass(frozen=True)
class ArchiveProjection:
    """Owner-neutral roots for one finalized Business Day archive."""

    day: BusinessDay
    root: Path
    session_root: Path
    workspace_root: Path

    def __post_init__(self) -> None:
        if not isinstance(self.day, BusinessDay):
            raise MaintenanceContractError("Archive projection day is invalid")
        for name in ("root", "session_root", "workspace_root"):
            value = getattr(self, name)
            if not isinstance(value, Path) or not value.is_absolute():
                raise MaintenanceContractError(
                    f"Archive projection {name} must be an absolute path"
                )


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
            raise MaintenanceContractError("Daily journal schema_version must be 1")
        if not self.operation_id or not self.archive_name or not self.started_at:
            raise MaintenanceContractError("Daily journal identity fields must be non-empty")
        try:
            BusinessDay.parse(self.from_day)
            BusinessDay.parse(self.to_day)
        except BusinessDayError as exc:
            raise MaintenanceContractError("Daily journal contains an invalid day") from exc
        steps = tuple(self.completed_steps)
        if len(steps) != len(set(steps)):
            raise MaintenanceContractError("Daily journal steps must be unique")
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
        expected_fields = {
            "schema_version",
            "operation_id",
            "from_day",
            "to_day",
            "archive_name",
            "started_at",
            "completed_steps",
        }
        if set(value) != expected_fields:
            raise MaintenanceContractError("Daily journal fields are invalid")
        steps_value = value.get("completed_steps", [])
        if not isinstance(steps_value, list):
            raise MaintenanceContractError("Daily journal completed_steps must be a list")
        try:
            steps = tuple(DailyTransitionStep(item) for item in steps_value)
        except (TypeError, ValueError) as exc:
            raise MaintenanceContractError("Daily journal contains an unknown step") from exc
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
    archives: tuple[ArchiveProjection, ...] = field(default_factory=tuple)
    resumed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.active_day, BusinessDay):
            raise MaintenanceContractError("Daily transition active day is invalid")
        if any(not isinstance(item, ArchiveProjection) for item in self.archives):
            raise MaintenanceContractError("Daily transition archives are invalid")
        days = tuple(item.day for item in self.archives)
        if len(days) != len(set(days)):
            raise MaintenanceContractError("Daily transition archive days must be unique")
        if any(day >= self.active_day for day in days):
            raise MaintenanceContractError("Daily transition archived day must be closed")
        object.__setattr__(self, "archives", tuple(self.archives))


class ActiveDayLease:
    """Hold Daily rollover exclusion while accessing active-day modules."""

    def __init__(
        self,
        *,
        lock: RLock,
        session: SessionDailyLifecycle,
        workspace: WorkspaceDailyLifecycle,
    ) -> None:
        self._lock = lock
        self._session = session
        self._workspace = workspace
        self._entered = False

    def __enter__(self) -> BusinessDay:
        self._lock.acquire()
        self._entered = True
        session_day = self._session.active_day
        workspace_day = self._workspace.active_day
        if session_day is None or workspace_day is None:
            self._release()
            raise MaintenanceInvariantError("Daily active day is not initialized")
        if session_day != workspace_day:
            self._release()
            raise MaintenanceInvariantError("Session and Workspace active days disagree")
        return session_day

    def __exit__(
        self,
        exception_type: object,
        exception: object,
        traceback: object,
    ) -> None:
        self._release()

    def _release(self) -> None:
        if self._entered:
            self._entered = False
            self._lock.release()


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
        observations: ObservationEmitter | None = None,
    ) -> None:
        self._archive_root = archive_root
        self._session = session
        self._workspace = workspace
        self._observations = observations or NullObservationEmitter()
        self._lock = RLock()

    def active_day_lease(self) -> ActiveDayLease:
        """Exclude rollover while one caller reads or mutates active-day state."""

        return ActiveDayLease(
            lock=self._lock,
            session=self._session,
            workspace=self._workspace,
        )

    def ensure_active_day(
        self,
        target_day: BusinessDay,
        *,
        now: datetime,
        scope: RunScope | None = None,
    ) -> DailyTransitionOutcome:
        with self._lock:
            if not isinstance(target_day, BusinessDay):
                raise MaintenanceContractError("Daily target must be a BusinessDay")
            if not isinstance(now, datetime) or now.tzinfo is None:
                raise MaintenanceContractError(
                    "Daily rollover timestamp must be timezone-aware"
                )
            run_scope = scope or RunScope()
            try:
                return self._ensure_active_day_locked(
                    target_day,
                    now=now,
                    scope=run_scope,
                )
            except MaintenanceContractError as exc:
                self._emit_failed(run_scope, target_day, exc)
                raise
            except MaintenanceInvariantError as exc:
                self._emit_failed(run_scope, target_day, exc)
                raise
            except (
                OSError,
                SessionIOError,
                SessionInvariantError,
                WorkspaceIOError,
                WorkspaceInvariantError,
            ) as exc:
                self._emit_failed(run_scope, target_day, exc)
                raise MaintenanceInvariantError(
                    f"Daily rollover failed: {type(exc).__name__}"
                ) from exc

    def _ensure_active_day_locked(
        self,
        target_day: BusinessDay,
        *,
        now: datetime,
        scope: RunScope,
    ) -> DailyTransitionOutcome:
        self._validate_layout()
        pending = self._pending_directory()
        if pending is not None:
            journal = self._load_journal(pending)
            self._emit_transition(
                "daily.transition.started",
                ObservationLevel.VERBOSE,
                "Daily transition recovery started.",
                journal,
                scope=scope,
                resumed=True,
            )
            archive = self._resume(pending, journal)
            self._emit_transition(
                "daily.transition.recovered",
                ObservationLevel.NORMAL,
                "Daily transition recovered.",
                journal,
                scope=scope,
                resumed=True,
            )
            active = BusinessDay.parse(journal.to_day)
            recovered = self._projection_for_archive(
                BusinessDay.parse(journal.from_day),
                archive,
            )
            if active != target_day:
                following = self._ensure_active_day_locked(
                    target_day,
                    now=now,
                    scope=scope,
                )
                return DailyTransitionOutcome(
                    active_day=following.active_day,
                    archives=(recovered, *following.archives),
                    resumed=True,
                )
            return DailyTransitionOutcome(
                active_day=target_day,
                archives=(recovered,),
                resumed=True,
            )

        active = self._claim_active_day(target_day)
        if active == target_day:
            self._initialize_all(target_day)
            return DailyTransitionOutcome(active_day=target_day)
        if active > target_day:
            raise MaintenanceInvariantError(
                f"Business clock moved behind active day {active}: {target_day}"
            )
        pending, journal = self._start(active, target_day, now=now)
        self._emit_transition(
            "daily.transition.started",
            ObservationLevel.VERBOSE,
            "Daily transition started.",
            journal,
            scope=scope,
            resumed=False,
        )
        archive = self._resume(pending, journal)
        self._emit_transition(
            "daily.transition.completed",
            ObservationLevel.NORMAL,
            "Daily transition completed.",
            journal,
            scope=scope,
            resumed=False,
        )
        return DailyTransitionOutcome(
            active_day=target_day,
            archives=(self._projection_for_archive(active, archive),),
        )

    @staticmethod
    def _projection_for_archive(day: BusinessDay, archive: Path) -> ArchiveProjection:
        root = archive.resolve()
        session_root = root / "session"
        workspace_root = root / "workspace"
        if not session_root.is_dir() or not workspace_root.is_dir():
            raise MaintenanceInvariantError(
                "Daily archive is missing participant facts"
            )
        return ArchiveProjection(
            day=day,
            root=root,
            session_root=session_root.resolve(),
            workspace_root=workspace_root.resolve(),
        )

    def _emit_transition(
        self,
        name: str,
        level: ObservationLevel,
        message: str,
        journal: DailyTransitionJournal,
        *,
        scope: RunScope,
        resumed: bool,
    ) -> None:
        self._emit(
            name,
            level,
            message,
            scope=scope,
            payload={
                "operation_id": journal.operation_id,
                "from_day": journal.from_day,
                "to_day": journal.to_day,
                "archive_name": journal.archive_name,
                "resumed": resumed,
            },
        )

    def _emit_failed(
        self,
        scope: RunScope,
        target_day: BusinessDay,
        error: Exception,
    ) -> None:
        self._emit(
            "daily.transition.failed",
            ObservationLevel.NORMAL,
            "Daily transition failed.",
            scope=scope,
            payload={
                "target_day": str(target_day),
                "error_type": type(error).__name__,
            },
        )

    def _emit(
        self,
        name: str,
        level: ObservationLevel,
        message: str,
        *,
        scope: RunScope,
        payload: JsonObject,
    ) -> None:
        if not observation_enabled(self._observations, level):
            return
        emit_observation(
            self._observations,
            ObservationEvent(
                name=name,
                level=level,
                source="maintenance.archive",
                scope=scope,
                message=message,
                payload=payload,
            ),
        )

    def archive_for(self, day: BusinessDay) -> ArchiveProjection | None:
        """Resolve one finalized archive through the durable date index."""

        with self._lock:
            if not isinstance(day, BusinessDay):
                raise MaintenanceContractError("Archive day must be a BusinessDay")
            archive_name = self._load_catalog().get(day)
            if archive_name is None:
                return None
            archive = self._archive_root / archive_name
            if not archive.is_dir():
                raise MaintenanceInvariantError(
                    f"Archive catalog points to a missing directory: {archive_name}"
                )
            journal = self._load_journal(archive)
            if journal.archive_name != archive_name or journal.from_day != str(day):
                raise MaintenanceInvariantError(
                    "Archive catalog identity does not match its journal"
                )
            return self._projection_for_archive(day, archive)

    def session_archive_for(self, day: BusinessDay) -> Path | None:
        projection = self.archive_for(day)
        return projection.session_root if projection is not None else None

    def _load_catalog(self) -> dict[BusinessDay, str]:
        path = self._archive_root / "catalog.json"
        if not path.exists():
            return {}
        try:
            read = read_text_prefix(path, max_chars=_MAX_CATALOG_CHARS)
        except (OSError, UnicodeError) as exc:
            raise MaintenanceInvariantError(
                f"Failed to read Daily archive catalog: {type(exc).__name__}"
            ) from exc
        if read.truncated:
            raise MaintenanceInvariantError("Daily archive catalog is too large")
        try:
            raw = json.loads(read.text)
            value = to_json_object(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise MaintenanceInvariantError(
                "Daily archive catalog is not valid JSON"
            ) from exc
        if set(value) != _CATALOG_FIELDS:
            raise MaintenanceInvariantError("Daily archive catalog fields are invalid")
        if value.get("schema_version") != _CATALOG_SCHEMA_VERSION:
            raise MaintenanceInvariantError("Daily archive catalog schema is unsupported")
        entries = value.get("entries")
        if not isinstance(entries, list):
            raise MaintenanceInvariantError("Daily archive catalog entries are invalid")
        result: dict[BusinessDay, str] = {}
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != _CATALOG_ENTRY_FIELDS:
                raise MaintenanceInvariantError("Daily archive catalog entry is invalid")
            day_value = entry.get("day")
            archive_name = entry.get("archive_name")
            if not isinstance(day_value, str):
                raise MaintenanceInvariantError(
                    "Daily archive catalog entry day is invalid"
                )
            if (
                not isinstance(archive_name, str)
                or not archive_name
                or Path(archive_name).name != archive_name
                or archive_name.startswith(".")
            ):
                raise MaintenanceInvariantError(
                    "Daily archive catalog entry archive_name is invalid"
                )
            try:
                day = BusinessDay.parse(day_value)
            except (BusinessDayError, TypeError) as exc:
                raise MaintenanceInvariantError(
                    "Daily archive catalog entry day is invalid"
                ) from exc
            if day in result:
                raise MaintenanceInvariantError(
                    f"Multiple archives claim one Business Day: {day}"
                )
            result[day] = archive_name
        return result

    def _save_catalog_entry(
        self,
        day: BusinessDay,
        archive_name: str,
    ) -> None:
        entries = self._load_catalog()
        previous = entries.get(day)
        if previous is not None and previous != archive_name:
            raise MaintenanceInvariantError(
                f"Multiple archives claim one Business Day: {day}"
            )
        entries[day] = archive_name
        value: JsonObject = {
            "schema_version": _CATALOG_SCHEMA_VERSION,
            "entries": [
                {"day": str(item_day), "archive_name": entries[item_day]}
                for item_day in sorted(entries)
            ],
        }
        try:
            atomic_write_text(
                self._archive_root / "catalog.json",
                json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            )
        except OSError as exc:
            raise MaintenanceInvariantError(
                f"Failed to write Daily archive catalog: {type(exc).__name__}"
            ) from exc

    def _validate_layout(self) -> None:
        roots = {
            "Session": self._session.root.resolve(),
            "Workspace": self._workspace.root.resolve(),
        }
        archive = self._archive_root.resolve()
        for name, root in roots.items():
            if _paths_overlap(archive, root):
                raise MaintenanceContractError(
                    f"Daily archive root overlaps {name} root: {root}"
                )
        items = tuple(roots.items())
        for index, (left_name, left) in enumerate(items):
            for right_name, right in items[index + 1 :]:
                if _paths_overlap(left, right):
                    raise MaintenanceContractError(
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
            raise MaintenanceInvariantError("Session and Workspace active days disagree")
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
            raise MaintenanceInvariantError(
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
            raise MaintenanceInvariantError(
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
        saved = False
        try:
            self._save_journal(pending, journal)
            saved = True
        finally:
            if not saved:
                shutil.rmtree(pending, ignore_errors=True)
        return pending, journal

    def _resume(
        self,
        pending: Path,
        journal: DailyTransitionJournal,
    ) -> Path:
        from_day = BusinessDay.parse(journal.from_day)
        to_day = BusinessDay.parse(journal.to_day)
        if (pending / "home").exists():
            raise MaintenanceInvariantError(
                "Pending Daily transition contains forbidden Home data; "
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
            raise MaintenanceInvariantError(f"Daily archive already exists: {archive}")
        self._save_catalog_entry(from_day, journal.archive_name)
        try:
            os.replace(pending, archive)
        except OSError as exc:
            raise MaintenanceInvariantError(f"Failed to finalize Daily archive: {exc}") from exc
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
                    raise MaintenanceInvariantError(
                        "Pending Daily transition has participant data but no journal"
                    )
                try:
                    shutil.rmtree(path)
                except OSError as exc:
                    raise MaintenanceInvariantError(
                        f"Failed to discard unstarted Daily transition: {exc}"
                    ) from exc
        pending = tuple(path for path in pending if path.exists())
        if len(pending) > 1:
            raise MaintenanceInvariantError("Multiple pending Daily transitions exist")
        return pending[0] if pending else None

    @staticmethod
    def _load_journal(pending: Path) -> DailyTransitionJournal:
        path = pending / "transition.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MaintenanceInvariantError(f"Failed to read Daily journal: {exc}") from exc
        if not isinstance(value, dict):
            raise MaintenanceInvariantError("Daily journal root must be an object")
        try:
            return DailyTransitionJournal.from_json(to_json_object(value))
        except MaintenanceContractError as exc:
            raise MaintenanceInvariantError(
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
            raise MaintenanceInvariantError(f"Failed to write Daily journal: {exc}") from exc


def _required_str(value: JsonObject, name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item:
        raise MaintenanceContractError(f"Daily journal field must be text: {name}")
    return item


def _required_int(value: JsonObject, name: str) -> int:
    item = value.get(name)
    if isinstance(item, bool) or not isinstance(item, int):
        raise MaintenanceContractError(f"Daily journal field must be int: {name}")
    return item


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents
