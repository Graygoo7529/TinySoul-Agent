"""Resource capability failures."""

from __future__ import annotations

from tinysoul.infra.json import JsonObject


class ResourceError(Exception):
    """Base Resource capability error."""


class ResourceContractError(ResourceError):
    """Raised when a Resource caller violates the service contract."""


class ResourceInvariantError(ResourceError):
    """Raised when Resource internal state violates an invariant."""


class ResourceProcessingError(ResourceError):
    """A stable local conversion failure suitable for ActionResult mapping."""

    def __init__(
        self,
        message: str,
        *,
        reason: str,
        payload: JsonObject | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.payload = payload or {}


class ResourceProcessTimeout(ResourceError):
    """Raised when the controlled document worker times out or is cancelled."""

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason

