"""Session's public service and fixed source projection."""

from collections.abc import Callable

from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.registration import PluginDeclaration, Service

from .engine import SessionEngine
from .projection import SessionViewSource, session_segment_registration


def declare_session(
    session: SessionEngine, *, source: SessionViewSource | None = None,
    source_day: Callable[[], CalendarDay] | None = None,
) -> PluginDeclaration:
    return PluginDeclaration(
        "session", services=(Service(SessionEngine, session),),
        segments=(session_segment_registration(source or session, source_day=source_day),),
    )
