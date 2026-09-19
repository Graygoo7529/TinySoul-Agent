"""Validate the immutable Turn index and recover committed orphan records."""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import SessionInvariantError
from .models import SessionManifest, SessionTurnRecord
from .store import SessionStore
from .validation import validate_turn_record


@dataclass(frozen=True)
class SessionReconcileScan:
    orphan_turn_records: tuple[SessionTurnRecord, ...]


@dataclass(frozen=True)
class SessionReconcileResult:
    revision: int
    adopted_turn_refs: tuple[str, ...] = ()


class SessionReconciler:
    """Recover facts written before an interrupted manifest replacement."""

    def __init__(self, store: SessionStore) -> None:
        self._store = store

    def scan(self, manifest: SessionManifest) -> SessionReconcileScan:
        records = {
            record.ref: validate_turn_record(record)
            for record in self._store.list_records()
        }
        for record in records.values():
            if record.day != manifest.day:
                raise SessionInvariantError("Session record belongs to another day")
        indexed = set(manifest.refs)
        if len(indexed) != len(manifest.refs) or not indexed.issubset(records):
            raise SessionInvariantError(
                "Session index contains duplicate or missing records"
            )
        orphans = tuple(
            sorted(
                (record for ref, record in records.items() if ref not in indexed),
                key=lambda record: (record.recorded_at_ns, record.ref),
            )
        )
        return SessionReconcileScan(orphan_turn_records=orphans)
