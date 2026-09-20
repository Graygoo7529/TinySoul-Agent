"""Session business engine: immutable Turns, factual Map, and projections."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from tinysoul.kernel.context import (
    ContextTurnCompletion,
)
from tinysoul.infra.json import JsonObject
from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.loop.outcomes import TurnFailure, TurnOutcomeStatus

from .views.background import SessionBackgroundSnapshot
from .completion import project_turn_record
from .config import SessionSettings
from .errors import (
    SessionContractError,
    SessionInvariantError,
)
from .views.memory import SessionMemoryFactsProjection, project_session_memory_facts
from .records.models import (
    SessionManifest,
    SessionOutputRecord,
    SessionTurnRecord,
)
from .views import SessionView
from .records.reconcile import SessionReconcileResult, SessionReconciler
from .records.store import SessionStore
from .records.validation import validate_turn_record


@dataclass(frozen=True)
class SessionArchiveSnapshot:
    """Validated, read-only roots for one archived Business Day."""

    day: CalendarDay
    root: Path
    revision: int
    refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.day, CalendarDay):
            raise SessionContractError(
                "Session archive snapshot day must be a CalendarDay"
            )
        if not isinstance(self.root, Path) or not self.root.is_absolute():
            raise SessionContractError(
                "Session archive snapshot root must be an absolute Path"
            )
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 0
        ):
            raise SessionContractError(
                "Session archive snapshot revision must be non-negative"
            )
        refs = tuple(self.refs)
        if any(not isinstance(ref, str) or not ref for ref in refs):
            raise SessionContractError(
                "Session archive snapshot refs must be non-empty"
            )
        object.__setattr__(self, "refs", refs)

    @property
    def has_facts(self) -> bool:
        return bool(self.refs)


class SessionEngine:
    """Own completed-Turn persistence and prior-Turn semantic inspection."""

    def __init__(
        self,
        settings: SessionSettings,
        *,
        store: SessionStore | None = None,
    ) -> None:
        self._settings = settings
        self._lock = RLock()
        self._store = store or SessionStore(root=settings.root)
        if self._store.root.resolve() != settings.root.resolve():
            raise SessionContractError(
                "Session store root must match Session settings root"
            )
        self._reconciler = SessionReconciler(self._store)
        self._manifest = self._store.load_active_manifest()
        self._last_reconcile_result = SessionReconcileResult(revision=0)
        if self._manifest is not None:
            self._last_reconcile_result = self._reconcile_current()

    @property
    def root(self) -> Path:
        return self._settings.root

    @property
    def active_day(self) -> CalendarDay | None:
        with self._lock:
            return (
                CalendarDay.parse(self._manifest.day)
                if self._manifest is not None
                else None
            )

    @property
    def revision(self) -> int:
        with self._lock:
            return self._manifest.revision if self._manifest is not None else 0

    @property
    def last_reconcile_result(self) -> SessionReconcileResult:
        with self._lock:
            return self._last_reconcile_result

    def initialize_day(self, day: CalendarDay) -> None:
        with self._lock:
            _require_active_day(day)
            if self._manifest is not None:
                self._require_day(day)
                self._last_reconcile_result = self._reconcile_current()
                return
            self._manifest = self._store.create_manifest(str(day))
            self._last_reconcile_result = SessionReconcileResult(revision=0)

    def archive_day(self, day: CalendarDay, *, target: Path) -> None:
        with self._lock:
            self._require_day(day)
            self._last_reconcile_result = self._reconcile_current()
            self._store.archive_to(target)
            self._manifest = None
            self._last_reconcile_result = SessionReconcileResult(revision=0)

    def reconcile_active(self) -> SessionReconcileResult:
        with self._lock:
            self._require_manifest()
            self._last_reconcile_result = self._reconcile_current()
            return self._last_reconcile_result

    def archive_snapshot(
        self,
        day: CalendarDay,
        *,
        root: Path,
    ) -> SessionArchiveSnapshot:
        _require_active_day(day)
        if not isinstance(root, Path) or not root.is_absolute():
            raise SessionContractError("Session archive root must be absolute")
        store = SessionStore(root=root)
        manifest = store.load_manifest()
        if manifest.day != str(day):
            raise SessionInvariantError(
                f"Session archive day mismatch: {manifest.day} != {day}"
            )
        scan = SessionReconciler(store).scan(manifest)
        if scan.orphan_turn_records:
            raise SessionInvariantError(
                "Session archive contains uncommitted Turn records"
            )
        return SessionArchiveSnapshot(
            day=day,
            root=root,
            revision=manifest.revision,
            refs=manifest.refs,
        )

    def archive_available(self, day: CalendarDay, *, root: Path) -> bool:
        """Return false for an absent archive and validate one that exists."""

        _require_active_day(day)
        if not isinstance(root, Path) or not root.is_absolute():
            raise SessionContractError("Session archive root must be absolute")
        manifest = root / "manifest.json"
        if manifest.is_symlink():
            raise SessionInvariantError("Session archive manifest cannot be a symlink")
        if not manifest.exists():
            return False
        if not manifest.is_file():
            raise SessionInvariantError("Session archive manifest is not a file")
        self.archive_snapshot(day, root=root)
        return True

    def memory_facts(
        self,
        day: CalendarDay,
        *,
        root: Path,
    ) -> SessionMemoryFactsProjection:
        snapshot = self.archive_snapshot(day, root=root)
        return project_session_memory_facts(
            day=day,
            root=root,
            revision=snapshot.revision,
            refs=snapshot.refs,
        )

    def archive_view(self, day: CalendarDay, *, root: Path) -> SessionView:
        """Open a fixed, read-only source without a writable archive Engine."""

        snapshot = self.archive_snapshot(day, root=root)
        return SessionView(
            SessionManifest(
                day=str(day), revision=snapshot.revision, refs=snapshot.refs
            ),
            self._settings,
            SessionStore(root=root),
        )

    def snapshot_view(self, day: CalendarDay) -> SessionView:
        """Freeze the current committed source set for a Turn."""

        with self._lock:
            self._require_day(day)
            self._last_reconcile_result = self._reconcile_current()
            return SessionView(self._require_manifest(), self._settings, self._store)

    def empty_view(self, day: CalendarDay) -> SessionView:
        """Represent an explicitly absent historical Session source."""

        _require_active_day(day)
        return SessionView(
            SessionManifest(day=str(day), revision=0, refs=()),
            self._settings,
            self._store,
        )

    def background_snapshot(self, day: CalendarDay) -> SessionBackgroundSnapshot:
        return self.snapshot_view(day).background_snapshot(day)

    def record_turn(
        self,
        completion: ContextTurnCompletion,
        *,
        day: CalendarDay,
        output: SessionOutputRecord | None,
        exhausted: bool,
        status: TurnOutcomeStatus,
        failure: TurnFailure | None = None,
        finish_failures: tuple[TurnFailure, ...] = (),
    ) -> None:
        with self._lock:
            self._require_day(day)
            self._last_reconcile_result = self._reconcile_current()
            record = project_turn_record(
                completion,
                day=day,
                output=output,
                exhausted=exhausted,
                status=status,
                failure=failure,
                finish_failures=finish_failures,
            )
            validate_turn_record(record)
            stored = validate_turn_record(self._store.save_record_if_absent(record))
            manifest = self._require_manifest()
            if stored.ref in manifest.refs:
                return
            refs = (*manifest.refs, stored.ref)
            committed = SessionManifest(
                day=manifest.day,
                revision=manifest.revision + 1,
                refs=refs,
            )
            self._store.save_manifest(committed)
            self._manifest = committed
            self._last_reconcile_result = SessionReconcileResult(
                revision=committed.revision
            )

    def inspect(
        self,
        ref: str | None = None,
        *,
        action: str | None = None,
        query: str | None = None,
        continuation: str | None = None,
        expected_revision: int | None = None,
    ) -> JsonObject:
        with self._lock:
            view = SessionView(self._require_manifest(), self._settings, self._store)
        return view.inspect(
            ref,
            action=action,
            query=query,
            continuation=continuation,
            expected_revision=expected_revision,
        )

    def _reconcile_current(self) -> SessionReconcileResult:
        manifest = self._require_manifest()
        scan = self._reconciler.scan(manifest)
        if not scan.orphan_turn_records:
            return SessionReconcileResult(
                revision=manifest.revision,
            )
        refs = (*manifest.refs, *(record.ref for record in scan.orphan_turn_records))
        committed = SessionManifest(
            day=manifest.day,
            revision=manifest.revision + len(scan.orphan_turn_records),
            refs=refs,
        )
        self._store.save_manifest(committed)
        self._manifest = committed
        return SessionReconcileResult(
            revision=committed.revision,
            adopted_turn_refs=tuple(record.ref for record in scan.orphan_turn_records),
        )

    def _require_manifest(self) -> SessionManifest:
        if self._manifest is None:
            raise SessionContractError("Session day is not initialized")
        return self._manifest

    def _require_day(self, day: CalendarDay) -> SessionManifest:
        _require_active_day(day)
        manifest = self._require_manifest()
        if manifest.day != str(day):
            raise SessionContractError(
                f"Session active day mismatch: {manifest.day} != {day}"
            )
        return manifest


def _require_active_day(day: CalendarDay) -> None:
    if not isinstance(day, CalendarDay):
        raise SessionContractError("Session day must be a CalendarDay")
