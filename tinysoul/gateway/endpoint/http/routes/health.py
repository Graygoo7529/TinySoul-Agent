"""Process liveness route."""

from fastapi import FastAPI

from tinysoul.infra.json import JsonObject


def register_health_routes(app: FastAPI) -> None:
    @app.get("/v1/health")
    async def health() -> JsonObject:
        return {"ok": True}
