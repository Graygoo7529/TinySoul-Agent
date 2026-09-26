"""Effective Home operations and separately granted actual Home review."""

from tinysoul.infra.services import ScopedService, ServiceScope
from typing import Self
from tinysoul.kernel.retrieval.operations import SearchSession, SelectionInput
from tinysoul.kernel.retrieval.contracts import (
    RetrievalRequest,
    SearchPage,
    SearchFailure,
    SearchFailureKind,
)
from .engine import AgentHomeEngine


class HomeService(ScopedService[AgentHomeEngine]):
    def __init__(
        self,
        owner: AgentHomeEngine,
        scope: ServiceScope = ServiceScope(),
        *,
        queries: SearchSession | None = None,
    ) -> None:
        super().__init__(owner, scope)
        self.default_background_links = scope.local(owner.default_background_links)
        self.loadable_background_links = scope.local(owner.loadable_background_links)
        self.skill_metadata = scope.local(owner.skill_metadata)
        self._queries = queries
        self.retrieval_policies = queries.retrieval_policies if queries else ()
        self.search = scope.remote(self._search)
        self.inspect = scope.local(owner.inspect)
        self.read_top = scope.local(owner.read_top)
        self.read_resource = scope.local(owner.read_resource)
        self.resource_exists = scope.local(owner.resource_exists)
        self.guidance_for_domain = scope.local(owner.guidance_for_domain)
        self.guidance_for_action = scope.local(owner.guidance_for_action)
        self.write_resource = scope.local(owner.write_resource)
        self.patch_resource = scope.local(owner.patch_resource)
        self.delete_resource = scope.local(owner.delete_resource)
        self.write_top = scope.local(owner.write_top)
        self.patch_top = scope.local(owner.patch_top)
        self.delete_top = scope.local(owner.delete_top)
        self.write_prompt_mount = scope.local(owner.write_prompt_mount)
        self.patch_prompt_mount = scope.local(owner.patch_prompt_mount)
        self.actual_top_links = scope.local(owner.actual_top_links)
        self.actual_default_background_links = scope.local(
            owner.actual_default_background_links
        )
        self.actual_skill_metadata = scope.local(owner.actual_skill_metadata)
        self.read_actual_top = scope.local(owner.read_actual_top)

    def _bind(self, scope: ServiceScope) -> Self:
        return type(self)(self._owner, scope, queries=self._queries)

    async def _search(
        self, request: RetrievalRequest | str, *, inputs: SelectionInput = SelectionInput()
    ) -> SearchPage:
        if self._queries is None:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Home search has not been assembled for this service",
            )
        return await self._queries.search(request, inputs=inputs)


class HomeReviewService(ScopedService[AgentHomeEngine]):
    def __init__(
        self, owner: AgentHomeEngine, scope: ServiceScope = ServiceScope()
    ) -> None:
        super().__init__(owner, scope)
        self.review_snapshot = scope.local(owner.review_snapshot)
        self.resolve_review = scope.local(owner.resolve_review)
