"""Action internal error types."""

from __future__ import annotations


class ActionError(Exception):
    """Base class for action module internal exceptions."""


class ActionContractError(ActionError):
    """Raised when an action public boundary receives invalid inputs."""


class ActionInvariantError(ActionError):
    """Raised when an internal action invariant is broken."""
