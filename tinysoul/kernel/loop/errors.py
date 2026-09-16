"""Loop module errors."""

from __future__ import annotations


class LoopError(Exception):
    """Base class for loop module errors."""


class LoopContractError(LoopError):
    """Raised when a loop public boundary receives invalid input."""


class LoopInvariantError(LoopError):
    """Raised when loop internal state is inconsistent."""
