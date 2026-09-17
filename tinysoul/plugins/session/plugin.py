"""Session's public service and fixed source projection."""

from collections.abc import Callable

from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.registration import PluginDeclaration, Service

from .engine import SessionEngine
from .projection import SessionViewSource, session_segment_registration
from .services import SessionService


def declare_session(
    session: SessionEngine, *, source: SessionViewSource | None = None,
    source_day: Callable[[], CalendarDay] | None = None,
) -> PluginDeclaration:
    service = SessionService(source or session)
    return PluginDeclaration(
        "session", services=(Service(SessionService, service),),
        segments=(session_segment_registration(service, source_day=source_day),),
    )
