"""Context internal error types."""

from __future__ import annotations

from enum import StrEnum

from tinysoul.infra.json import JsonObject, to_json_object


class ContextError(Exception):
    """Base class for context module internal exceptions."""


class ContextContractError(ContextError):
    """Raised when a context public boundary receives invalid inputs."""


class ContextTraceFailureReason(StrEnum):
    """Stable request-local failures for Context trace navigation."""

    INVALID_REF = "invalid_ref"
    UNKNOWN_REF = "unknown_ref"
    REF_NOT_LEAF = "ref_not_leaf"
    INVALID_CURSOR = "invalid_cursor"
    CURSOR_OUT_OF_RANGE = "cursor_out_of_range"
    ENTRY_OFFSET_OUT_OF_RANGE = "entry_offset_out_of_range"
    ENTRY_DIGEST_MISMATCH = "entry_digest_mismatch"
    PAGE_BUDGET_TOO_SMALL = "page_budget_too_small"
    INVALID_MAX_CHARS = "invalid_max_chars"
    INVALID_MAX_ENTRIES = "invalid_max_entries"


class ContextTraceRequestError(ContextContractError):
    """A caller can correct one Context trace request."""

    def __init__(
        self,
        reason: ContextTraceFailureReason,
        message: str,
        *,
        constraint: JsonObject | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.scope = "context.trace"
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
