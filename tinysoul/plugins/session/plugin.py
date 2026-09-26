"""Session's public service and fixed source projection."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.infra.model_services import ModelServices
from tinysoul.infra.references import ReferenceResolver
from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.action.config import ActionSettings
from tinysoul.kernel.action.models import ModelUseRegistry
from tinysoul.kernel.context import ContextTurnFacts
from tinysoul.kernel.context.search import CONTEXT_SEARCH_FILTERS, disclosure_corpus
from tinysoul.kernel.registration import (
    GenerationBuildContext,
    PluginConfig,
    PluginGeneration,
    PluginProfileExtension,
    PluginServiceExport,
    ProfileBuildContext,
    ProfileKind,
    Service,
    ServiceLifetime,
)
from tinysoul.kernel.retrieval.contracts import (
    RefsSource,
    SearchFailure,
    SearchFailureKind,
)
from tinysoul.kernel.retrieval.operations import SearchSession
from tinysoul.kernel.retrieval.selection import CandidateSelector

from .actions import register_session_actions
from .config import SessionSettings, parse_session_settings
from .engine import SessionEngine
from .errors import SessionError
from .projection import SessionTurnCompletionHandler, session_segment_registration
from .runtime_bridge import RuntimeSessionBridge
from .services import SessionOrganizeService, SessionService, SessionViewSource


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
    model_uses = ()
    search_capabilities = ()
    provides = (SessionEngine, SessionStorage)
    requires = (ModelServices, ReferenceResolver)
    configuration = (
        PluginConfig(
            "session",
            SessionSettings,
            lambda tree, root: parse_session_settings(tree, project_root=root),
            RuntimeSessionBridge().from_config_error,
        ),
    )

    async def build_generation(
        self, context: GenerationBuildContext
    ) -> PluginGeneration:
        try:
            owner = SessionEngine(context.settings.get(SessionSettings))
        except SessionError as exc:
            raise RuntimeSessionBridge().startup_failure(
                message="Session could not be initialized.",
                payload={"error_type": type(exc).__name__},
            ) from exc

        def extend(
            kind: ProfileKind, profile: ProfileBuildContext
        ) -> PluginProfileExtension:
            source = (
                profile.bindings.get(SessionProfileSource)
                if kind is ProfileKind.MEMORY_REFLECTION
                else None
            )
            return declare_session(
                owner,
                source=source.source if source else None,
                source_day=source.source_day if source else None,
                record_completed=kind is ProfileKind.USER,
                facts=profile.context.current_facts
                if kind is ProfileKind.USER
                else None,
            )

        async def invoke(call):
            return await context.llm.invoke(call)

        selector = CandidateSelector(
            models=context.settings.get(ModelUseRegistry),
            invoke=invoke,
            services=context.services.get(ModelServices),
        )

        def sdk(scope):
            async def source(request):
                if request.options.scope not in {"all", "session"}:
                    raise SearchFailure(
                        SearchFailureKind.INVALID_REQUEST,
                        "SDK Session search only reads Session sources",
                    )

                def collect():
                    day = owner.active_day
                    if day is None:
                        raise SearchFailure(
                            SearchFailureKind.SOURCE_UNAVAILABLE,
                            "No active Session day",
                        )
                    view = owner.snapshot_view(day)
                    entries = view.search_entries(
                        request.source.refs
                        if isinstance(request.source, RefsSource)
                        else ()
                    )
                    return disclosure_corpus(
                        entries, request, context.services.get(ReferenceResolver)
                    )

                operations = JoinedOperations()
                result = await operations.run(collect)
                operations.check_cancelled()
                return result

            queries = SearchSession(
                observations=context.observations,
                action_id="core.context.search",
                retrieval_policies=context.settings.get(
                    ActionSettings
                ).retrieval_policies,
                source=source,
                selector=selector,
                filters=CONTEXT_SEARCH_FILTERS,
            )
            return SessionService(owner, scope, queries=queries)

        return PluginGeneration(
            self.id,
            services=(
                Service(SessionEngine, owner),
                Service(SessionStorage, SessionStorage(owner.root)),
            ),
            profile_extension_factory=extend,
            sdk_exports=(
                PluginServiceExport(SessionService, sdk, ServiceLifetime.DAY),
            ),
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
