"""Home/Memory read projections and owner-scoped Search requests."""

from typing import Literal

from fastapi import Body, FastAPI

from tinysoul.infra.json import JsonObject
from tinysoul.infra.paging import PageOptions
from tinysoul.infra.time import CalendarDay

from ...engine import EndpointEngine
from ...engine.resources import SearchSpace
from ..schemas import PageResponse, ResourceResolveResponse, SearchResponse


def register_resource_routes(app: FastAPI, engine: EndpointEngine) -> None:
    @app.get(
        "/v2/resources/resolve",
        response_model=ResourceResolveResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def resolve(
        ref: str,
        origin_ref: str | None = None,
        day: str | None = None,
        turn_id: str | None = None,
        view: Literal["actual", "effective"] = "effective",
    ):
        return await engine.inspection.resolve_resource(
            ref,
            origin_ref=origin_ref,
            day=CalendarDay.parse(day) if day else None,
            turn_id=turn_id,
            view=view,
        )

    @app.get(
        "/v2/home/catalog",
        response_model=PageResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def home_catalog(
        view: Literal["actual", "effective"] = "effective",
        space: str | None = None,
        query: str | None = None,
        continuation: str | None = None,
        limit: int = 30,
        max_chars: int = 16000,
    ):
        return await engine.resources.home_catalog(
            view=view,
            space=space,
            query=query,
            page=PageOptions(continuation, limit, max_chars),
        )

    @app.get(
        "/v2/home/content",
        response_model=PageResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def home_content(
        ref: str,
        view: Literal["actual", "effective"] = "effective",
        continuation: str | None = None,
        max_chars: int = 16000,
    ):
        return await engine.resources.home_content(
            ref, view=view, page=PageOptions(continuation, max_chars=max_chars)
        )

    @app.get("/v2/home/changes")
    async def home_changes(
        continuation: str | None = None, limit: int = 30, max_chars: int = 16000
    ):
        return await engine.resources.home_changes(
            PageOptions(continuation, limit, max_chars)
        )

    @app.get("/v2/home/diff")
    async def home_diff(
        ref: str, continuation: str | None = None, max_chars: int = 16000
    ):
        return await engine.resources.home_diff(
            ref, PageOptions(continuation, max_chars=max_chars)
        )

    @app.get(
        "/v2/memory/catalog",
        response_model=PageResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def memory_catalog(
        kind: str | None = None,
        query: str | None = None,
        continuation: str | None = None,
        limit: int = 30,
        max_chars: int = 16000,
    ):
        return await engine.resources.memory_catalog(
            kind=kind, query=query, page=PageOptions(continuation, limit, max_chars)
        )

    @app.get(
        "/v2/memory/document",
        response_model=PageResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def memory_document(
        ref: str, continuation: str | None = None, max_chars: int = 16000
    ):
        return await engine.resources.memory_document(
            ref, PageOptions(continuation, max_chars=max_chars)
        )

    @app.get("/v2/memory/active")
    async def memory_active(
        day: str | None = None, continuation: str | None = None, max_chars: int = 16000
    ):
        return await engine.inspection.memory_active(
            CalendarDay.parse(day) if day else None,
            PageOptions(continuation, max_chars=max_chars),
        )

    @app.post(
        "/v2/home/search",
        response_model=SearchResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def home_search(body: JsonObject = Body()):
        return await engine.resources.search(SearchSpace.HOME, body)

    @app.post(
        "/v2/memory/search",
        response_model=SearchResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def memory_search(body: JsonObject = Body()):
        return await engine.resources.search(SearchSpace.MEMORY, body)

    @app.post(
        "/v2/workspace/search",
        response_model=SearchResponse,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def workspace_search(body: JsonObject = Body()):
        return await engine.resources.search(SearchSpace.WORKSPACE, body)
