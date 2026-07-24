"""Session history facade and bounded background projection."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from threading import RLock

from tinysoul.context import SessionBackgroundItem, SessionBackgroundSnapshot, TurnSummary
from tinysoul.infra.json import JsonObject, dumps_json, to_json_object
from tinysoul.infra.paging import (
    JsonPageCursor,
    JsonPageError,
    JsonPageFailureReason,
    page_json_sequence,
)
from tinysoul.loop.day import BusinessDay

from .action_history import TurnActionProjection, project_turn_actions
from .config import SessionSettings
from .errors import (
    SessionContractError,
    SessionHistoryFailureReason,
    SessionHistoryRequestError,
    SessionInvariantError,
)
from .memory import (
    SessionMemoryFactsProjection,
    project_session_memory_facts,
)
from .models import (
    SessionHistoryItem,
    SessionHistoryKind,
    SessionManifest,
    SessionRecord,
)
from .reconcile import SessionReconcileResult, SessionReconciler
from .store import SessionStore


@dataclass(frozen=True)
class SessionArchiveSnapshot:
    """Validated, read-only history head for one archived Business Day."""

    day: BusinessDay
    root: Path
    revision: int
    items: tuple[SessionHistoryItem, ...]

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
                "Session archive snapshot revision must be a non-negative integer"
            )
        if any(not isinstance(item, SessionHistoryItem) for item in self.items):
            raise SessionContractError(
                "Session archive snapshot items must be SessionHistoryItem values"
            )
        object.__setattr__(self, "items", tuple(self.items))

    @property
    def has_facts(self) -> bool:
        return bool(self.items)


class SessionEngine:
    """Persist completed Turns and expose a bounded history head."""

    def __init__(
        self,
        settings: SessionSettings,
        *,
        store: SessionStore | None = None,
    ) -> None:
        self._settings = settings
        self._lock = RLock()
        self._store = store or SessionStore(
            root=settings.root,
        )
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
    def active_day(self) -> BusinessDay | None:
        with self._lock:
            if self._manifest is None:
                return None
            return BusinessDay.parse(self._manifest.day)

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
            if not isinstance(day, BusinessDay):
                raise SessionContractError("Session day must be a BusinessDay")
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
            if self._manifest is None:
                return SessionReconcileResult(revision=0)
            self._last_reconcile_result = self._reconcile_current()
            return self._last_reconcile_result

    def archive_snapshot(
        self,
        day: BusinessDay,
        *,
        root: Path,
    ) -> SessionArchiveSnapshot:
        """Validate and expose one archived Session head without mutating it."""

        with self._lock:
            if not isinstance(day, BusinessDay):
                raise SessionContractError("Session archive day must be a BusinessDay")
            if not isinstance(root, Path):
                raise SessionContractError("Session archive root must be a Path")
            resolved = root.resolve()
            if resolved == self.root.resolve():
                raise SessionContractError(
                    "Session archive root must differ from the active root"
                )
            store = SessionStore(root=resolved)
            manifest = store.load_active_manifest()
            if manifest is None:
                raise SessionContractError(
                    f"Session archive does not contain a manifest: {resolved}"
                )
            if manifest.day != str(day):
                raise SessionInvariantError(
                    f"Session archive day mismatch: expected {day}, found {manifest.day}"
                )
            scan = SessionReconciler(store).scan(manifest)
            if scan.orphan_turn_records:
                raise SessionInvariantError(
                    "Session archive contains uncommitted Turn records"
                )
            return SessionArchiveSnapshot(
                day=day,
                root=resolved,
                revision=manifest.revision,
                items=manifest.items,
            )

    def memory_facts(
        self,
        day: BusinessDay,
        *,
        root: Path,
    ) -> SessionMemoryFactsProjection:
        """Project all committed Turn facts from one validated archive."""

        snapshot = self.archive_snapshot(day, root=root)
        return project_session_memory_facts(
            day=snapshot.day,
            root=snapshot.root,
            revision=snapshot.revision,
            items=snapshot.items,
        )

    def background_snapshot(
        self,
        day: BusinessDay,
    ) -> SessionBackgroundSnapshot:
        with self._lock:
            self._require_day(day)
            self._last_reconcile_result = self._reconcile_current()
            manifest = self._require_manifest()
            items = self._bounded_background_items()
            return SessionBackgroundSnapshot(
                revision=manifest.revision,
                items=tuple(
                    SessionBackgroundItem(item_id=item.item_id, content=item.background)
                    for item in items
                ),
            )

    def record_turn(
        self,
        *,
        summary: TurnSummary,
        output: JsonObject | None,
        exhausted: bool,
        day: BusinessDay,
    ) -> None:
        with self._lock:
            self._require_day(day)
            manifest = self._require_manifest()
            ref = f"session:turn/{summary.turn_id}"
            projection = project_turn_actions(
                summary.trace,
                expected_digest=summary.trace_digest,
            )
            background = _turn_background(
                summary,
                projection=projection,
                output=output,
                exhausted=exhausted,
                action_names=frozenset(self._settings.background_action_names),
                max_actions=self._settings.background_max_actions_per_turn,
            )
            self._store.save_record_if_absent(
                SessionRecord(
                    ref=ref,
                    kind=SessionHistoryKind.TURN,
                    content={
                        "day": manifest.day,
                        "background": background,
                        "completion": summary.to_json(),
                        "action_history": projection.summary_json(),
                        "output": output,
                        "exhausted": exhausted,
                    },
                )
            )
            self._last_reconcile_result = self._reconcile_current()

    def inspect_history(
        self,
        ref: str | None = None,
        *,
        max_chars: int | None = None,
        max_entries: int | None = None,
        cursor: JsonObject | None = None,
    ) -> JsonObject:
        with self._lock:
            self._last_reconcile_result = self._reconcile_current()
            manifest = self._require_manifest()
            requested_chars, limit, requested_entries, entry_limit = (
                _history_page_limits(
                    self._settings,
                    max_chars=max_chars,
                    max_entries=max_entries,
                    scope="session.history.inspect",
                )
            )
            page_cursor = _inspect_cursor(
                cursor,
                ref=ref,
                revision=manifest.revision,
            )
            if ref is None:
                items = manifest.items
                source: JsonObject = {
                    "owner": "session",
                    "scope": "active_head",
                    "day": manifest.day,
                    "revision": manifest.revision,
                    "estimated_chars": sum(item.char_count for item in items),
                }
            else:
                record = _load_requested_record(
                    self._store,
                    ref,
                    scope="session.history.inspect",
                )
                if record.kind is SessionHistoryKind.SUMMARY:
                    items = _summary_children_from_record(record)
                    source = {
                        "owner": "session",
                        "scope": "summary_children",
                        "ref": ref,
                        "record_kind": record.kind.value,
                        "child_count": len(items),
                    }
                else:
                    item = _turn_item_from_record(record)
                    items = (item,)
                    completion = record.content.get("completion")
                    if not isinstance(completion, dict):
                        raise SessionInvariantError(
                            f"Session Turn record is missing completion: {ref}"
                        )
                    trace = completion.get("trace")
                    if not isinstance(trace, list):
                        raise SessionInvariantError(
                            f"Session Turn record has an invalid trace: {ref}"
                        )
                    source = {
                        "owner": "session",
                        "scope": "turn_overview",
                        "ref": ref,
                        "record_kind": record.kind.value,
                        "turn_id": item.item_id,
                        "trace_digest": completion.get("trace_digest"),
                        "trace_entry_count": len(trace),
                    }
            try:
                page = page_json_sequence(
                    tuple(self._inspect_item(item) for item in items),
                    base=to_json_object({"source": source}),
                    item_field="items",
                    cursor_unit="history_item",
                    cursor=page_cursor,
                    max_chars=limit,
                    max_entries=entry_limit,
                    requested_max_chars=requested_chars,
                    requested_max_entries=requested_entries,
                )
            except JsonPageError as exc:
                raise _session_page_error(
                    exc,
                    ref=ref,
                    scope="session.history.inspect",
                ) from exc
            if ref is None:
                _bind_page_revision(page, manifest.revision)
            return page

    def _inspect_item(self, item: SessionHistoryItem) -> JsonObject:
        value: JsonObject = {
            "item_id": item.item_id,
            "ref": item.ref,
            "kind": item.kind.value,
            "char_count": item.char_count,
            "child_count": len(item.child_refs),
            "preview": item.background,
        }
        if item.kind is SessionHistoryKind.TURN:
            _action_projection_from_record(self._store.load_record(item.ref))
        return to_json_object(value)

    def recall_history(
        self,
        ref: str,
        *,
        max_chars: int | None = None,
        max_entries: int | None = None,
        cursor: JsonObject | None = None,
    ) -> JsonObject:
        with self._lock:
            self._require_manifest()
            self._last_reconcile_result = self._reconcile_current()
            requested, limit, requested_entries, entry_limit = _history_page_limits(
                self._settings,
                max_chars=max_chars,
                max_entries=max_entries,
                scope="session.history.recall",
            )
            try:
                page_cursor = JsonPageCursor.from_json(cursor)
            except JsonPageError as exc:
                raise _session_page_error(
                    exc,
                    ref=ref,
                    scope="session.history.recall",
                ) from exc
            record = _load_requested_record(
                self._store,
                ref,
                scope="session.history.recall",
            )
            if record.kind is not SessionHistoryKind.TURN:
                raise SessionHistoryRequestError(
                    SessionHistoryFailureReason.WRONG_RECORD_KIND,
                    "Session recall is only available for Turn records",
                    constraint={"ref": ref, "record_kind": record.kind.value},
                    scope="session.history.recall",
                )
            return _recall_record(
                record,
                max_chars=limit,
                max_entries=entry_limit,
                requested_max_chars=requested,
                requested_max_entries=requested_entries,
                cursor=page_cursor,
            )

    def action_history(
        self,
        ref: str,
        *,
        cursor: int = 0,
        max_items: int | None = None,
    ) -> JsonObject:
        """Return complete Action facts plus one bounded detail page for a Turn."""

        with self._lock:
            self._require_manifest()
            self._last_reconcile_result = self._reconcile_current()
            if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
                raise SessionHistoryRequestError(
                    SessionHistoryFailureReason.INVALID_CURSOR,
                    "Session action history cursor must be non-negative",
                    constraint={"cursor": cursor},
                    scope="session.history.actions",
                )
            requested = (
                self._settings.actions_page_max_items
                if max_items is None
                else max_items
            )
            if (
                isinstance(requested, bool)
                or not isinstance(requested, int)
                or requested <= 0
            ):
                raise SessionHistoryRequestError(
                    SessionHistoryFailureReason.INVALID_MAX_ITEMS,
                    "Session action history max_items must be positive",
                    constraint={"max_items": requested},
                    scope="session.history.actions",
                )
            record = _load_requested_record(
                self._store,
                ref,
                scope="session.history.actions",
            )
            projection = _action_projection_from_record(record)
            completion = record.content.get("completion")
            if not isinstance(completion, dict):
                raise SessionInvariantError(
                    f"Session Turn record is missing completion: {ref}"
                )
            if cursor > len(projection.details):
                raise SessionHistoryRequestError(
                    SessionHistoryFailureReason.CURSOR_OUT_OF_RANGE,
                    "Session action history cursor exceeds the detail count",
                    constraint={
                        "cursor": cursor,
                        "detail_count": len(projection.details),
                    },
                    scope="session.history.actions",
                )
            trace_value = completion.get("trace")
            if not isinstance(trace_value, list):
                raise SessionInvariantError(
                    f"Session Turn record has an invalid trace: {ref}"
                )
            page_size = min(requested, self._settings.actions_page_max_items)
            stop = min(len(projection.details), cursor + page_size)
            next_cursor = stop if stop < len(projection.details) else None
            return {
                "source": {
                    "owner": "session",
                    "ref": ref,
                    "turn_id": completion.get("turn_id"),
                    "record_kind": record.kind.value,
                    "trace_digest": projection.trace_digest,
                    "trace_entry_count": len(trace_value),
                },
                "summary": projection.summary_json(),
                "details": [item.to_json() for item in projection.details[cursor:stop]],
                "detail_count": len(projection.details),
                "requested_max_items": requested,
                "effective_max_items": page_size,
                "returned_detail_count": stop - cursor,
                "cursor": cursor,
                "next_cursor": next_cursor,
                "coverage": [cursor, stop],
                "remaining": len(projection.details) - stop,
                "page_complete": next_cursor is None,
                "truncated": next_cursor is not None,
            }

    def _require_manifest(self) -> SessionManifest:
        if self._manifest is None:
            raise SessionInvariantError("Session has no active business day")
        return self._manifest

    def _require_day(self, day: BusinessDay) -> None:
        if not isinstance(day, BusinessDay):
            raise SessionContractError("Session day must be a BusinessDay")
        manifest = self._require_manifest()
        if manifest.day != str(day):
            raise SessionInvariantError(
                f"Session active day mismatch: expected {day}, found {manifest.day}"
            )

    def _reconcile_current(self) -> SessionReconcileResult:
        current = self._require_manifest()
        scan = self._reconciler.scan(current)
        if not scan.orphan_turn_records:
            return SessionReconcileResult(
                revision=current.revision,
                orphan_summary_refs=scan.orphan_summary_refs,
            )
        items = current.items
        adopted: list[str] = []
        for record in scan.orphan_turn_records:
            items = (*items, _turn_item_from_record(record))
            items = self._summarize_once(items)
            adopted.append(record.ref)
        manifest = SessionManifest(
            day=current.day,
            revision=current.revision + len(adopted),
            items=items,
        )
        self._store.save_manifest(manifest)
        self._manifest = manifest
        committed_scan = self._reconciler.scan(manifest)
        return SessionReconcileResult(
            revision=manifest.revision,
            adopted_turn_refs=tuple(adopted),
            orphan_summary_refs=committed_scan.orphan_summary_refs,
        )

    def _bounded_background_items(self) -> tuple[SessionHistoryItem, ...]:
        manifest = self._require_manifest()
        total = sum(item.char_count for item in manifest.items)
        if total <= self._settings.background_max_chars:
            return manifest.items
        head_background: JsonObject = {
            "kind": "session_overflow_head",
            "inspect_action": "session.history.inspect",
        }
        head_chars = len(dumps_json(head_background)) + 32
        selected: list[SessionHistoryItem] = []
        used = 0
        for item in reversed(manifest.items):
            if (
                used + item.char_count + head_chars
                > self._settings.background_max_chars
            ):
                break
            selected.append(item)
            used += item.char_count
        selected.reverse()
        omitted = len(manifest.items) - len(selected)
        if omitted <= 0:
            return tuple(selected)
        head_background["omitted_item_count"] = omitted
        head = SessionHistoryItem(
            item_id="session_overflow_head",
            ref="session:summary/session_overflow_head",
            kind=SessionHistoryKind.SUMMARY,
            background=head_background,
            char_count=len(dumps_json(head_background)),
        )
        return (head, *selected)

    def _summarize_once(
        self,
        items: tuple[SessionHistoryItem, ...],
    ) -> tuple[SessionHistoryItem, ...]:
        manifest = self._require_manifest()
        watermark = int(
            self._settings.background_max_chars
            * self._settings.summary_watermark_ratio
        )
        if sum(item.char_count for item in items) <= watermark:
            return items
        max_split = _summary_split(
            items,
            min_recent_turns=self._settings.min_recent_turns,
        )
        if max_split < 2:
            return items
        provisional_ref = f"session:summary/summary_{'0' * 16}"
        target = int(
            self._settings.background_max_chars
            * self._settings.summary_target_ratio
        )
        split = max_split
        for candidate in range(2, max_split + 1):
            candidate_background = _summary_background(
                provisional_ref,
                items[:candidate],
            )
            candidate_chars = len(dumps_json(candidate_background)) + sum(
                item.char_count for item in items[candidate:]
            )
            if candidate_chars <= target:
                split = candidate
                break
        children = items[:split]
        child_refs = tuple(item.ref for item in children)
        summary_digest = sha256(
            dumps_json(
                {
                    "schema_version": 1,
                    "day": manifest.day,
                    "child_refs": list(child_refs),
                }
            ).encode("utf-8")
        ).hexdigest()[:16]
        summary_id = f"summary_{summary_digest}"
        ref = f"session:summary/{summary_id}"
        background = _summary_background(ref, children)
        record = SessionRecord(
            ref=ref,
            kind=SessionHistoryKind.SUMMARY,
            content={
                "day": manifest.day,
                "background": background,
                "child_refs": list(child_refs),
                "children": [item.to_json() for item in children],
            },
        )
        self._store.save_record_if_absent(record)
        summary_item = SessionHistoryItem(
            item_id=summary_id,
            ref=ref,
            kind=SessionHistoryKind.SUMMARY,
            background=background,
            char_count=len(dumps_json(background)),
            child_refs=child_refs,
        )
        return (summary_item, *items[split:])


def _turn_item_from_record(record: SessionRecord) -> SessionHistoryItem:
    if record.kind is not SessionHistoryKind.TURN:
        raise SessionInvariantError(
            f"Session orphan is not a Turn record: {record.ref}"
        )
    background = record.content.get("background")
    completion = record.content.get("completion")
    if not isinstance(background, dict) or not isinstance(completion, dict):
        raise SessionInvariantError(
            f"Session Turn record is missing committed content: {record.ref}"
        )
    turn_id = completion.get("turn_id")
    if not isinstance(turn_id, str):
        raise SessionInvariantError(
            f"Session Turn record has an invalid turn id: {record.ref}"
        )
    expected_ref = f"session:turn/{turn_id}"
    if expected_ref != record.ref:
        raise SessionInvariantError(
            f"Session Turn record identity does not match completion: {record.ref}"
        )
    _action_projection_from_record(record)
    stable_background = to_json_object(background)
    return SessionHistoryItem(
        item_id=turn_id,
        ref=record.ref,
        kind=SessionHistoryKind.TURN,
        background=stable_background,
        char_count=len(dumps_json(stable_background)),
    )


def _turn_background(
    summary: TurnSummary,
    *,
    projection: TurnActionProjection,
    output: JsonObject | None,
    exhausted: bool,
    action_names: frozenset[str],
    max_actions: int,
) -> JsonObject:
    asks = tuple(
        text
        for item in summary.inputs
        if isinstance((text := item.get("text")), str) and text
    )
    answer = ""
    references: list[str] = []
    if output is not None:
        raw_answer = output.get("text")
        if isinstance(raw_answer, str):
            answer = raw_answer
        raw_references = output.get("references", [])
        if isinstance(raw_references, list):
            references = [item for item in raw_references if isinstance(item, str)]
    return to_json_object(
        {
            "kind": "session_turn",
            "ref": f"session:turn/{summary.turn_id}",
            "turn_id": summary.turn_id,
            "user_ask": _bounded_asks(asks),
            "actions": _project_action_history(
                projection,
                action_names=action_names,
                max_actions=max_actions,
            ),
            "answer": _clip(answer, 1800),
            "references": references,
            "exhausted": exhausted,
            "action_outcome_summary": projection.outcome_summary(),
            "trace_summary": summary.trace_summary,
            "trace_digest": summary.trace_digest,
        }
    )


def _summary_background(
    ref: str,
    children: tuple[SessionHistoryItem, ...],
) -> JsonObject:
    turns: list[JsonObject] = []
    for item in children:
        if item.kind is SessionHistoryKind.SUMMARY:
            turns.append(
                {
                    "kind": "summary",
                    "ref": item.ref,
                    "child_count": len(item.child_refs),
                }
            )
            continue
        turns.append(
            {
                "kind": "turn",
                "ref": item.ref,
                "user_ask": _clip_json_text(item.background.get("user_ask"), 360),
                "answer": _clip_json_text(item.background.get("answer"), 520),
            }
        )
    return to_json_object({
        "kind": "session_summary",
        "ref": ref,
        "child_refs": [item.ref for item in children],
        "turns": turns,
    })


def _summary_split(
    items: tuple[SessionHistoryItem, ...],
    *,
    min_recent_turns: int,
) -> int:
    remaining_turns = min_recent_turns
    split = len(items)
    for index in range(len(items) - 1, -1, -1):
        if items[index].kind is not SessionHistoryKind.TURN:
            continue
        if remaining_turns == 0:
            break
        split = index
        remaining_turns -= 1
    return split


def _history_page_limits(
    settings: SessionSettings,
    *,
    max_chars: int | None,
    max_entries: int | None,
    scope: str,
) -> tuple[int, int, int, int]:
    requested_chars = (
        settings.history_page_max_chars if max_chars is None else max_chars
    )
    if (
        isinstance(requested_chars, bool)
        or not isinstance(requested_chars, int)
        or requested_chars <= 0
    ):
        raise SessionHistoryRequestError(
            SessionHistoryFailureReason.INVALID_MAX_CHARS,
            "Session history max_chars must be positive",
            constraint={"max_chars": requested_chars},
            scope=scope,
        )
    requested_entries = (
        settings.history_page_max_entries if max_entries is None else max_entries
    )
    if (
        isinstance(requested_entries, bool)
        or not isinstance(requested_entries, int)
        or requested_entries <= 0
    ):
        raise SessionHistoryRequestError(
            SessionHistoryFailureReason.INVALID_MAX_ENTRIES,
            "Session history max_entries must be positive",
            constraint={"max_entries": requested_entries},
            scope=scope,
        )
    return (
        requested_chars,
        min(requested_chars, settings.history_page_max_chars),
        requested_entries,
        min(requested_entries, settings.history_page_max_entries),
    )


def _inspect_cursor(
    value: JsonObject | None,
    *,
    ref: str | None,
    revision: int,
) -> JsonPageCursor:
    scope = "session.history.inspect"
    raw_revision: object | None = None
    page_value: object = value
    if isinstance(value, dict) and "revision" in value:
        raw_revision = value.get("revision")
        page_value = {
            key: item
            for key, item in value.items()
            if key != "revision"
        }
    if ref is not None and raw_revision is not None:
        raise SessionHistoryRequestError(
            SessionHistoryFailureReason.INVALID_CURSOR,
            "Only the active Session head cursor may carry a revision",
            constraint={"field": "revision", "ref": ref},
            scope=scope,
        )
    try:
        cursor = JsonPageCursor.from_json(page_value)
    except JsonPageError as exc:
        raise _session_page_error(exc, ref=ref, scope=scope) from exc
    if ref is not None:
        return cursor
    if raw_revision is not None and (
        isinstance(raw_revision, bool) or not isinstance(raw_revision, int)
    ):
        raise SessionHistoryRequestError(
            SessionHistoryFailureReason.INVALID_CURSOR,
            "Session head cursor revision must be an integer",
            constraint={"field": "revision"},
            scope=scope,
        )
    continuation = cursor.entry_index > 0 or cursor.char_offset > 0
    if continuation and raw_revision is None:
        raise SessionHistoryRequestError(
            SessionHistoryFailureReason.INVALID_CURSOR,
            "Session head continuation requires its revision",
            constraint={"field": "revision"},
            scope=scope,
        )
    if raw_revision is not None and raw_revision != revision:
        raise SessionHistoryRequestError(
            SessionHistoryFailureReason.REVISION_CHANGED,
            "Session head revision changed; restart inspection",
            constraint={
                "expected_revision": raw_revision,
                "actual_revision": revision,
            },
            scope=scope,
        )
    return cursor


def _bind_page_revision(page: JsonObject, revision: int) -> None:
    for name in ("cursor", "next_cursor"):
        raw = page.get(name)
        if isinstance(raw, dict):
            raw["revision"] = revision


def _summary_children_from_record(
    record: SessionRecord,
) -> tuple[SessionHistoryItem, ...]:
    if record.kind is not SessionHistoryKind.SUMMARY:
        raise SessionInvariantError(
            f"Session history node is not a Summary record: {record.ref}"
        )
    raw_children = record.content.get("children")
    if not isinstance(raw_children, list) or len(raw_children) < 2:
        raise SessionInvariantError(
            f"Session summary record has invalid children: {record.ref}"
        )
    children: list[SessionHistoryItem] = []
    try:
        for raw in raw_children:
            if not isinstance(raw, dict):
                raise SessionContractError("Session summary child must be an object")
            children.append(SessionHistoryItem.from_json(to_json_object(raw)))
    except SessionContractError as exc:
        raise SessionInvariantError(
            f"Session summary record has invalid children: {record.ref}"
        ) from exc
    child_refs = [child.ref for child in children]
    if record.content.get("child_refs") != child_refs:
        raise SessionInvariantError(
            f"Session summary record child refs are inconsistent: {record.ref}"
        )
    return tuple(children)


def _recall_record(
    record: SessionRecord,
    *,
    max_chars: int,
    max_entries: int,
    requested_max_chars: int,
    requested_max_entries: int,
    cursor: JsonPageCursor,
) -> JsonObject:
    completion = record.content.get("completion")
    if not isinstance(completion, dict):
        raise SessionInvariantError(
            f"Session Turn record is missing completion: {record.ref}"
        )
    trace_value = completion.get("trace")
    if not isinstance(trace_value, list) or any(
        not isinstance(entry, dict) for entry in trace_value
    ):
        raise SessionInvariantError(
            f"Session Turn record has an invalid trace: {record.ref}"
        )
    base: JsonObject = {
        "source": {
            "owner": "session",
            "ref": record.ref,
            "record_kind": record.kind.value,
            "turn_id": completion.get("turn_id"),
            "trace_digest": completion.get("trace_digest"),
            "trace_entry_count": len(trace_value),
        }
    }
    try:
        return page_json_sequence(
            tuple(
                to_json_object(entry)
                for entry in trace_value
                if isinstance(entry, dict)
            ),
            base=base,
            item_field="trace",
            cursor_unit="trace_entry",
            cursor=cursor,
            max_chars=max_chars,
            max_entries=max_entries,
            requested_max_chars=requested_max_chars,
            requested_max_entries=requested_max_entries,
        )
    except JsonPageError as exc:
        raise _session_page_error(
            exc,
            ref=record.ref,
            scope="session.history.recall",
        ) from exc


def _project_action_history(
    projection: TurnActionProjection,
    *,
    action_names: frozenset[str],
    max_actions: int,
) -> list[JsonObject]:
    values: list[JsonObject] = []
    for item in projection.details:
        if item.action_name not in action_names:
            continue
        detail = item.to_json()
        failure = detail.pop("failure", None)
        if isinstance(failure, dict):
            detail["failure"] = {
                key: failure[key]
                for key in ("reason", "scope", "disposition")
                if key in failure
            }
        values.append(detail)
    return values[-max_actions:]


def _action_projection_from_record(record: SessionRecord) -> TurnActionProjection:
    if record.kind is not SessionHistoryKind.TURN:
        raise SessionHistoryRequestError(
            SessionHistoryFailureReason.WRONG_RECORD_KIND,
            "Session action history is only available for Turn records",
            constraint={"ref": record.ref, "record_kind": record.kind.value},
            scope="session.history.actions",
        )
    completion = record.content.get("completion")
    stored = record.content.get("action_history")
    if not isinstance(completion, dict) or not isinstance(stored, dict):
        raise SessionInvariantError(
            f"Session Turn record is missing Action history: {record.ref}"
        )
    trace_value = completion.get("trace")
    digest = completion.get("trace_digest")
    if not isinstance(trace_value, list) or any(
        not isinstance(item, dict) for item in trace_value
    ):
        raise SessionInvariantError(
            f"Session Turn record has an invalid trace: {record.ref}"
        )
    if not isinstance(digest, str):
        raise SessionInvariantError(
            f"Session Turn record has an invalid trace digest: {record.ref}"
        )
    projection = project_turn_actions(
        tuple(to_json_object(item) for item in trace_value if isinstance(item, dict)),
        expected_digest=digest,
    )
    if projection.summary_json() != to_json_object(stored):
        raise SessionInvariantError(
            f"Session Turn Action history projection is inconsistent: {record.ref}"
        )
    return projection


def _load_requested_record(
    store: SessionStore,
    ref: str,
    *,
    scope: str,
) -> SessionRecord:
    if not _is_valid_history_ref(ref):
        raise SessionHistoryRequestError(
            SessionHistoryFailureReason.INVALID_REF,
            "Invalid Session history ref",
            constraint={"ref": ref} if isinstance(ref, str) else {},
            scope=scope,
        )
    try:
        return store.load_record(ref)
    except SessionContractError as exc:
        raise SessionHistoryRequestError(
            SessionHistoryFailureReason.UNKNOWN_REF,
            "Unknown Session history ref",
            constraint={"ref": ref},
            scope=scope,
        ) from exc


def _is_valid_history_ref(ref: object) -> bool:
    if not isinstance(ref, str):
        return False
    prefixes = tuple(f"session:{kind.value}/" for kind in SessionHistoryKind)
    prefix = next((value for value in prefixes if ref.startswith(value)), None)
    if prefix is None:
        return False
    record_id = ref[len(prefix) :]
    return bool(record_id) and all(
        char in "abcdefghijklmnopqrstuvwxyz0123456789_-" for char in record_id
    )


def _session_page_error(
    error: JsonPageError,
    *,
    ref: str | None,
    scope: str,
) -> SessionHistoryRequestError:
    reason_map = {
        JsonPageFailureReason.INVALID_CURSOR: SessionHistoryFailureReason.INVALID_CURSOR,
        JsonPageFailureReason.CURSOR_OUT_OF_RANGE: (
            SessionHistoryFailureReason.CURSOR_OUT_OF_RANGE
        ),
        JsonPageFailureReason.ENTRY_OFFSET_OUT_OF_RANGE: (
            SessionHistoryFailureReason.ENTRY_OFFSET_OUT_OF_RANGE
        ),
        JsonPageFailureReason.ENTRY_DIGEST_MISMATCH: (
            SessionHistoryFailureReason.ENTRY_DIGEST_MISMATCH
        ),
        JsonPageFailureReason.PAGE_BUDGET_TOO_SMALL: (
            SessionHistoryFailureReason.PAGE_BUDGET_TOO_SMALL
        ),
    }
    reason = reason_map.get(error.reason)
    if reason is None:
        raise SessionInvariantError("Unexpected Session paging failure") from error
    constraint: JsonObject = {**error.constraint}
    if ref is not None:
        constraint = {"ref": ref, **constraint}
    return SessionHistoryRequestError(
        reason,
        str(error),
        constraint=constraint,
        scope=scope,
    )

def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _bounded_asks(asks: tuple[str, ...]) -> list[str]:
    selected: list[str] = []
    used = 0
    for text in reversed(asks):
        clipped = _clip(text, 1200)
        if selected and used + len(clipped) > 2400:
            break
        selected.append(clipped)
        used += len(clipped)
    selected.reverse()
    return selected


def _clip_json_text(value: object, limit: int) -> str:
    if isinstance(value, str):
        return _clip(value, limit)
    if isinstance(value, list):
        return _clip("\n".join(item for item in value if isinstance(item, str)), limit)
    return ""
