"""Memory services and one profile's protected background binding."""

from functools import partial
from dataclasses import dataclass, replace

from tinysoul.kernel.registration import (
    PluginProfileExtension, Service, PluginGeneration, PluginConfig, PluginServiceExport,
    ServiceLifetime, GenerationBuildContext, ProfileBuildContext, ProfileKind,
)
from tinysoul.infra import InfraSettings, build_embedding_client
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
    provides = (MemoryEngine, MemoryWriteSession)
    requires = (SessionStorage,)
    configuration = (PluginConfig(
        "memory", MemorySettings,
        lambda tree, root: parse_memory_settings(tree, project_root=root),
        RuntimeMemoryBridge().from_config_error,
    ),)

    async def build_generation(self, context: GenerationBuildContext) -> PluginGeneration:
        embedding = build_embedding_client(
            context.settings.get(InfraSettings).embedding, env=context.runtime_env
        )
        try:
            owner = MemoryEngine(
                settings=context.settings.get(MemorySettings),
                active_session_root=context.services.get(SessionStorage).root,
                embedding_client=embedding,
            )
        except BaseException as exc:
            if embedding is not None:
                await embedding.close()
            if isinstance(exc, MemoryError):
                raise RuntimeMemoryBridge().startup_failure(
                    message="Memory could not be initialized.", payload={"error_type": type(exc).__name__}
                ) from exc
            raise
        knowledge = MemoryKnowledgeService(owner)
        writes = MemoryWriteSession(memory=knowledge)

        def extend(kind: ProfileKind, profile: ProfileBuildContext) -> PluginProfileExtension:
            target = profile.bindings.get(MemoryProfileSource).target if kind is ProfileKind.MEMORY_REFLECTION else None
            extension = declare_memory(owner, target=target)
            if target is None:
                return extension
            actions = extension.actions

            def register(builder):
                assert actions is not None
                actions(builder)
                return register_memory_write_actions(builder, controller=writes)

            return replace(extension, actions=register, services=(
                *extension.services, Service(MemoryKnowledgeService, knowledge)
            ))

        return PluginGeneration(
            self.id, services=(Service(MemoryEngine, owner), Service(MemoryWriteSession, writes)),
            profile_extension_factory=extend,
            sdk_exports=(PluginServiceExport(
                MemoryService, lambda scope: MemoryService(owner, scope), ServiceLifetime.DAY
            ),),
            close=embedding.close if embedding else None,
        )


def declare_memory(memory: MemoryEngine, *, target: TargetMemoryBinding | None = None) -> PluginProfileExtension:
    service = MemoryService(memory) if target is None else MemoryReadService(memory)
    return PluginProfileExtension(
        "memory", services=(Service(type(service), service),), requires=(SessionService,),
        segments=(memory_segment_registration(service, target=target),),
        actions=partial(register_memory_actions, memory=service, runtime_bridge=RuntimeMemoryBridge()),
    )
