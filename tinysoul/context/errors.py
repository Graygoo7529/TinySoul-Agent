"""Context internal error types."""

from __future__ import annotations

from tinysoul.infra.json import JsonObject, to_json_object


class ContextError(Exception):
    """Base class for context module internal exceptions."""


class ContextContractError(ContextError):
    """Raised when a context public boundary receives invalid inputs."""


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
