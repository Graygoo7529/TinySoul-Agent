"""Memory services and one profile's protected background binding."""

from functools import partial
from tinysoul.kernel.registration import PluginTurnResource
from tinysoul.kernel.action.models import (
    ModelUseDescriptor,
    ModelOperation,
    ModelImplementation,
)
from dataclasses import dataclass, replace

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
)
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
from tinysoul.plugins.session.plugin import SessionStorage
from tinysoul.plugins.session.services import SessionService

from .actions import register_memory_actions
from .background import TargetMemoryBinding, memory_segment_registration
from .engine import MemoryEngine
from .services import MemoryReadService, MemoryService
from .runtime_bridge import RuntimeMemoryBridge
from .config import MemorySettings, parse_memory_settings
from .errors import MemoryError
from .actions import MemoryWriteSession, register_memory_write_actions
from .services import MemoryKnowledgeService


@dataclass(frozen=True)
class MemoryProfileSource:
    target: TargetMemoryBinding


@dataclass(frozen=True)
class MemoryPlugin:
    id = "memory"
    search_capabilities = (
        SearchCapability("memory.search", tuple(SourceKind), tuple(OperationKind), scopes=("all", "daily", "entity", "concept", "fact", "note"), filters=("kind", "status", "updated_on", "confidence"), ordered_filters=("updated_on",), document_query=True),
    )
    model_uses = (
        ModelUseDescriptor(
            "memory.search.select",
            "memory.search",
            ModelOperation.SELECT,
            (ModelImplementation.LLM_TASK, ModelImplementation.STRUCTURED_DECISION),
        ),
        ModelUseDescriptor(
            "memory.search.rerank",
            "memory.search",
            ModelOperation.RERANK,
            (
                *(
                    ModelImplementation.LLM_TASK,
                    ModelImplementation.STRUCTURED_DECISION,
                ),
                ModelImplementation.EMBEDDING_SIMILARITY,
            ),
            "memory",
        ),
    )
    provides = (MemoryEngine, MemoryWriteSession)
    requires = (SessionStorage, ModelServices, ReferenceResolver)
    configuration = (
        PluginConfig(
            "memory",
            MemorySettings,
            lambda tree, root: parse_memory_settings(tree, project_root=root),
            RuntimeMemoryBridge().from_config_error,
        ),
    )

    async def build_generation(
        self, context: GenerationBuildContext
    ) -> PluginGeneration:
        settings = context.settings.get(MemorySettings)
        models = context.services.get(ModelServices)
        references = context.services.get(ReferenceResolver)
        use = settings.search.embedding_use
        if use is not None:
            models.embedding_sessions(use)
        embedding = (
            EmbeddingIndex(
                path=settings.root / ".tinysoul" / "embeddings",
                services=models,
                use=use,
                max_chars=settings.search.embedding_cache_max_chars,
            )
            if use
            else None
        )
        try:
            owner = MemoryEngine(
                settings=settings,
                active_session_root=context.services.get(SessionStorage).root,
                embedding=embedding,
            )
        except MemoryError as exc:
            raise RuntimeMemoryBridge().startup_failure(
                message="Memory could not be initialized.",
                payload={"error_type": type(exc).__name__},
            ) from exc

        async def invoke(call):
            return await context.llm.invoke(call)

        selector = CandidateSelector(
            models=context.settings.get(ModelUseRegistry),
            invoke=invoke,
            services=models,
        )

        async def source(request):
            operations = JoinedOperations()
            result = await operations.run(
                lambda: owner.search_corpus(request, references=references)
            )
            operations.check_cancelled()
            return result

        def queries():
            return SearchSession(
                observations=context.observations,
                action_id="memory.search",

                retrieval_policies=context.settings.get(ActionSettings).retrieval_policies,
                source=source,
                selector=selector,
                embedding=embedding,
                supported_filters=frozenset({"kind", "status", "updated_on", "confidence"}),
            )

        knowledge = MemoryKnowledgeService(owner)
        writes = MemoryWriteSession(memory=knowledge)

        def extend(
            kind: ProfileKind, profile: ProfileBuildContext
        ) -> PluginProfileExtension:
            target = (
                profile.bindings.get(MemoryProfileSource).target
                if kind is ProfileKind.MEMORY_REFLECTION
                else None
            )
            extension = declare_memory(
                owner, target=target, queries=queries(), tasks=profile.tasks
            )
            if target is None:
                return extension
            actions = extension.actions

            def register(builder):
                assert actions is not None
                actions(builder)
                return register_memory_write_actions(builder, controller=writes)

            return replace(
                extension,
                actions=register,
                services=(
                    *extension.services,
                    Service(MemoryKnowledgeService, knowledge),
                ),
            )

        return PluginGeneration(
            self.id,
            services=(
                Service(MemoryEngine, owner),
                Service(MemoryWriteSession, writes),
            ),
            profile_extension_factory=extend,
            sdk_exports=(
                PluginServiceExport(
                    MemoryService,
                    lambda scope: MemoryService(owner, scope, queries=queries()),
                    ServiceLifetime.DAY,
                ),
            ),
        )


def declare_memory(
    memory: MemoryEngine,
    *,
    target: TargetMemoryBinding | None = None,
    queries: SearchSession | None = None,
    tasks: ActionTaskFactory | None = None,
) -> PluginProfileExtension:
    service = (
        MemoryService(memory, queries=queries)
        if target is None
        else MemoryReadService(memory, queries=queries)
    )
    return PluginProfileExtension(
        "memory",
        services=(Service(type(service), service),),
        requires=(SessionService,),
        segments=(memory_segment_registration(service, target=target),),
        actions=partial(
            register_memory_actions,
            memory=service,
            runtime_bridge=RuntimeMemoryBridge(),
            tasks=tasks,
        ),
        preparation=(queries,) if queries else (),
        turn_resources=(PluginTurnResource(queries),) if queries else (),
    )
