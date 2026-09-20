"""Structured Turn and Turn-owned Job routes."""

from fastapi import FastAPI

from tinysoul.infra.json import JsonObject, to_json_object

from ...engine import EndpointEngine
from ..schemas import (
    TurnCreateRequest,
    TurnGrantRequest,
    TurnInputRequest,
    TurnReplyRequest,
)


def register_turn_routes(app: FastAPI, engine: EndpointEngine) -> None:
    @app.post("/v2/turns", status_code=202)
    async def create_turn(body: TurnCreateRequest) -> JsonObject:
        return await engine.runtime.create_turn(
            kind=body.kind,
            text=body.text,
            target_day=body.target_day,
            instructions=body.instructions,
            metadata=to_json_object(body.metadata),
            command_id=body.command_id,
        )

    @app.get("/v2/turns/{turn_id}")
    async def get_turn(turn_id: str) -> JsonObject:
        return await engine.runtime.get_turn(turn_id)

    @app.post("/v2/turns/{turn_id}/input")
    async def append_input(turn_id: str, body: TurnInputRequest) -> JsonObject:
        return await engine.runtime.append_input(turn_id, body.text, body.input_id)

    @app.post("/v2/turns/{turn_id}/reply")
    async def reply(turn_id: str, body: TurnReplyRequest) -> JsonObject:
        return await engine.runtime.reply(turn_id, body.question_id, body.response)

    @app.post("/v2/turns/{turn_id}/grant")
    async def grant(turn_id: str, body: TurnGrantRequest) -> JsonObject:
        return await engine.runtime.grant(turn_id, body.request_id, body.count)

    @app.post("/v2/turns/{turn_id}/cancel")
    async def cancel(turn_id: str) -> JsonObject:
        return await engine.runtime.cancel(turn_id)

    @app.get("/v2/turns/{turn_id}/jobs")
    async def jobs(turn_id: str) -> JsonObject:
        return await engine.runtime.jobs(turn_id)

    @app.post("/v2/turns/{turn_id}/jobs/{job_id}/stop")
    async def stop_job(turn_id: str, job_id: str) -> JsonObject:
        return await engine.runtime.stop_job(turn_id, job_id)
