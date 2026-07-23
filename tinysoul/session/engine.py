"""Session history facade and bounded background projection."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from threading import RLock

from tinysoul.context import SessionBackgroundItem, SessionBackgroundSnapshot, TurnSummary
from tinysoul.infra.json import JsonObject, JsonValue, dumps_json, to_json_object
from tinysoul.infra.paging import (
    JsonPageCursor,
    JsonPageError,
    page_json_sequence,
)
from tinysoul.loop.day import BusinessDay

from .action_history import TurnActionProjection, project_turn_actions
from .config import SessionSettings
from .errors import SessionContractError, SessionInvariantError
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

    def inspect_history(self) -> JsonObject:
        with self._lock:
            self._last_reconcile_result = self._reconcile_current()
            manifest = self._require_manifest()
            return {
                "revision": manifest.revision,
                "day": manifest.day,
                "estimated_chars": sum(item.char_count for item in manifest.items),
                "items": [
                    {
                        "item_id": item.item_id,
                        "ref": item.ref,
                        "kind": item.kind.value,
                        "char_count": item.char_count,
                        "child_refs": list(item.child_refs),
                    }
                    for item in manifest.items
                ],
            }

    def recall_history(
        self,
        ref: str,
        *,
        max_chars: int | None = None,
        cursor: JsonObject | None = None,
    ) -> JsonObject:
        with self._lock:
            self._require_manifest()
            self._last_reconcile_result = self._reconcile_current()
            requested = self._settings.recall_max_chars if max_chars is None else max_chars
            if isinstance(requested, bool) or requested <= 0:
                raise SessionContractError("Session recall max_chars must be positive")
            try:
                page_cursor = JsonPageCursor.from_json(cursor)
            except JsonPageError as exc:
                raise SessionContractError(str(exc)) from exc
            limit = min(requested, self._settings.recall_max_chars)
            record = self._store.load_record(ref)
            return _recall_record(
                record,
                max_chars=limit,
                requested_max_chars=requested,
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
            if not ref.startswith("session:turn/"):
                raise SessionContractError(
                    "Session action history requires a session:turn ref"
                )
            if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
                raise SessionContractError(
                    "Session action history cursor must be non-negative"
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
                raise SessionContractError(
                    "Session action history max_items must be positive"
                )
            record = self._store.load_record(ref)
            projection = _action_projection_from_record(record)
            completion = record.content.get("completion")
            if not isinstance(completion, dict):
                raise SessionInvariantError(
                    f"Session Turn record is missing completion: {ref}"
                )
            if cursor > len(projection.details):
                raise SessionContractError(
                    "Session action history cursor exceeds the detail count"
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


def _recall_record(
    record: SessionRecord,
    *,
    max_chars: int,
    requested_max_chars: int,
    cursor: JsonPageCursor,
) -> JsonObject:
    background = record.content.get("background")
    first_page = cursor.entry_index == 0 and cursor.char_offset == 0
    base: JsonObject = {
        "ref": record.ref,
        "kind": record.kind.value,
    }
    if first_page:
        base["background"] = (
            to_json_object(background) if isinstance(background, dict) else {}
        )
    if record.kind is SessionHistoryKind.SUMMARY:
        refs = record.content.get("child_refs", [])
        if not isinstance(refs, list) or any(
            not isinstance(ref, str) or not ref for ref in refs
        ):
            raise SessionInvariantError(
                f"Session summary record has invalid child refs: {record.ref}"
            )
        base["source"] = {
            "owner": "session",
            "ref": record.ref,
            "record_kind": record.kind.value,
            "child_count": len(refs),
        }
        return _page_session_values(
            tuple(refs),
            base=base,
            item_field="child_refs",
            cursor_unit="summary_child",
            cursor=cursor,
            max_chars=max_chars,
            requested_max_chars=requested_max_chars,
        )
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
    base["source"] = {
        "owner": "session",
        "ref": record.ref,
        "record_kind": record.kind.value,
        "turn_id": completion.get("turn_id"),
        "trace_digest": completion.get("trace_digest"),
        "trace_entry_count": len(trace_value),
    }
    return _page_session_values(
        tuple(to_json_object(entry) for entry in trace_value if isinstance(entry, dict)),
        base=base,
        item_field="trace",
        cursor_unit="trace_entry",
        cursor=cursor,
        max_chars=max_chars,
        requested_max_chars=requested_max_chars,
    )


def _page_session_values(
    values: tuple[JsonValue, ...],
    *,
    base: JsonObject,
    item_field: str,
    cursor_unit: str,
    cursor: JsonPageCursor,
    max_chars: int,
    requested_max_chars: int,
) -> JsonObject:
    try:
        return page_json_sequence(
            values,
            base=base,
            item_field=item_field,
            cursor_unit=cursor_unit,
            cursor=cursor,
            max_chars=max_chars,
            requested_max_chars=requested_max_chars,
        )
    except JsonPageError as exc:
        raise SessionContractError(str(exc)) from exc


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
        raise SessionContractError(
            "Session action history is only available for Turn records"
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
