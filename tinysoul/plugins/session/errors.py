"""Session module errors."""

from __future__ import annotations

from enum import StrEnum

from tinysoul.infra.json import JsonObject, to_json_object


class SessionError(Exception):
    """Base Session module error."""


class SessionContractError(SessionError):
    """Invalid Session boundary input."""


class SessionInspectFailureReason(StrEnum):
    """Stable request-local failures for Session heap inspection."""

    INVALID_REF = "invalid_ref"
    UNKNOWN_REF = "unknown_ref"
    WRONG_RECORD_KIND = "wrong_record_kind"
    INVALID_CONTINUATION = "invalid_continuation"
    PAGE_BUDGET_TOO_SMALL = "page_budget_too_small"


class SessionInspectRequestError(SessionContractError):
    """A caller can correct one Session inspect request."""

    def __init__(
        self,
        reason: SessionInspectFailureReason,
        message: str,
        *,
        constraint: JsonObject | None = None,
        scope: str = "session.inspect",
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.scope = scope
        self.constraint = to_json_object(constraint or {})


class SessionInvariantError(SessionError):
    """Broken Session internal invariant."""


class SessionIOError(SessionError):
    """Session persistence failure."""
