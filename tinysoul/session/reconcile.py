"""Session record graph validation and orphan Turn discovery."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import SessionInvariantError
from .models import (
    SessionManifest,
    SessionRecord,
    SessionRecordKind,
    SessionSummaryRecord,
    SessionTurnRecord,
)
from .store import SessionStore
from .validation import validate_record


@dataclass(frozen=True)
class SessionReconcileScan:
    orphan_turn_records: tuple[SessionTurnRecord, ...]
    orphan_summary_refs: tuple[str, ...]


@dataclass(frozen=True)
class SessionReconcileResult:
    revision: int
    adopted_turn_refs: tuple[str, ...] = ()
    orphan_summary_refs: tuple[str, ...] = ()


class SessionReconciler:
    """Validate one immutable graph and find records outside its active roots."""

    def __init__(self, store: SessionStore) -> None:
        self._store = store

    def scan(self, manifest: SessionManifest) -> SessionReconcileScan:
        records = self._records()
        for record in records.values():
            validate_record(record)
            if record.day != manifest.day:
                raise SessionInvariantError(
                    f"Session record belongs to another day: {record.ref}"
                )
        reachable: set[str] = set()
        visiting: set[str] = set()
        for ref in manifest.refs:
            self._visit(
                ref,
                records=records,
                reachable=reachable,
                visiting=visiting,
            )
        turns = tuple(
            record
            for record in records.values()
            if isinstance(record, SessionTurnRecord) and record.ref not in reachable
        )
        turns = tuple(sorted(turns, key=lambda item: (item.recorded_at_ns, item.ref)))
        summaries = tuple(
            sorted(
                record.ref
                for record in records.values()
                if isinstance(record, SessionSummaryRecord)
                and record.ref not in reachable
            )
        )
        return SessionReconcileScan(
            orphan_turn_records=turns,
            orphan_summary_refs=summaries,
        )

    def validate_graph(self, manifest: SessionManifest) -> None:
        self.scan(manifest)

    def _records(self) -> dict[str, SessionRecord]:
        records = {
            record.ref: record
            for kind in (SessionRecordKind.TURN, SessionRecordKind.SUMMARY)
            for record in self._store.list_records(kind)
        }
        return records

    def _visit(
        self,
        ref: str,
        *,
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
            raise SessionInvariantError(f"Session graph contains a cycle: {ref}")
        if ref in reachable:
            raise SessionInvariantError(
                f"Session graph contains a duplicate reachable ref: {ref}"
            )
        visiting.add(ref)
        reachable.add(ref)
        if isinstance(record, SessionSummaryRecord):
            for child_ref in record.child_refs:
                self._visit(
                    child_ref,
                    records=records,
                    reachable=reachable,
                    visiting=visiting,
                )
        visiting.remove(ref)
