"""Agent Home module errors."""

from __future__ import annotations


class AgentHomeError(Exception):
    """Base class for Agent Home module errors."""


class AgentHomeContractError(AgentHomeError):
    """Raised when callers violate Agent Home contracts."""


class AgentHomeInvariantError(AgentHomeError):
    """Raised when Agent Home internal invariants are broken."""


class AgentHomeIOError(AgentHomeError):
    """Raised when Agent Home filesystem operations fail at the module boundary."""

