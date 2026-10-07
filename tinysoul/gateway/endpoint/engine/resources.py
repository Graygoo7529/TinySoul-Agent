"""Resource browser adapters over the existing scoped owner services."""

from enum import StrEnum

from tinysoul.infra.json import JsonObject
from tinysoul.infra.paging import PageOptions
from tinysoul.kernel.retrieval.contracts import (
    ModelStep,
    RetrievalRequest,
    SearchContext,
    SearchFailure,
    SearchFailureKind,
)
from tinysoul.kernel.retrieval.requests import parse_retrieval_request
from tinysoul.plugins.home.services import HomeService
from tinysoul.plugins.memory.services import MemoryService
from tinysoul.plugins.workspace.services import WorkspaceService

from .context import EndpointEngineContext


class SearchSpace(StrEnum):
    HOME = "home"
    MEMORY = "memory"
    WORKSPACE = "workspace"


class EndpointResourcesEngine:
    def __init__(self, context: EndpointEngineContext) -> None:
        self._context = context

    async def home_catalog(
        self, *, view: str, space: str | None, query: str | None, page: PageOptions
    ) -> JsonObject:
        return await self._context.services.registry.get(HomeService).catalog(
            view=view, space=space, query=query, page=page
        )

    async def home_content(
        self, ref: str, *, view: str, page: PageOptions
    ) -> JsonObject:
        return await self._context.services.registry.get(HomeService).content(
            ref, view=view, page=page
        )

    async def home_changes(self, page: PageOptions) -> JsonObject:
        return await self._context.services.registry.get(HomeService).changes(page)

    async def home_diff(self, ref: str, page: PageOptions) -> JsonObject:
        return await self._context.services.registry.get(HomeService).diff(ref, page)

    async def memory_catalog(
        self, *, kind: str | None, query: str | None, page: PageOptions
    ) -> JsonObject:
        return await self._context.services.registry.get(MemoryService).catalog(
            kind=kind, query=query, page=page
        )

    async def memory_document(self, ref: str, page: PageOptions) -> JsonObject:
        return (
            await self._context.services.registry.get(MemoryService).inspect(
                ref, continuation=page.continuation, max_chars=page.max_chars
            )
        ).to_json()

    async def search(self, space: SearchSpace, parameters: JsonObject) -> JsonObject:
        registry = self._context.services.registry
        service = (
            registry.get(HomeService)
            if space is SearchSpace.HOME
            else registry.get(MemoryService)
            if space is SearchSpace.MEMORY
            else registry.get(WorkspaceService)
        )
        if not service.retrieval_policies:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "This SDK source has no retrieval policy",
            )
        request = parse_retrieval_request(parameters, service.retrieval_policies[0])
        if isinstance(request, RetrievalRequest) and any(
            isinstance(step, ModelStep) and step.context is not SearchContext.NONE
            for step in request.steps
        ):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST, "SDK searches require context=none"
            )
        return (await service.search(request)).to_json()
