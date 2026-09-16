"""Stable HTTP error serialization for the Endpoint application."""

from __future__ import annotations

from fastapi.responses import JSONResponse

from tinysoul.infra.json import JsonObject


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: JsonObject | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
            }
        },
    )
