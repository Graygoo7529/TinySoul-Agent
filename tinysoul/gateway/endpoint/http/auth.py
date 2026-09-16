"""HTTP and WebSocket authentication helpers."""

from __future__ import annotations

from hmac import compare_digest

from tinysoul.runtime import ObservationLevel

from ..config import EndpointSettings
from ..errors import EndpointRequestError


def bearer_valid(value: str, settings: EndpointSettings) -> bool:
    return compare_digest(value, f"Bearer {settings.token}")


def websocket_token_valid(value: object, settings: EndpointSettings) -> bool:
    return isinstance(value, str) and compare_digest(value, settings.token)


def websocket_cursor(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EndpointRequestError(
            status_code=422,
            code="websocket.invalid_auth",
            message=f"WebSocket {name} must be a non-negative integer.",
        )
    return value


def websocket_mode(value: object) -> ObservationLevel:
    if not isinstance(value, str):
        raise EndpointRequestError(
            status_code=422,
            code="websocket.invalid_auth",
            message="WebSocket mode is invalid.",
        )
    try:
        return ObservationLevel(value)
    except ValueError as exc:
        raise EndpointRequestError(
            status_code=422,
            code="websocket.invalid_auth",
            message="WebSocket mode is invalid.",
        ) from exc
