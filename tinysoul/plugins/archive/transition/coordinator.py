"""Archive owner: deterministic rollover journal and frozen-day catalog."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import shutil
from uuid import uuid4

from tinysoul.infra.concurrency import ReadWriteLock
from tinysoul.infra.filesystem import atomic_write_text
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.infra.time import CalendarDay
from tinysoul.runtime import (
    NullObservationEmitter,
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    RunScope,
    emit_observation,
    observation_enabled,
)
from tinysoul.plugins.session import SessionIOError, SessionInvariantError
from tinysoul.plugins.workspace import WorkspaceIOError, WorkspaceInvariantError
from tinysoul.plugins.memory import MemoryIOError, MemoryInvariantError

from ..errors import ArchiveContractError, ArchiveInvariantError


from ..projection import ArchiveProjection
from ..catalog import ArchiveCatalog
from .journal import DailyTransitionStep, DailyTransitionJournal
from .contracts import (
    DailyTransitionOutcome,
    ActiveDayLease,
    SessionDailyLifecycle,
    WorkspaceDailyLifecycle,
    ActiveMemoryDailyLifecycle,
)


class DailyLifecycleCoordinator:
    """Archive Session and Workspace facts before opening the next day."""

    def __init__(
        self,
        *,
        archive_root: Path,
        session: SessionDailyLifecycle,
        workspace: WorkspaceDailyLifecycle,
        memory: ActiveMemoryDailyLifecycle,
        observations: ObservationEmitter | None = None,
    ) -> None:
        self._archive_root = archive_root
        self._catalog = ArchiveCatalog(archive_root)
        self._session = session
        self._workspace = workspace
        self._memory = memory
        self._observations = observations or NullObservationEmitter()
        self._lock = ReadWriteLock()

    def active_day_lease(self) -> ActiveDayLease:
        """Exclude rollover while one caller reads or mutates active-day state."""

        return ActiveDayLease(
            lock=self._lock,
            session=self._session,
            workspace=self._workspace,
            memory=self._memory,
        )

    def ensure_active_day(
        self,
        target_day: CalendarDay,
        *,
        now: datetime,
        scope: RunScope | None = None,
    ) -> DailyTransitionOutcome:
        with self._lock.write_locked():
            if not isinstance(target_day, CalendarDay):
                raise ArchiveContractError("Daily target must be a CalendarDay")
            if not isinstance(now, datetime) or now.tzinfo is None:
                raise ArchiveContractError(
                    "Daily rollover timestamp must be timezone-aware"
                )
            run_scope = scope or RunScope()
            try:
                return self._ensure_active_day_locked(
                    target_day,
                    now=now,
                    scope=run_scope,
                )
            except ArchiveContractError as exc:
                self._emit_failed(run_scope, target_day, exc)
                raise
            except ArchiveInvariantError as exc:
                self._emit_failed(run_scope, target_day, exc)
                raise
            except (
                OSError,
                SessionIOError,
                SessionInvariantError,
                WorkspaceIOError,
                WorkspaceInvariantError,
                MemoryIOError,
                MemoryInvariantError,
            ) as exc:
                self._emit_failed(run_scope, target_day, exc)
                raise ArchiveInvariantError(
                    f"Daily rollover failed: {type(exc).__name__}"
                ) from exc

    def _ensure_active_day_locked(
        self,
        target_day: CalendarDay,
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
            active = CalendarDay.parse(journal.to_day)
            recovered = self._projection_for_archive(
                CalendarDay.parse(journal.from_day),
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
            raise ArchiveInvariantError(
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
    def _projection_for_archive(day: CalendarDay, archive: Path) -> ArchiveProjection:
        root = archive.resolve()
        session_root = root / "session"
        workspace_root = root / "workspace"
        if not session_root.is_dir() or not workspace_root.is_dir():
            raise ArchiveInvariantError("Daily archive is missing participant facts")
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
        target_day: CalendarDay,
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
                source="reflection.archive",
                scope=scope,
                message=message,
                payload=payload,
            ),
        )

    def archive_for(self, day: CalendarDay) -> ArchiveProjection | None:
        """Resolve one finalized archive through the durable date index."""

        with self._lock.read_locked():
            if not isinstance(day, CalendarDay):
                raise ArchiveContractError("Archive day must be a CalendarDay")
            archive_name = self._catalog.load().get(day)
            if archive_name is None:
                return None
            archive = self._archive_root / archive_name
            if not archive.is_dir():
                raise ArchiveInvariantError(
                    f"Archive catalog points to a missing directory: {archive_name}"
                )
            journal = self._load_journal(archive)
            if journal.archive_name != archive_name or journal.from_day != str(day):
                raise ArchiveInvariantError(
                    "Archive catalog identity does not match its journal"
                )
            return self._projection_for_archive(day, archive)

    def archived_days(
        self, *, before: CalendarDay | None = None, limit: int = 64
    ) -> tuple[CalendarDay, ...]:
        """List newest archive dates without opening every historical owner root."""

        if type(limit) is not int or limit < 1 or limit > 256:
            raise ArchiveContractError(
                "Archive date page limit must be between 1 and 256"
            )
        with self._lock.read_locked():
            return tuple(
                day
                for day in sorted(self._catalog.load(), reverse=True)
                if before is None or day < before
            )[:limit]

    def session_archive_for(self, day: CalendarDay) -> Path | None:
        projection = self.archive_for(day)
        return projection.session_root if projection is not None else None

    def _validate_layout(self) -> None:
        roots = {
            "Session": self._session.root.resolve(),
            "Workspace": self._workspace.root.resolve(),
            "Memory": self._memory.root.resolve(),
        }
        active_memory_root = self._memory.active_session_root
        if (
            active_memory_root is None
            or active_memory_root.resolve() != self._session.root.resolve()
        ):
            raise ArchiveContractError(
                "Active Memory must be bound to the Session root"
            )
        archive = self._archive_root.resolve()
        for name, root in roots.items():
            if _paths_overlap(archive, root):
                raise ArchiveContractError(
                    f"Daily archive root overlaps {name} root: {root}"
                )
        items = tuple(roots.items())
        for index, (left_name, left) in enumerate(items):
            for right_name, right in items[index + 1 :]:
                if _paths_overlap(left, right):
                    raise ArchiveContractError(
                        f"Daily roots overlap: {left_name} and {right_name}"
                    )

    def _claim_active_day(self, target_day: CalendarDay) -> CalendarDay:
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
            raise ArchiveInvariantError("Session and Workspace active days disagree")
        inherited = session_day or (next(iter(tagged)) if tagged else target_day)
        self._initialize_all(inherited)
        return inherited

    def _initialize_all(self, day: CalendarDay) -> None:
        self._session.initialize_day(day)
        self._memory.initialize_active_day(day)
        self._workspace.initialize_day(day)
        days = {
            self._session.active_day,
            self._workspace.active_day,
            self._memory.active_day(),
        }
        if days != {day}:
            raise ArchiveInvariantError(
                "Daily participants did not initialize the same active day"
            )

    def _start(
        self,
        from_day: CalendarDay,
        to_day: CalendarDay,
        *,
        now: datetime,
    ) -> tuple[Path, DailyTransitionJournal]:
        self._archive_root.mkdir(parents=True, exist_ok=True)
        archive_name = now.strftime("%Y%m%dT%H%M%S.%f%z")
        if (self._archive_root / archive_name).exists():
            raise ArchiveInvariantError(
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
        from_day = CalendarDay.parse(journal.from_day)
        to_day = CalendarDay.parse(journal.to_day)
        if (pending / "home").exists():
            raise ArchiveInvariantError(
                "Pending Daily transition contains forbidden Home data; "
                "manual recovery is required"
            )

        if not journal.completed(DailyTransitionStep.SESSION_ARCHIVED):
            if (pending / "session").exists() and self._session.active_day is None:
                self._memory.validate_archived_active(
                    from_day,
                    (pending / "session").resolve(),
                )
            else:
                self._memory.validate_active_day(from_day)
                self._session.reconcile_active()
                self._session.archive_day(from_day, target=pending / "session")
                self._memory.validate_archived_active(
                    from_day,
                    (pending / "session").resolve(),
                )
            journal = journal.with_step(DailyTransitionStep.SESSION_ARCHIVED)
            self._save_journal(pending, journal)
        self._memory.validate_archived_active(
            from_day,
            (pending / "session").resolve(),
        )

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
            raise ArchiveInvariantError(f"Daily archive already exists: {archive}")
        self._catalog.record(from_day, journal.archive_name)
        try:
            os.replace(pending, archive)
        except OSError as exc:
            raise ArchiveInvariantError(
                f"Failed to finalize Daily archive: {exc}"
            ) from exc
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
                    raise ArchiveInvariantError(
                        "Pending Daily transition has participant data but no journal"
                    )
                try:
                    shutil.rmtree(path)
                except OSError as exc:
                    raise ArchiveInvariantError(
                        f"Failed to discard unstarted Daily transition: {exc}"
                    ) from exc
        pending = tuple(path for path in pending if path.exists())
        if len(pending) > 1:
            raise ArchiveInvariantError("Multiple pending Daily transitions exist")
        return pending[0] if pending else None

    @staticmethod
    def _load_journal(pending: Path) -> DailyTransitionJournal:
        path = pending / "transition.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ArchiveInvariantError(f"Failed to read Daily journal: {exc}") from exc
        if not isinstance(value, dict):
            raise ArchiveInvariantError("Daily journal root must be an object")
        try:
            return DailyTransitionJournal.from_json(to_json_object(value))
        except ArchiveContractError as exc:
            raise ArchiveInvariantError(
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
            raise ArchiveInvariantError(
                f"Failed to write Daily journal: {exc}"
            ) from exc


def _required_str(value: JsonObject, name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item:
        raise ArchiveContractError(f"Daily journal field must be text: {name}")
    return item


def _required_int(value: JsonObject, name: str) -> int:
    item = value.get(name)
    if isinstance(item, bool) or not isinstance(item, int):
        raise ArchiveContractError(f"Daily journal field must be int: {name}")
    return item


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents
