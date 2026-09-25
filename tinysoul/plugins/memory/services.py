"""Memory capabilities selected by the consumer's execution scenario."""

from tinysoul.infra.services import ScopedService, ServiceScope
from tinysoul.kernel.retrieval.operations import SearchSession, SelectionInput
from tinysoul.kernel.retrieval.contracts import (
    SearchRequest,
    SearchPage,
    SearchFailure,
    SearchFailureKind,
)
from typing import Self
from .engine import MemoryEngine


class MemoryReadService(ScopedService[MemoryEngine]):
    """Memory discovery and Context projection without persistence changes."""

    def __init__(
        self,
        owner: MemoryEngine,
        scope: ServiceScope = ServiceScope(),
        *,
        queries: SearchSession | None = None,
    ) -> None:
        super().__init__(owner, scope)
        self.active_day = scope.local(owner.active_day)
        self.read_active = scope.local(owner.read_active)
        self.inspect = scope.local(owner.inspect)
        self._queries = queries
        self.search_policies = queries.policies if queries else ()
        self.search = scope.remote(self._search)
        self.latest_daily_before = scope.local(owner.latest_daily_before)

    def _bind(self, scope: ServiceScope) -> Self:
        return type(self)(self._owner, scope, queries=self._queries)

    async def _search(
        self, request: SearchRequest | str, *, inputs: SelectionInput = SelectionInput()
    ) -> SearchPage:
        if self._queries is None:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Memory search has not been assembled for this service",
            )
        return await self._queries.search(request, inputs=inputs)


class MemoryService(MemoryReadService):
    """Normal work can additionally patch active memory."""

    def __init__(
        self,
        owner: MemoryEngine,
        scope: ServiceScope = ServiceScope(),
        *,
        queries: SearchSession | None = None,
    ) -> None:
        super().__init__(owner, scope, queries=queries)
        self.patch_active = scope.local(owner.patch_active)


class MemoryKnowledgeService(ScopedService[MemoryEngine]):
    """Persistent writes granted to Memory Reflection only."""

    def __init__(
        self, owner: MemoryEngine, scope: ServiceScope = ServiceScope()
    ) -> None:
        super().__init__(owner, scope)
        self.write_document = scope.local(owner.write_document)
        self.write_markdown = scope.local(owner.write_markdown)
