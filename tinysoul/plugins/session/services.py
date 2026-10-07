"""Read-only Session projection, without record or day lifecycle operations."""

from typing import Protocol, Self

from tinysoul.infra.services import ScopedService, ServiceScope
from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.retrieval.contracts import (
    RetrievalRequest,
    SearchFailure,
    SearchFailureKind,
    SearchPage,
)
from tinysoul.kernel.retrieval.disclosure import InspectPage
from tinysoul.kernel.retrieval.operations import SearchSession

from .engine import SessionEngine
from .views import SessionView
from .views.background import SessionBackgroundSnapshot


class SessionOrganizeService(ScopedService[SessionEngine]):
    """User profile's narrow write capability; not exported through the SDK."""

    def __init__(
        self, owner: SessionEngine, scope: ServiceScope = ServiceScope()
    ) -> None:
        super().__init__(owner, scope)
        self.organize = scope.local(owner.organize)
        self.annotation_snapshot = scope.local(owner.annotation_snapshot)


class SessionViewSource(Protocol):
    def snapshot_view(self, day: CalendarDay) -> SessionView: ...

    def background_snapshot(self, day: CalendarDay) -> SessionBackgroundSnapshot: ...

    def inspect(
        self,
        ref: str | None = None,
        *,
        action: str | None = None,
        query: str | None = None,
        continuation: str | None = None,
        expected_revision: int | None = None,
    ) -> InspectPage: ...


class SessionService(ScopedService[SessionViewSource]):
    def __init__(
        self,
        owner: SessionViewSource,
        scope: ServiceScope = ServiceScope(),
        *,
        queries: SearchSession | None = None,
    ) -> None:
        super().__init__(owner, scope)
        self.snapshot_view = scope.local(owner.snapshot_view)
        self.background_snapshot = scope.local(owner.background_snapshot)
        self.inspect = scope.local(owner.inspect)
        self._queries = queries
        self.search = scope.remote(self._search)

    def _bind(self, scope: ServiceScope) -> Self:
        return type(self)(self._owner, scope, queries=self._queries)

    async def _search(self, request: RetrievalRequest | str) -> SearchPage:
        if self._queries is None:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Session search is available through its SDK query scope or core.context.search",
            )
        return await self._queries.search(request)
