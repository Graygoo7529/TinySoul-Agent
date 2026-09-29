"""Read-only Turn, Context and committed Session projections."""

from fastapi import FastAPI, Query

from tinysoul.infra.paging import PageOptions
from tinysoul.infra.time import CalendarDay

from ...engine import EndpointEngine
from ..schemas import (
    ContextMessagesResponse,
    ContextOverviewResponse,
    InteractionPageResponse,
    JobDetailResponse,
    JobOutputResponse,
    PageResponse,
)


def register_inspection_routes(app: FastAPI, engine: EndpointEngine) -> None:
    @app.get("/v2/subagent")
    async def subagent():
        return await engine.inspection.subagent_status()

    @app.get("/v2/expand/servers")
    async def expand_servers(continuation: str | None = None, limit: int = 30):
        return await engine.inspection.expand_servers(PageOptions(continuation, limit))

    @app.get("/v2/expand/tools")
    async def expand_tools(
        server_id: str,
        tool_name: str | None = None,
        continuation: str | None = None,
        limit: int = 30,
        max_chars: int = 16000,
    ):
        return await engine.inspection.expand_tools(
            server_id,
            tool_name=tool_name,
            page=PageOptions(continuation, limit, max_chars),
        )

    @app.post("/v2/expand/servers/{server_id}/refresh")
    async def expand_refresh(server_id: str):
        return await engine.inspection.expand_refresh(server_id)

    @app.get(
        "/v2/turns/{turn_id}/jobs/{job_id}",
        response_model=JobDetailResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def job(turn_id: str, job_id: str):
        return await engine.inspection.job_detail(turn_id, job_id)

    @app.get(
        "/v2/turns/{turn_id}/jobs/{job_id}/output",
        response_model=JobOutputResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def output(
        turn_id: str,
        job_id: str,
        continuation: str | None = None,
        max_chars: int = 16000,
    ):
        return await engine.inspection.job_output(
            turn_id, job_id, PageOptions(continuation, max_chars=max_chars)
        )

    @app.get("/v2/days")
    async def days(before: str | None = None, limit: int = Query(30, ge=1, le=100)):
        return await engine.inspection.days(
            before=CalendarDay.parse(before) if before else None, limit=limit
        )

    @app.get(
        "/v2/turns/{turn_id}/interactions",
        response_model=InteractionPageResponse,
        response_model_exclude_unset=True,
    )
    async def interactions(
        turn_id: str,
        continuation: str | None = None,
        limit: int = 30,
        max_chars: int = 16000,
    ):
        return await engine.inspection.turn_interactions(
            turn_id, PageOptions(continuation, limit, max_chars)
        )

    @app.get(
        "/v2/turns/{turn_id}/context",
        response_model=ContextOverviewResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def context(turn_id: str):
        return await engine.inspection.context_overview(turn_id)

    @app.get(
        "/v2/turns/{turn_id}/context/segments/{segment_id}",
        response_model=ContextMessagesResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def segment(
        turn_id: str,
        segment_id: str,
        continuation: str | None = None,
        max_chars: int = 16000,
    ):
        return await engine.inspection.context_segment(
            turn_id, segment_id, PageOptions(continuation, max_chars=max_chars)
        )

    @app.get(
        "/v2/turns/{turn_id}/context/inspect",
        response_model=PageResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def inspect_context(
        turn_id: str,
        ref: str,
        query: str | None = None,
        continuation: str | None = None,
    ):
        return await engine.inspection.context_inspect(
            turn_id, ref, query=query, continuation=continuation
        )

    @app.get("/v2/session/turns")
    async def turns(
        day: str | None = None,
        continuation: str | None = None,
        limit: int = 30,
        max_chars: int = 16000,
    ):
        return await engine.inspection.session_turns(
            CalendarDay.parse(day) if day else None,
            PageOptions(continuation, limit, max_chars),
        )

    @app.get(
        "/v2/session/turns/{turn_id}",
        response_model=InteractionPageResponse,
        response_model_exclude_unset=True,
    )
    async def session_turn(
        turn_id: str, day: str, continuation: str | None = None, max_chars: int = 16000
    ):
        return await engine.inspection.session_interactions(
            turn_id,
            CalendarDay.parse(day),
            PageOptions(continuation, max_chars=max_chars),
        )

    @app.get(
        "/v2/session/map",
        response_model=PageResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def session_map(day: str | None = None, continuation: str | None = None):
        return await engine.inspection.session_inspect(
            CalendarDay.parse(day) if day else None,
            ref="session:map",
            continuation=continuation,
        )

    @app.get(
        "/v2/session/inspect",
        response_model=PageResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def inspect_session(
        day: str,
        ref: str | None = None,
        query: str | None = None,
        continuation: str | None = None,
    ):
        return await engine.inspection.session_inspect(
            CalendarDay.parse(day), ref=ref, query=query, continuation=continuation
        )
