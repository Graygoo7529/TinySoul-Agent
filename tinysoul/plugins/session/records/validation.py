"""Session-owned validation of immutable Turn identity."""

from ..errors import SessionInvariantError
from .models import SessionTurnRecord


def validate_turn_record(record: SessionTurnRecord) -> SessionTurnRecord:
    if not isinstance(record, SessionTurnRecord):
        raise SessionInvariantError("Session record must be a Turn")
    if record.ref != f"session:turn/{record.turn_id}":
        raise SessionInvariantError("Session Turn identity is inconsistent")
    return record
