"""Session's public service and fixed source projection."""

from collections.abc import Callable
from functools import partial
from dataclasses import dataclass
from pathlib import Path

from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.registration import (
    PluginProfileExtension, Service, PluginGeneration, PluginConfig,
    PluginServiceExport, ServiceLifetime, GenerationBuildContext, ProfileBuildContext, ProfileKind,
)
from tinysoul.kernel.context import ContextTurnFacts

from .engine import SessionEngine
from .projection import session_segment_registration
from .services import SessionService, SessionViewSource, SessionOrganizeService
from .actions import register_session_actions
from .projection import SessionTurnCompletionHandler
from .runtime_bridge import RuntimeSessionBridge
from .config import SessionSettings, parse_session_settings
from .errors import SessionError


@dataclass(frozen=True)
class SessionStorage:
    root: Path


@dataclass(frozen=True)
class SessionProfileSource:
    source: SessionViewSource
    source_day: Callable[[], CalendarDay]


@dataclass(frozen=True)
class SessionPlugin:
    id = "session"
    provides = (SessionEngine, SessionStorage)
    requires = ()
    configuration = (PluginConfig(
        "session", SessionSettings,
        lambda tree, root: parse_session_settings(tree, project_root=root),
        RuntimeSessionBridge().from_config_error,
    ),)

    async def build_generation(self, context: GenerationBuildContext) -> PluginGeneration:
        try:
            owner = SessionEngine(context.settings.get(SessionSettings))
        except SessionError as exc:
            raise RuntimeSessionBridge().startup_failure(
                message="Session could not be initialized.", payload={"error_type": type(exc).__name__}
            ) from exc

        def extend(kind: ProfileKind, profile: ProfileBuildContext) -> PluginProfileExtension:
            source = profile.bindings.get(SessionProfileSource) if kind is ProfileKind.MEMORY_REFLECTION else None
            return declare_session(
                owner, source=source.source if source else None,
                source_day=source.source_day if source else None,
                record_completed=kind is ProfileKind.USER,
                facts=profile.context.current_facts if kind is ProfileKind.USER else None,
            )

        return PluginGeneration(
            self.id, services=(Service(SessionEngine, owner), Service(SessionStorage, SessionStorage(owner.root))),
            profile_extension_factory=extend,
            sdk_exports=(PluginServiceExport(
                SessionService, lambda scope: SessionService(owner, scope), ServiceLifetime.DAY
            ),),
        )


def declare_session(
    session: SessionEngine,
    *,
    source: SessionViewSource | None = None,
    source_day: Callable[[], CalendarDay] | None = None,
    record_completed: bool = False,
    facts: Callable[[], ContextTurnFacts] | None = None,
) -> PluginProfileExtension:
    service = SessionService(source or session)
    writer = SessionOrganizeService(session) if facts is not None else None
    return PluginProfileExtension(
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
