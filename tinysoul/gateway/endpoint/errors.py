"""Endpoint module boundary errors."""

from __future__ import annotations

from tinysoul.infra.json import JsonObject, to_json_object


class EndpointError(Exception):
    """Base class for Endpoint module failures."""


class EndpointContractError(EndpointError):
    """Invalid Endpoint configuration or public API usage."""


class EndpointInvariantError(EndpointError):
    """Endpoint internal state is inconsistent."""


class EndpointServerError(EndpointError):
    """The local HTTP server could not start or stop cleanly."""


class EndpointRequestError(EndpointError):
    """Stable request-local failure rendered by the HTTP adapter."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: JsonObject | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = to_json_object(details or {})

    def to_json(self) -> JsonObject:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }
