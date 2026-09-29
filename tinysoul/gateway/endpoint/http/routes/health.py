"""Process liveness route."""

from fastapi import FastAPI

from tinysoul.infra.json import JsonObject
from ..schemas import HealthResponse


def register_health_routes(app: FastAPI) -> None:
    @app.get("/v2/health", response_model=HealthResponse)
    async def health() -> JsonObject:
        return {"ok": True}
