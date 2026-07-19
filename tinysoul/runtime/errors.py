"""Runtime module errors."""

from __future__ import annotations


class RuntimeModuleError(Exception):
    """Base class for runtime module contract and invariant failures."""


class RuntimeContractError(RuntimeModuleError):
    """Raised when a runtime public contract is violated."""


class RuntimeInvariantError(RuntimeModuleError):
    """Raised when runtime assembled state violates an internal invariant."""


class RuntimeGatewayError(RuntimeModuleError):
    """Raised when an external application gateway rejects a request."""


class RuntimeInputBlockedError(RuntimeGatewayError):
    """Raised when application state blocks ordinary user input."""
