"""Session's public service and fixed source projection."""

from collections.abc import Callable
from functools import partial

from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.registration import PluginDeclaration, Service
from tinysoul.kernel.context import ContextTurnFacts

from .engine import SessionEngine
from .projection import session_segment_registration
from .services import SessionService, SessionViewSource, SessionOrganizeService
from .actions import register_session_actions
from .projection import SessionTurnCompletionHandler
from .runtime_bridge import RuntimeSessionBridge


def declare_session(
    session: SessionEngine,
    *,
    source: SessionViewSource | None = None,
    source_day: Callable[[], CalendarDay] | None = None,
    record_completed: bool = False,
    facts: Callable[[], ContextTurnFacts] | None = None,
) -> PluginDeclaration:
    service = SessionService(source or session)
    writer = SessionOrganizeService(session) if facts is not None else None
    return PluginDeclaration(
        "session",
        services=(
            Service(SessionService, service),
            *((Service(SessionOrganizeService, writer),) if writer is not None else ()),
        ),
        segments=(
            session_segment_registration(
                service, source_day=source_day, writer=writer, facts=facts
            ),
        ),
        actions=partial(register_session_actions, service=writer, facts=facts)
        if writer is not None and facts is not None
        else None,
        recorder=SessionTurnCompletionHandler(
            session, runtime_bridge=RuntimeSessionBridge()
        )
        if record_completed
        else None,
    )
