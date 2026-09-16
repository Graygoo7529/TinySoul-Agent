"""Memory module errors."""

from __future__ import annotations


class MemoryError(Exception):
    """Base class for Memory module errors."""


class MemoryContractError(MemoryError):
    """Raised when a caller violates a Memory contract."""


class MemoryInvariantError(MemoryError):
    """Raised when persisted Memory cannot satisfy module invariants."""


class MemoryIOError(MemoryError):
    """Raised when Memory filesystem operations fail."""

