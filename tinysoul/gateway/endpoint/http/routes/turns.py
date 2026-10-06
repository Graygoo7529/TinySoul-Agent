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
    @app.get(
        "/v2/requests",
        response_model=TurnListResponse,
        response_model_exclude_unset=True,
    )
    async def list_turns() -> JsonObject:
        return await engine.runtime.list_requests()

    @app.post(
        "/v2/requests",
        status_code=202,
        response_model=CommandReceiptResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def create_turn(body: TurnCreateRequest) -> JsonObject:
        return await engine.runtime.create_request(
            kind=body.kind,
            text=body.text,
            target_day=body.target_day,
            instructions=body.instructions,
            metadata=to_json_object(body.metadata),
            command_id=body.command_id,
        )

    @app.get(
        "/v2/requests/{request_id}",
        response_model=TurnResponse,
        response_model_exclude_unset=True,
    )
    async def get_turn(request_id: str) -> JsonObject:
        return await engine.runtime.get_request(request_id)

    @app.post(
        "/v2/requests/{request_id}/input",
        response_model=CommandReceiptResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def append_input(request_id: str, body: TurnInputRequest) -> JsonObject:
        return await engine.runtime.append_input(request_id, body.text, body.input_id)

    @app.post(
        "/v2/requests/{request_id}/reply",
        response_model=CommandReceiptResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def reply(request_id: str, body: TurnReplyRequest) -> JsonObject:
        return await engine.runtime.reply(
            request_id, body.question_id, body.answer.to_answer()
        )

    @app.post(
        "/v2/requests/{request_id}/grant",
        response_model=CommandReceiptResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def grant(request_id: str, body: TurnGrantRequest) -> JsonObject:
        return await engine.runtime.grant(
            request_id, body.budget_request_id, body.count
        )

    @app.post(
        "/v2/requests/{request_id}/cancel",
        response_model=CommandReceiptResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def cancel(request_id: str) -> JsonObject:
        return await engine.runtime.cancel(request_id)

    @app.get(
        "/v2/requests/{request_id}/jobs",
        response_model=JobListResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def jobs(request_id: str) -> JsonObject:
        return await engine.runtime.jobs(request_id)

    @app.post(
        "/v2/requests/{request_id}/jobs/{job_id}/stop",
        response_model=JobDetailResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def stop_job(request_id: str, job_id: str) -> JsonObject:
        return await engine.runtime.stop_job(request_id, job_id)
