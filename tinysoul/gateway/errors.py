"""Failures owned by process and project gateway adapters."""


class GatewayError(Exception):
    """Base gateway boundary failure."""


class ProjectInitializationError(GatewayError):
    """Project initialization or reset could not finish."""


class ProjectInstanceError(GatewayError):
    """The project process lease could not be acquired."""


class ConsoleOutputError(GatewayError):
    """The terminal renderer received an invalid contract."""
