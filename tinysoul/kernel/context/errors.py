"""Context internal error types."""

from __future__ import annotations

from enum import StrEnum

from tinysoul.infra.continuation import ContinuationError, ContinuationFailureReason
from tinysoul.infra.json import JsonObject, to_json_object


class ContextError(Exception):
    """Base class for context module internal exceptions."""


class ContextContractError(ContextError):
    """Raised when a context public boundary receives invalid inputs."""


class ContextInspectFailureReason(StrEnum):
    """Stable request-local failures for Context segment navigation."""

    INVALID_REF = "invalid_ref"
    UNKNOWN_REF = "unknown_ref"
    REF_NOT_LEAF = "ref_not_leaf"
    WRONG_RECORD_KIND = "wrong_record_kind"
    INVALID_CONTINUATION = "invalid_continuation"
    PAGE_BUDGET_TOO_SMALL = "page_budget_too_small"
    QUERY_UNSUPPORTED = "query_unsupported"
    INVALID_QUERY = "invalid_query"


class ContextInspectRequestError(ContextContractError):
    """A caller can correct one Context inspection request."""

    def __init__(
        self,
        reason: ContextInspectFailureReason,
        message: str,
        *,
        constraint: JsonObject | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.scope = "context.inspect"
        self.constraint = to_json_object(constraint or {})


class ContextInvariantError(ContextError):
    """Raised when an internal context invariant is broken."""


class ContextBudgetError(ContextError):
    """Raised when a composed message stack exceeds the context budget."""

    def __init__(
        self,
        message: str,
        *,
        estimated_chars: int,
        estimated_image_bytes: int = 0,
        max_image_bytes: int | None = None,
        section_usage: JsonObject | None = None,
    ) -> None:
        super().__init__(message)
        self.estimated_chars = estimated_chars
        self.estimated_image_bytes = estimated_image_bytes
        self.max_image_bytes = max_image_bytes
        self.section_usage = to_json_object(section_usage or {})


def inspect_continuation_error(
    error: ContinuationError,
    *,
    ref: str,
) -> ContextInspectRequestError:
    reason_map = {
        ContinuationFailureReason.INVALID: (
            ContextInspectFailureReason.INVALID_CONTINUATION
        ),
        ContinuationFailureReason.MISMATCH: (
            ContextInspectFailureReason.INVALID_CONTINUATION
        ),
        ContinuationFailureReason.OUT_OF_RANGE: (
            ContextInspectFailureReason.INVALID_CONTINUATION
        ),
        ContinuationFailureReason.CONTENT_CHANGED: (
            ContextInspectFailureReason.INVALID_CONTINUATION
        ),
        ContinuationFailureReason.BUDGET_TOO_SMALL: (
            ContextInspectFailureReason.PAGE_BUDGET_TOO_SMALL
        ),
    }
    reason = reason_map.get(error.reason)
    if reason is None:
        raise ContextInvariantError(
            "Unexpected Context continuation failure"
        ) from error
    return ContextInspectRequestError(
        reason,
        str(error),
        constraint={"ref": ref},
    )
