"""Runtime status and command routes."""

from fastapi import FastAPI

from tinysoul.infra.json import JsonObject

from ...engine import EndpointEngine
from ..schemas import (
    CommandReceiptResponse,
    RuntimeStatusResponse,
)


def register_runtime_routes(app: FastAPI, engine: EndpointEngine) -> None:
    @app.get(
        "/v2/status", response_model=RuntimeStatusResponse, response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def status() -> JsonObject:
        return await engine.runtime.status()

    @app.post(
        "/v2/restart",
        status_code=202,
        response_model=CommandReceiptResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def restart() -> JsonObject:
        return await engine.runtime.restart()
