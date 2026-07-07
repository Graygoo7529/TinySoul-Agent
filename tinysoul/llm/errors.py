"""LLM module semantic errors."""

from __future__ import annotations


class LLMError(Exception):
    """Base class for LLM module boundary errors."""


class LLMContractError(LLMError):
    """Raised when a caller or configuration violates the LLM contract."""


class LLMInvariantError(LLMError):
    """Raised when an internal LLM invariant is violated."""
