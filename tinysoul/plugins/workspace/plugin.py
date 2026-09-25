"""Current Workspace service and explicit read-only archive contributions."""

from collections.abc import Callable
from functools import partial
from tinysoul.kernel.action.models import (
    ModelUseDescriptor,
    ModelOperation,
    ModelImplementation,
)
from dataclasses import dataclass, replace
from tinysoul.kernel.registration import PluginTurnResource

from tinysoul.kernel.action.tasks import ActionTaskFactory, ActionTaskOutput
from tinysoul.kernel.loop.phases import LLMRunner
from tinysoul.llm.protocol.responses import AnswerFormat
from tinysoul.kernel.loop.interaction.events import TurnEventSubscription
from tinysoul.kernel.registration import (
    PluginProfileExtension,
    Service,
    PluginGeneration,
    PluginConfig,
    PluginServiceExport,
    ServiceLifetime,
    GenerationBuildContext,
    ProfileBuildContext,
    ProfileKind,
    PluginTurnResource,
    TurnResourceStage,
)
from tinysoul.runtime import RunScope, Signal
from tinysoul.runtime.events import EnvironmentEvent, EventFilter

from .actions import register_workspace_actions
from .engine import WorkspaceArchiveView, WorkspaceEngine
from .events import WORKSPACE_CHANGED, WORKSPACE_OWNER, WORKSPACE_WATCH
from .failures import WorkspaceFailureKind
from .projection import (
    WorkspaceTurnPreparationHandler,
    archived_workspace_segment_registration,
    workspace_refresh_signal,
    workspace_segment_registration,
)
from .runtime_bridge import RuntimeWorkspaceBridge
from .services import WorkspaceService, WorkspaceExecutionService
from .config import WorkspaceSettings, parse_workspace_settings
from .engine import WorkspaceEngineBuilder
from .errors import WorkspaceError, WorkspaceReconciliationError
from .events import WorkspaceRuntime
from tinysoul.runtime.sources import RuntimeWatcher
from tinysoul.infra.concurrency import CleanupDiagnostic, JoinedOperations
from tinysoul.infra.references import ReferenceResolver
from tinysoul.kernel.action.config import ActionSettings
from tinysoul.kernel.retrieval.policy import SearchCapability
from tinysoul.kernel.retrieval.contracts import (
    SearchMode,
    CandidateSource,
    SearchSemantic,
)
from tinysoul.kernel.retrieval.operations import SearchSession


@dataclass(frozen=True)
class WorkspaceProfileSource:
    archive: Callable[[], WorkspaceArchiveView | None]


class WorkspaceTurnResources:
    def __init__(self, owner: WorkspaceEngine) -> None:
        self._owner = owner

    async def close_turn(self, turn_id: str) -> tuple[CleanupDiagnostic, ...]:
        joined = JoinedOperations()
        try:
            result = await joined.run(self._owner.reconcile)
            if not result.complete:
                raise WorkspaceReconciliationError(
                    "Final Workspace reconciliation is incomplete"
                )
        except WorkspaceError as exc:
            raise RuntimeWorkspaceBridge().from_workspace_error(exc) from exc
        await joined.finish(self._owner.events.flush)
        joined.check_cancelled()
        return ()


