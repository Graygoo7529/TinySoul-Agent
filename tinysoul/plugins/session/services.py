"""Read-only Session projection, without record or day lifecycle operations."""

from tinysoul.infra.services import ScopedService, ServiceScope
from typing import Protocol
from tinysoul.infra.time import CalendarDay
from tinysoul.infra.json import JsonObject
from .views.background import SessionBackgroundSnapshot
from .views import SessionView
from .engine import SessionEngine


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
    ) -> JsonObject: ...


class SessionService(ScopedService[SessionViewSource]):
    def __init__(
        self, owner: SessionViewSource, scope: ServiceScope = ServiceScope()
    ) -> None:
        super().__init__(owner, scope)
        self.snapshot_view = scope.local(owner.snapshot_view)
        self.background_snapshot = scope.local(owner.background_snapshot)
        self.inspect = scope.local(owner.inspect)
