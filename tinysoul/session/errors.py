"""Session module errors."""

from __future__ import annotations

from enum import StrEnum

from tinysoul.infra.json import JsonObject, to_json_object


class SessionError(Exception):
    """Base Session module error."""


class SessionContractError(SessionError):
    """Invalid Session boundary input."""


class SessionHistoryFailureReason(StrEnum):
    """Stable request-local failures for Session history navigation."""

    INVALID_REF = "invalid_ref"
    UNKNOWN_REF = "unknown_ref"
    WRONG_RECORD_KIND = "wrong_record_kind"
    INVALID_CURSOR = "invalid_cursor"
    REVISION_CHANGED = "revision_changed"
    CURSOR_OUT_OF_RANGE = "cursor_out_of_range"
    ENTRY_OFFSET_OUT_OF_RANGE = "entry_offset_out_of_range"
    ENTRY_DIGEST_MISMATCH = "entry_digest_mismatch"
    PAGE_BUDGET_TOO_SMALL = "page_budget_too_small"
    INVALID_MAX_CHARS = "invalid_max_chars"
    INVALID_MAX_ENTRIES = "invalid_max_entries"
    INVALID_MAX_ITEMS = "invalid_max_items"


class SessionHistoryRequestError(SessionContractError):
    """A caller can correct one Session history request."""

    def __init__(
        self,
        reason: SessionHistoryFailureReason,
        message: str,
        *,
        constraint: JsonObject | None = None,
        scope: str = "session.history",
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.scope = scope
        self.constraint = to_json_object(constraint or {})


class SessionInvariantError(SessionError):
    """Broken Session internal invariant."""


class SessionIOError(SessionError):
    """Session persistence failure."""