@dataclass(frozen=True)
class WorkspacePlugin:
    id = "workspace"
    search_capabilities = (
        SearchCapability(
            "workspace.search",
            (SearchMode.BACKLINK_SEARCH,),
            (),
            (SearchSemantic.NONE,),
        ),
    )
    model_uses = (
        ModelUseDescriptor(
            "workspace.compose.generate", "workspace.compose", ModelOperation.GENERATE
        ),
        ModelUseDescriptor(
            "workspace.describe.generate", "workspace.describe", ModelOperation.GENERATE
        ),
        ModelUseDescriptor(
            "workspace.analyze.generate", "workspace.analyze", ModelOperation.GENERATE
        ),
    )
    provides = (WorkspaceEngine, WorkspaceService, WorkspaceExecutionService)
    requires = (RuntimeWatcher, ReferenceResolver)
    configuration = (
        PluginConfig(
            "workspace",
            WorkspaceSettings,
            lambda tree, root: parse_workspace_settings(tree, project_root=root),
            RuntimeWorkspaceBridge().from_config_error,
        ),
    )

    async def build_generation(
        self, context: GenerationBuildContext
    ) -> PluginGeneration:
        try:
            owner = WorkspaceEngineBuilder(
                context.settings.get(WorkspaceSettings),
                observations=context.observations,
            ).build()
        except WorkspaceError as exc:
            raise RuntimeWorkspaceBridge().startup_failure(
                message="Workspace could not be initialized.",
                payload={"error_type": type(exc).__name__},
            ) from exc
        references = context.services.get(ReferenceResolver)

        async def source(request):
            operations = JoinedOperations()
            result = await operations.run(
                lambda: owner.backlink_corpus(request, references=references)
            )
            await operations.finish(owner.events.flush)
            operations.check_cancelled()
            return result

        def queries():
            return SearchSession(
                observations=context.observations,
                action_id="workspace.search",
                policies=context.settings.get(ActionSettings).search_policies,
                source=source,
            )

        service = WorkspaceService(owner, queries=queries())
        runtime = WorkspaceRuntime(
            owner,
            context.services.get(RuntimeWatcher),
            observations=context.observations,
        )

        def extend(
            kind: ProfileKind, profile: ProfileBuildContext
        ) -> PluginProfileExtension:
            archive = (
                profile.bindings.get(WorkspaceProfileSource).archive
                if kind is ProfileKind.MEMORY_REFLECTION
                else None
            )
            search = queries()
            extension = declare_workspace(
                WorkspaceService(owner, queries=search),
                owner=owner,
                tasks=profile.tasks,
                llm=profile.llm,
                archive_source=archive,
            )
            return replace(
                extension,
                preparation=(*extension.preparation, search),
                turn_resources=(*extension.turn_resources, PluginTurnResource(search)),
            )

        return PluginGeneration(
            self.id,
            services=(
                Service(WorkspaceEngine, owner),
                Service(WorkspaceService, service),
                Service(WorkspaceExecutionService, WorkspaceExecutionService(owner)),
            ),
            profile_extension_factory=extend,
            sources=(runtime,),
            close=lambda: _unbind_runtime(runtime),
            sdk_exports=(
                PluginServiceExport(
                    WorkspaceService,
                    lambda scope: WorkspaceService(owner, scope, queries=queries()),
                    ServiceLifetime.DAY,
                ),
            ),
        )


async def _unbind_runtime(runtime: WorkspaceRuntime) -> None:
    runtime.unbind()


def _refresh(event: EnvironmentEvent, scope: RunScope) -> tuple[Signal, ...]:
    return (
        workspace_refresh_signal(
            call_id=event.event_id, scope=scope, source=event.source
        ),
    )


def _unavailable(event: EnvironmentEvent, scope: RunScope) -> tuple[Signal, ...]:
    raise RuntimeWorkspaceBridge().from_failure(
        WorkspaceFailureKind.IO_FAILED,
        message="Workspace discovery could not complete.",
        payload=event.payload,
    )


def declare_workspace(
    workspace: WorkspaceService,
    *,
    tasks: ActionTaskFactory,
    llm: LLMRunner,
    owner: WorkspaceEngine,
    archive_source: Callable[[], WorkspaceArchiveView | None] | None = None,
) -> PluginProfileExtension:
    return PluginProfileExtension(
        "workspace",
        services=(Service(WorkspaceService, workspace),),
        segments=(
            workspace_segment_registration(owner),
            *(
                (archived_workspace_segment_registration(archive_source),)
                if archive_source is not None
                else ()
            ),
        ),
        actions=partial(
            register_workspace_actions,
            workspace=workspace,
            tasks=tasks,
            llm=llm,
            runtime_bridge=RuntimeWorkspaceBridge(),
        ),
        preparation=(WorkspaceTurnPreparationHandler(owner, RuntimeWorkspaceBridge()),),
        turn_resources=(
            PluginTurnResource(
                WorkspaceTurnResources(owner), TurnResourceStage.SYNCHRONIZE
            ),
        ),
        events=tuple(
            TurnEventSubscription(
                EventFilter(topic=WORKSPACE_CHANGED, source=name),
                _refresh,
                coalesce=True,
                requires_decision=False,
            )
            for name in (WORKSPACE_OWNER, WORKSPACE_WATCH)
        )
        + (
            TurnEventSubscription(
                EventFilter(topic="workspace.unavailable", source=WORKSPACE_WATCH),
                _unavailable,
            ),
        ),
    )
