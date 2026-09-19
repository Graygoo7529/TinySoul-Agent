"""Reflection availability and request routes."""

from fastapi import FastAPI

from tinysoul.infra.json import JsonObject, to_json_object

from ...engine import EndpointEngine
from ..schemas import ReflectionRequest


def register_reflection_routes(app: FastAPI, engine: EndpointEngine) -> None:
    @app.get("/v1/reflection")
    async def reflection_status(before: str | None = None) -> JsonObject:
        return await engine.reflection.status(before=before)

    @app.post("/v1/reflection", status_code=202)
    async def request_reflection(body: ReflectionRequest) -> JsonObject:
        return await engine.reflection.request(
            kind=body.kind,
            target_day=body.target_day,
            instructions=body.instructions,
            metadata=to_json_object(body.metadata),
            command_id=body.command_id,
        )
