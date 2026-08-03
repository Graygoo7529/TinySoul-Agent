"""Session business engine: immutable Turns, Summary heap, and projections."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from threading import RLock

from tinysoul.context import (
    ContextTurnCompletion,
    SessionBackgroundItem,
    SessionBackgroundSnapshot,
)
from tinysoul.infra.continuation import (
    ContinuationError,
    ContinuationFailureReason,
    OpaqueContinuationCodec,
    continue_json_sequence,
)
from tinysoul.infra.json import JsonObject, dumps_json
from tinysoul.maintenance import BusinessDay

from .background import (
    project_overflow_background,
    project_summary_background,
    project_turn_background,
)
from .completion import project_turn_record
from .config import SessionSettings
from .errors import (
    SessionContractError,
    SessionInspectFailureReason,
    SessionInspectRequestError,
    SessionInvariantError,
)
from .memory import SessionMemoryFactsProjection, project_session_memory_facts
from .models import (
    SessionManifest,
    SessionOutputRecord,
    SessionRecord,
    SessionRecordKind,
    SessionSummaryRecord,
    SessionTurnRecord,
    summary_ref,
)
from .navigation import (
    action_collection_ref,
    action_leaf_ref,
    parse_action_ref,
    project_action,
    project_action_header,
    project_navigation_header,
    project_turn,
)
from .reconcile import SessionReconcileResult, SessionReconciler
from .store import SessionStore
from .validation import validate_record, validate_summary_record, validate_turn_record


@dataclass(frozen=True)
class SessionArchiveSnapshot:
    """Validated, read-only roots for one archived Business Day."""

    day: BusinessDay
    root: Path
    revision: int
    refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.day, BusinessDay):
            raise SessionContractError(
                "Session archive snapshot day must be a BusinessDay"
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
        self._continuations = OpaqueContinuationCodec(
            owner="session",
            operation="inspect",
        )
        self._manifest = self._store.load_active_manifest()
        self._last_reconcile_result = SessionReconcileResult(revision=0)
        if self._manifest is not None:
            self._last_reconcile_result = self._reconcile_current()

    @property
    def root(self) -> Path:
        return self._settings.root

    @property
    def active_day(self) -> BusinessDay | None:
        with self._lock:
            return (
                BusinessDay.parse(self._manifest.day)
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

    def initialize_day(self, day: BusinessDay) -> None:
        with self._lock:
            _require_business_day(day)
            if self._manifest is not None:
                self._require_day(day)
                self._last_reconcile_result = self._reconcile_current()
                return
            self._manifest = self._store.create_manifest(str(day))
            self._last_reconcile_result = SessionReconcileResult(revision=0)

    def archive_day(self, day: BusinessDay, *, target: Path) -> None:
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
        day: BusinessDay,
        *,
        root: Path,
    ) -> SessionArchiveSnapshot:
        _require_business_day(day)
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

    def memory_facts(
        self,
        day: BusinessDay,
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

    def background_snapshot(self, day: BusinessDay) -> SessionBackgroundSnapshot:
        with self._lock:
            self._require_day(day)
            self._last_reconcile_result = self._reconcile_current()
            manifest = self._require_manifest()
            projected = tuple(
                SessionBackgroundItem(
                    item_id=ref,
                    content=self._background_for_ref(ref),
                )
                for ref in manifest.refs
            )
            items = self._fit_background(projected)
            return SessionBackgroundSnapshot(
                revision=manifest.revision,
                items=items,
            )

    def record_turn(
        self,
        completion: ContextTurnCompletion,
        *,
        day: BusinessDay,
        output: SessionOutputRecord | None,
        exhausted: bool,
    ) -> None:
        with self._lock:
            self._require_day(day)
            self._last_reconcile_result = self._reconcile_current()
            record = project_turn_record(
                completion,
                day=day,
                output=output,
                exhausted=exhausted,
            )
            validate_turn_record(record)
            stored = validate_turn_record(self._store.save_record_if_absent(record))
            manifest = self._require_manifest()
            if self._is_reachable(stored.ref, manifest.refs):
                return
            refs = self._compact_refs((*manifest.refs, stored.ref), day=day)
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
        continuation: str | None = None,
    ) -> JsonObject:
        """Inspect one Session heap node by exactly one semantic level."""

        with self._lock:
            manifest = self._require_manifest()
            if action is not None and (not isinstance(action, str) or not action):
                raise SessionInspectRequestError(
                    SessionInspectFailureReason.INVALID_REF,
                    "Session Action filter must be non-empty text",
                    scope="session.inspect",
                )
            try:
                action_ref = parse_action_ref(ref) if ref is not None else None
            except SessionContractError as exc:
                raise _request_error(
                    SessionInspectFailureReason.INVALID_REF,
                    str(exc),
                    ref=ref,
                ) from exc
            if action_ref is not None:
                record = self._load_turn(action_ref.turn_ref)
                if action_ref.is_collection:
                    collection_ref = action_collection_ref(record.ref)
                    actions = tuple(
                        project_action_header(record.ref, index, item)
                        for index, item in enumerate(record.actions)
                        if action is None or item.action == action
                    )
                    return self._page(
                        actions,
                        base={"kind": "session_actions", "ref": collection_ref},
                        item_field="actions",
                        continuation=continuation,
                        ref=collection_ref,
                        binding=({"action": action} if action is not None else None),
                    )
                if action is not None:
                    raise _request_error(
                        SessionInspectFailureReason.WRONG_RECORD_KIND,
                        "Session Action filter only applies to an Action collection",
                        ref=ref,
                    )
                assert action_ref.occurrence is not None
                if action_ref.occurrence >= len(record.actions):
                    raise _request_error(
                        SessionInspectFailureReason.UNKNOWN_REF,
                        "Unknown Session Action ref",
                        ref=ref,
                    )
                detail = project_action(
                    record.ref,
                    action_ref.occurrence,
                    record.actions[action_ref.occurrence],
                )
                leaf_ref = action_leaf_ref(record.ref, action_ref.occurrence)
                return self._page(
                    (detail,),
                    base={"kind": "session_action", "ref": leaf_ref},
                    item_field="content",
                    continuation=continuation,
                    ref=leaf_ref,
                )
            if action is not None:
                raise _request_error(
                    SessionInspectFailureReason.WRONG_RECORD_KIND,
                    "Session Action filter requires an Action collection ref",
                    ref=ref,
                )
            if ref is None:
                nodes = tuple(self._navigation_header(item) for item in manifest.refs)
                return self._page(
                    nodes,
                    base={"kind": "session_head"},
                    item_field="nodes",
                    continuation=continuation,
                    ref="session:head",
                    binding={"revision": manifest.revision},
                )
            record = self._requested_record(ref)
            if isinstance(record, SessionSummaryRecord):
                nodes = tuple(
                    self._navigation_header(child_ref)
                    for child_ref in record.child_refs
                )
                return self._page(
                    nodes,
                    base={"kind": "session_summary", "ref": ref},
                    item_field="nodes",
                    continuation=continuation,
                    ref=ref,
                )
            detail = project_turn(record)
            return self._page(
                (detail,),
                base={"kind": "session_turn", "ref": ref},
                item_field="content",
                continuation=continuation,
                ref=ref,
            )

    def _page(
        self,
        values: tuple[JsonObject, ...],
        *,
        base: JsonObject,
        item_field: str,
        continuation: str | None,
        ref: str,
        binding: JsonObject | None = None,
    ) -> JsonObject:
        try:
            return continue_json_sequence(
                values,
                base=base,
                item_field=item_field,
                continuation=continuation,
                codec=self._continuations,
                ref=ref,
                binding=binding,
                max_chars=self._settings.inspect_max_chars,
            )
        except ContinuationError as exc:
            reason = (
                SessionInspectFailureReason.PAGE_BUDGET_TOO_SMALL
                if exc.reason is ContinuationFailureReason.BUDGET_TOO_SMALL
                else SessionInspectFailureReason.INVALID_CONTINUATION
            )
            raise _request_error(reason, str(exc), ref=ref) from exc

    def _reconcile_current(self) -> SessionReconcileResult:
        manifest = self._require_manifest()
        scan = self._reconciler.scan(manifest)
        if not scan.orphan_turn_records:
            return SessionReconcileResult(
                revision=manifest.revision,
                orphan_summary_refs=scan.orphan_summary_refs,
            )
        refs = manifest.refs
        for record in scan.orphan_turn_records:
            refs = self._compact_refs(
                (*refs, record.ref),
                day=BusinessDay.parse(manifest.day),
            )
        committed = SessionManifest(
            day=manifest.day,
            revision=manifest.revision + len(scan.orphan_turn_records),
            refs=refs,
        )
        self._store.save_manifest(committed)
        self._manifest = committed
        return SessionReconcileResult(
            revision=committed.revision,
            adopted_turn_refs=tuple(
                record.ref for record in scan.orphan_turn_records
            ),
            orphan_summary_refs=scan.orphan_summary_refs,
        )

    def _compact_refs(
        self,
        refs: tuple[str, ...],
        *,
        day: BusinessDay,
    ) -> tuple[str, ...]:
        watermark = int(
            self._settings.background_max_chars
            * self._settings.summary_watermark_ratio
        )
        if self._background_chars(refs) <= watermark:
            return refs
        keep_start = _recent_turn_start(
            refs,
            store=self._store,
            count=self._settings.min_recent_turns,
        )
        if keep_start < 2:
            return refs
        target = int(
            self._settings.background_max_chars
            * self._settings.summary_target_ratio
        )
        cut = keep_start
        for candidate in range(2, keep_start + 1):
            trial_children = refs[:candidate]
            trial = SessionSummaryRecord(
                ref=summary_ref(str(day), trial_children),
                day=str(day),
                child_refs=trial_children,
            )
            trial_chars = len(
                dumps_json(
                    project_summary_background(
                        trial,
                        turn_count=sum(
                            self._turn_count(child_ref)
                            for child_ref in trial_children
                        ),
                    )
                )
            ) + self._background_chars(refs[candidate:])
            if trial_chars <= target:
                cut = candidate
                break
        children = refs[:cut]
        record = SessionSummaryRecord(
            ref=summary_ref(str(day), children),
            day=str(day),
            child_refs=children,
        )
        validate_summary_record(record)
        stored = validate_summary_record(self._store.save_record_if_absent(record))
        compacted = (stored.ref, *refs[cut:])
        return compacted

    def _background_chars(self, refs: tuple[str, ...]) -> int:
        return sum(len(dumps_json(self._background_for_ref(ref))) for ref in refs)

    def _background_for_ref(self, ref: str) -> JsonObject:
        record = self._record(ref)
        if isinstance(record, SessionTurnRecord):
            return project_turn_background(record)
        return project_summary_background(
            record,
            turn_count=self._turn_count(record.ref),
        )

    def _fit_background(
        self,
        items: tuple[SessionBackgroundItem, ...],
    ) -> tuple[SessionBackgroundItem, ...]:
        if (
            sum(len(dumps_json(item.content)) for item in items)
            <= self._settings.background_max_chars
        ):
            return items
        overflow = SessionBackgroundItem(
            item_id="session_overflow_head",
            content=project_overflow_background(),
        )
        used = len(dumps_json(overflow.content))
        selected: list[SessionBackgroundItem] = []
        for item in reversed(items):
            size = len(dumps_json(item.content))
            if used + size > self._settings.background_max_chars:
                break
            selected.append(item)
            used += size
        selected.reverse()
        return (overflow, *selected)

    def _navigation_header(self, ref: str) -> JsonObject:
        record = self._record(ref)
        return project_navigation_header(
            record,
            turn_count=self._turn_count(ref),
        )

    def _turn_count(self, ref: str) -> int:
        record = self._record(ref)
        if isinstance(record, SessionTurnRecord):
            return 1
        return sum(self._turn_count(child_ref) for child_ref in record.child_refs)

    def _record(self, ref: str) -> SessionRecord:
        try:
            return validate_record(self._store.load_record(ref))
        except SessionContractError as exc:
            raise SessionInvariantError(
                f"Session graph references a missing record: {ref}"
            ) from exc

    def _requested_record(self, ref: str) -> SessionRecord:
        try:
            record = validate_record(self._store.load_record(ref))
        except SessionContractError as exc:
            raise _request_error(
                SessionInspectFailureReason.UNKNOWN_REF,
                "Unknown Session ref",
                ref=ref,
            ) from exc
        if not self._is_reachable(ref, self._require_manifest().refs):
            raise _request_error(
                SessionInspectFailureReason.UNKNOWN_REF,
                "Unknown Session ref",
                ref=ref,
            )
        return record

    def _load_turn(self, ref: str) -> SessionTurnRecord:
        record = self._requested_record(ref)
        if not isinstance(record, SessionTurnRecord):
            raise _request_error(
                SessionInspectFailureReason.WRONG_RECORD_KIND,
                "Session Action ref must belong to a Turn",
                ref=ref,
            )
        return record

    def _is_reachable(self, target: str, refs: tuple[str, ...]) -> bool:
        for ref in refs:
            if ref == target:
                return True
            record = self._record(ref)
            if isinstance(record, SessionSummaryRecord) and self._is_reachable(
                target, record.child_refs
            ):
                return True
        return False

    def _require_manifest(self) -> SessionManifest:
        if self._manifest is None:
            raise SessionContractError("Session day is not initialized")
        return self._manifest

    def _require_day(self, day: BusinessDay) -> SessionManifest:
        _require_business_day(day)
        manifest = self._require_manifest()
        if manifest.day != str(day):
            raise SessionContractError(
                f"Session active day mismatch: {manifest.day} != {day}"
            )
        return manifest


def _recent_turn_start(
    refs: tuple[str, ...],
    *,
    store: SessionStore,
    count: int,
) -> int:
    if count == 0:
        return len(refs)
    seen = 0
    for index in range(len(refs) - 1, -1, -1):
        if isinstance(store.load_record(refs[index]), SessionTurnRecord):
            seen += 1
            if seen == count:
                return index
    return 0


def _request_error(
    reason: SessionInspectFailureReason,
    message: str,
    *,
    ref: str | None,
) -> SessionInspectRequestError:
    return SessionInspectRequestError(
        reason,
        message,
        constraint=({"ref": ref} if ref is not None else {}),
        scope="session.inspect",
    )


def _require_business_day(day: BusinessDay) -> None:
    if not isinstance(day, BusinessDay):
        raise SessionContractError("Session day must be a BusinessDay")
