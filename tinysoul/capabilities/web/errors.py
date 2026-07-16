"""Web capability failures."""

from __future__ import annotations

from tinysoul.infra import JsonObject


class WebError(Exception):
    """Base Web capability error."""


class WebContractError(WebError):
    """Raised when a caller violates the Web service contract."""


class WebWorkerProtocolError(WebError):
    """Raised when staged Web worker output violates the host protocol."""


class WebProcessingError(WebError):
    """A stable Web failure suitable for ActionResult mapping."""

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


class WebProcessTimeout(WebError):
    """Raised when a controlled Web worker times out or is cancelled."""

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason
