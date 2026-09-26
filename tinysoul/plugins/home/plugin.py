"""Home's explicit service, Context and Action contributions."""

from functools import partial
from tinysoul.kernel.registration import PluginTurnResource
from tinysoul.kernel.action.models import (
    ModelUseDescriptor,
    ModelOperation,
    ModelImplementation,
)
from dataclasses import dataclass, replace

from tinysoul.kernel.loop.phases import LLMRunner
from tinysoul.kernel.registration import (
    PluginProfileExtension,
    Service,
    PluginGeneration,
    PluginConfig,
    PluginServiceExport,
    PluginTrapHandler,
    GenerationBuildContext,
    ProfileBuildContext,
    ProfileKind,
)

from .actions import register_home_actions
from .background import home_segment_registration
from .engine import AgentHomeEngine
from .services import HomeService
from tinysoul.infra.model_services import ModelServices
from tinysoul.infra.model_services.vectors import EmbeddingIndex
from tinysoul.infra.references import ReferenceResolver
from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.kernel.action.config import ActionSettings
from tinysoul.kernel.action.models import ModelUseRegistry
from tinysoul.kernel.action.tasks import ActionTaskFactory
from tinysoul.kernel.retrieval.policy import SearchCapability
from tinysoul.kernel.retrieval.contracts import (
    SourceKind,
    OperationKind,
)
from tinysoul.kernel.retrieval.operations import SearchSession
from tinysoul.kernel.retrieval.selection import CandidateSelector
from .runtime_bridge import RuntimeAgentHomeBridge
from .config import AgentHomeSettings, parse_agent_home_settings
from .engine import AgentHomeEngineBuilder
from .errors import AgentHomeError
from .failures import HOME_RUNTIME_COPY_REQUIRED
from . import AgentHomeRuntimeCopyTrapHandler
from .actions import HomeReviewExecutor, register_home_review_actions
from .services import HomeReviewService


@dataclass(frozen=True)
class HomePlugin:
    id = "home"
    search_capabilities = (
        SearchCapability("home.search", tuple(SourceKind), tuple(OperationKind), scopes=("all", "agent", "skills"), filters=("space", "file_type")),
    )
    model_uses = (
        ModelUseDescriptor(
            "home.search.select",
            "home.search",
            ModelOperation.SELECT,
            (ModelImplementation.LLM_TASK, ModelImplementation.STRUCTURED_DECISION),
        ),
        ModelUseDescriptor(
            "home.search.rerank",
            "home.search",
            ModelOperation.RERANK,
            (
                *(
                    ModelImplementation.LLM_TASK,
                    ModelImplementation.STRUCTURED_DECISION,
                ),
                ModelImplementation.EMBEDDING_SIMILARITY,
            ),
            "home",
        ),
    )
    provides = (AgentHomeEngine, HomeService)
    requires = (ModelServices, ReferenceResolver)
    configuration = (
        PluginConfig(
            "home",
            AgentHomeSettings,
            lambda tree, root: parse_agent_home_settings(tree, project_root=root),
            RuntimeAgentHomeBridge().from_config_error,
        ),
    )

    async def build_generation(
        self, context: GenerationBuildContext
    ) -> PluginGeneration:
        try:
            owner = AgentHomeEngineBuilder(
                context.settings.get(AgentHomeSettings)
            ).build()
        except AgentHomeError as exc:
            raise RuntimeAgentHomeBridge().startup_failure(
                message="Home could not be initialized.",
                payload={"error_type": type(exc).__name__},
            ) from exc
        settings = context.settings.get(AgentHomeSettings)
        models = context.services.get(ModelServices)
        references = context.services.get(ReferenceResolver)
        use = settings.search.embedding_use
        if use is not None:
            models.embedding_sessions(use)

        async def invoke(call):
            return await context.llm.invoke(call)

        selector = CandidateSelector(
            models=context.settings.get(ModelUseRegistry),
            invoke=invoke,
            services=models,
        )
        index = (
            EmbeddingIndex(
                path=settings.runtime_root.parent
                / ".tinysoul"
                / "home-search"
                / settings.runtime_root.name
                / "effective",
                services=models,
                use=use,
                max_chars=settings.search.embedding_cache_max_chars,
            )
            if use
            else None
        )

        def queries():
            async def source(request):
                operations = JoinedOperations()
                result = await operations.run(
                    lambda: owner.search_corpus(request, references=references)
                )
                operations.check_cancelled()
                return result

            return SearchSession(
                observations=context.observations,
                action_id="home.search",

                retrieval_policies=context.settings.get(ActionSettings).retrieval_policies,
                source=source,
                selector=selector,
                embedding=index,
                supported_filters=frozenset({"space", "file_type"}),
            )

        service = HomeService(owner, queries=queries())

        def extend(
            kind: ProfileKind, profile: ProfileBuildContext
        ) -> PluginProfileExtension:
            actual = kind is not ProfileKind.USER
            extension = declare_home(
                owner, actual=actual, queries=queries(), tasks=profile.tasks
            )
            actions = extension.actions
            review = (
                HomeReviewService(owner)
                if kind is ProfileKind.HOME_REFLECTION
                else None
            )

            def register(builder):
                assert actions is not None
                actions(builder)
                if review is not None:
                    register_home_review_actions(
                        builder, controller=HomeReviewExecutor(review)
                    )
                return builder

            return replace(
                extension,
                actions=register,
                services=(
                    *extension.services,
                    *((Service(HomeReviewService, review),) if review else ()),
                ),
                trap_handlers=(
                    PluginTrapHandler(
                        HOME_RUNTIME_COPY_REQUIRED,
                        AgentHomeRuntimeCopyTrapHandler(owner),
                    ),
                ),
            )

        return PluginGeneration(
            self.id,
            services=(Service(AgentHomeEngine, owner), Service(HomeService, service)),
            profile_extension_factory=extend,
            sdk_exports=(
                PluginServiceExport(
                    HomeService,
                    lambda scope: HomeService(owner, scope, queries=queries()),
                ),
            ),
        )


def declare_home(
    home: AgentHomeEngine,
    *,
    actual: bool = False,
    queries: SearchSession | None = None,
    tasks: ActionTaskFactory | None = None,
) -> PluginProfileExtension:
    service = HomeService(home, queries=queries)
    return PluginProfileExtension(
        "home",
        services=(Service(HomeService, service),),
        segments=(home_segment_registration(service, actual=actual),),
        actions=partial(
            register_home_actions,
            home=service,
            runtime_bridge=RuntimeAgentHomeBridge(),
            tasks=tasks,
        ),
        preparation=(queries,) if queries else (),
        turn_resources=(PluginTurnResource(queries),) if queries else (),
    )
