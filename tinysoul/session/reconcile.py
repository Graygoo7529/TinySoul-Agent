"""Session record reachability and orphan reconciliation support."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.infra.json import dumps_json, to_json_object

from .errors import SessionError, SessionInvariantError
from .models import (
    SessionHistoryItem,
    SessionHistoryKind,
    SessionManifest,
    SessionRecord,
)
from .store import SessionStore
from .validation import validate_summary_record, validate_turn_record


@dataclass(frozen=True)
class _SessionReconcileScan:
    """Immutable records left unreachable after graph validation."""

    orphan_turn_records: tuple[SessionRecord, ...]
    orphan_summary_refs: tuple[str, ...]


@dataclass(frozen=True)
class SessionReconcileResult:
    """Committed reconciliation outcome exposed by SessionEngine."""

    revision: int
    adopted_turn_refs: tuple[str, ...] = ()
    orphan_summary_refs: tuple[str, ...] = ()


class SessionReconciler:
    """Validate a manifest graph and discover uncommitted immutable records."""

    def __init__(self, store: SessionStore) -> None:
        self._store = store

    def scan(self, manifest: SessionManifest) -> _SessionReconcileScan:
        turns = {
            record.ref: record
            for record in self._store.list_records(SessionHistoryKind.TURN)
        }
        summaries = {
            record.ref: record
            for record in self._store.list_records(SessionHistoryKind.SUMMARY)
        }
        records = {**turns, **summaries}
        for record in turns.values():
            validate_turn_record(record)
        for record in summaries.values():
            validate_summary_record(record)
        for record in records.values():
            record_day = record.content.get("day")
            if record_day is not None and record_day != manifest.day:
                raise SessionInvariantError(
                    f"Session record belongs to a different day: {record.ref}"
                )
        reachable: set[str] = set()
        visiting: set[str] = set()
        try:
            for item in manifest.items:
                self._visit(
                    item.ref,
                    expected=item,
                    records=records,
                    reachable=reachable,
                    visiting=visiting,
                )
        except SessionError as exc:
            if isinstance(exc, SessionInvariantError):
                raise
            raise SessionInvariantError(
                f"Session manifest graph is invalid: {exc}"
            ) from exc

        orphan_turns = tuple(
            sorted(
                (record for ref, record in turns.items() if ref not in reachable),
                key=lambda record: (record.recorded_at_ns, record.ref),
            )
        )
        orphan_summaries = tuple(
            sorted(ref for ref in summaries if ref not in reachable)
        )
        return _SessionReconcileScan(
            orphan_turn_records=orphan_turns,
            orphan_summary_refs=orphan_summaries,
        )

    def _visit(
        self,
        ref: str,
        *,
        expected: SessionHistoryItem | None,
        records: dict[str, SessionRecord],
        reachable: set[str],
        visiting: set[str],
    ) -> None:
        record = records.get(ref)
        if record is None:
            raise SessionInvariantError(
                f"Session manifest references a missing record: {ref}"
            )
        if ref in visiting:
            raise SessionInvariantError(f"Session summary graph contains a cycle: {ref}")
        if expected is not None:
            self._validate_item(expected, record)
        if ref in reachable:
            return
        visiting.add(ref)
        reachable.add(ref)
        if record.kind is SessionHistoryKind.SUMMARY:
            children = _summary_children(record)
            for child in children:
                self._visit(
                    child.ref,
                    expected=child,
                    records=records,
                    reachable=reachable,
                    visiting=visiting,
                )
        visiting.remove(ref)

    @staticmethod
    def _validate_item(item: SessionHistoryItem, record: SessionRecord) -> None:
        if item.kind is not record.kind:
            raise SessionInvariantError(
                f"Session item kind does not match its record: {item.ref}"
            )
        expected_ref = f"session:{item.kind.value}/{item.item_id}"
        if item.ref != expected_ref:
            raise SessionInvariantError(
                f"Session item identity does not match its ref: {item.ref}"
            )
        background = record.content.get("background")
        if (
            not isinstance(background, dict)
            or to_json_object(background) != item.background
        ):
            raise SessionInvariantError(
                f"Session item background does not match its record: {item.ref}"
            )
        if len(dumps_json(item.background)) != item.char_count:
            raise SessionInvariantError(
                f"Session item char_count does not match its background: {item.ref}"
            )
        if record.kind is SessionHistoryKind.TURN:
            completion = record.content.get("completion")
            turn_id = (
                completion.get("turn_id")
                if isinstance(completion, dict)
                else None
            )
            if turn_id != item.item_id or item.child_refs:
                raise SessionInvariantError(
                    f"Session Turn record identity is inconsistent: {item.ref}"
                )
        if record.kind is SessionHistoryKind.SUMMARY:
            child_refs = tuple(child.ref for child in _summary_children(record))
            if child_refs != item.child_refs:
                raise SessionInvariantError(
                    f"Session summary child refs do not match its item: {item.ref}"
                )


def _summary_children(record: SessionRecord) -> tuple[SessionHistoryItem, ...]:
    return validate_summary_record(record).children
