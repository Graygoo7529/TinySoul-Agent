"""Reflection module errors."""

from __future__ import annotations


class ReflectionError(Exception):
    """Base class for maintenance module failures."""


class ReflectionContractError(ReflectionError):
    """Raised when a maintenance boundary receives invalid input."""


class ReflectionInvariantError(ReflectionError):
    """Raised when persisted maintenance facts are inconsistent."""


class ReflectionTaskExecutionError(ReflectionError):
    """Raised when one task fails at a known recoverable module boundary."""
