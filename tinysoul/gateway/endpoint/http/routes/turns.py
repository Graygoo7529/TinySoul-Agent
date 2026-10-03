"""Structured Turn and Turn-owned Job routes."""

from fastapi import FastAPI

from tinysoul.infra.json import JsonObject, to_json_object

from ...engine import EndpointEngine
from ..schemas import (
    CommandReceiptResponse,
    JobDetailResponse,
    JobListResponse,
    TurnCreateRequest,
    TurnGrantRequest,
    TurnInputRequest,
    TurnReplyRequest,
    TurnResponse,
    TurnListResponse,
)


def register_turn_routes(app: FastAPI, engine: EndpointEngine) -> None:
    @app.get("/v2/turns", response_model=TurnListResponse, response_model_exclude_unset=True)
    async def list_turns() -> JsonObject:
        return await engine.runtime.list_turns()

    @app.post(
        "/v2/turns",
        status_code=202,
        response_model=CommandReceiptResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def create_turn(body: TurnCreateRequest) -> JsonObject:
        return await engine.runtime.create_turn(
            kind=body.kind,
            text=body.text,
            target_day=body.target_day,
            instructions=body.instructions,
            metadata=to_json_object(body.metadata),
            command_id=body.command_id,
        )

    @app.get(
        "/v2/turns/{turn_id}",
        response_model=TurnResponse,
        response_model_exclude_unset=True,
    )
    async def get_turn(turn_id: str) -> JsonObject:
        return await engine.runtime.get_turn(turn_id)

    @app.post(
        "/v2/turns/{turn_id}/input",
        response_model=CommandReceiptResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def append_input(turn_id: str, body: TurnInputRequest) -> JsonObject:
        return await engine.runtime.append_input(turn_id, body.text, body.input_id)

    @app.post(
        "/v2/turns/{turn_id}/reply",
        response_model=CommandReceiptResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def reply(turn_id: str, body: TurnReplyRequest) -> JsonObject:
        return await engine.runtime.reply(
            turn_id, body.question_id, body.answer.to_answer()
        )

    @app.post(
        "/v2/turns/{turn_id}/grant",
        response_model=CommandReceiptResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def grant(turn_id: str, body: TurnGrantRequest) -> JsonObject:
        return await engine.runtime.grant(turn_id, body.request_id, body.count)

    @app.post(
        "/v2/turns/{turn_id}/cancel",
        response_model=CommandReceiptResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def cancel(turn_id: str) -> JsonObject:
        return await engine.runtime.cancel(turn_id)

    @app.get(
        "/v2/turns/{turn_id}/jobs",
        response_model=JobListResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def jobs(turn_id: str) -> JsonObject:
        return await engine.runtime.jobs(turn_id)

    @app.post(
        "/v2/turns/{turn_id}/jobs/{job_id}/stop",
        response_model=JobDetailResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def stop_job(turn_id: str, job_id: str) -> JsonObject:
        return await engine.runtime.stop_job(turn_id, job_id)
