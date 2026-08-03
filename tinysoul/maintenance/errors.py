"""Maintenance module errors."""

from __future__ import annotations


class MaintenanceError(Exception):
    """Base class for maintenance module failures."""


class MaintenanceContractError(MaintenanceError):
    """Raised when a maintenance boundary receives invalid input."""


class MaintenanceInvariantError(MaintenanceError):
    """Raised when persisted maintenance facts are inconsistent."""
