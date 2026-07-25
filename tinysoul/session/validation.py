"""Single Session-owned validator for immutable business records."""

from __future__ import annotations

from .errors import SessionInvariantError
from .models import (
    SessionRecord,
    SessionSummaryRecord,
    SessionTurnRecord,
    summary_ref,
)


class SessionRecordValidator:
    """Validate record identity and immutable facts at every ownership boundary."""

    def validate(self, record: SessionRecord) -> SessionRecord:
        if isinstance(record, SessionTurnRecord):
            return self.validate_turn(record)
        if isinstance(record, SessionSummaryRecord):
            return self.validate_summary(record)
        raise SessionInvariantError("Unknown Session record type")

    def validate_turn(self, record: SessionTurnRecord) -> SessionTurnRecord:
        if record.ref != f"session:turn/{record.turn_id}":
            raise SessionInvariantError(
                f"Session Turn identity is inconsistent: {record.ref}"
            )
        return record

    def validate_summary(
        self,
        record: SessionSummaryRecord,
    ) -> SessionSummaryRecord:
        expected = summary_ref(record.day, record.child_refs)
        if record.ref != expected:
            raise SessionInvariantError(
                f"Session Summary identity is inconsistent: {record.ref}"
            )
        return record


_VALIDATOR = SessionRecordValidator()


def validate_record(record: SessionRecord) -> SessionRecord:
    return _VALIDATOR.validate(record)


def validate_turn_record(record: SessionRecord) -> SessionTurnRecord:
    if not isinstance(record, SessionTurnRecord):
        raise SessionInvariantError(f"Session record is not a Turn: {record.ref}")
    return _VALIDATOR.validate_turn(record)


def validate_summary_record(record: SessionRecord) -> SessionSummaryRecord:
    if not isinstance(record, SessionSummaryRecord):
        raise SessionInvariantError(f"Session record is not a Summary: {record.ref}")
    return _VALIDATOR.validate_summary(record)
