"""Read-only Session projection, without record or day lifecycle operations."""

from tinysoul.infra.services import ScopedService, ServiceScope
from typing import Protocol
from tinysoul.infra.time import CalendarDay
from tinysoul.infra.json import JsonObject
from .background import SessionBackgroundSnapshot


class SessionViewSource(Protocol):
    def background_snapshot(self, day: CalendarDay) -> SessionBackgroundSnapshot: ...

    def inspect(self, ref: str | None = None, *, action: str | None = None,
                continuation: str | None = None, expected_revision: int | None = None) -> JsonObject: ...


class SessionService(ScopedService[SessionViewSource]):
    def __init__(self, owner: SessionViewSource, scope: ServiceScope = ServiceScope()) -> None:
        super().__init__(owner, scope)
        self.background_snapshot = scope.local(owner.background_snapshot)
        self.inspect = scope.local(owner.inspect)
