"""App module errors."""

from __future__ import annotations


class AppError(Exception):
    """Base class for app module errors."""


class AppContractError(AppError):
    """Raised when app public boundaries receive invalid input."""


class AppInvariantError(AppError):
    """Raised when app internal state is inconsistent."""


class AppOutputError(AppError):
    """Raised at the app boundary after an output sink has failed."""
