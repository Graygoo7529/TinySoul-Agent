"""Context internal error types."""

from __future__ import annotations


class ContextError(Exception):
    """Base class for context module internal exceptions."""


class ContextContractError(ContextError):
    """Raised when a context public boundary receives invalid inputs."""


class ContextInvariantError(ContextError):
    """Raised when an internal context invariant is broken."""


class ContextBudgetError(ContextError):
    """Raised when a composed message stack exceeds the context budget."""

    def __init__(self, message: str, *, estimated_chars: int, max_chars: int) -> None:
        super().__init__(message)
        self.estimated_chars = estimated_chars
        self.max_chars = max_chars
