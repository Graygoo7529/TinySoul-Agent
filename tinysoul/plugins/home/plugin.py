"""Home's explicit service, Context and Action contributions."""

from functools import partial
from dataclasses import dataclass, replace

from tinysoul.kernel.loop.phases import LLMRunner
from tinysoul.kernel.registration import (
    PluginProfileExtension, Service, PluginGeneration, PluginConfig,
    PluginServiceExport, PluginTrapHandler, GenerationBuildContext,
    ProfileBuildContext, ProfileKind,
)

from .actions import register_home_actions
from .background import home_segment_registration
from .engine import AgentHomeEngine
from .services import HomeService
from .content.search import LLMHomeSearchReranker
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
    provides = (AgentHomeEngine, HomeService)
    requires = ()
    configuration = (PluginConfig(
        "home", AgentHomeSettings,
        lambda tree, root: parse_agent_home_settings(tree, project_root=root),
        RuntimeAgentHomeBridge().from_config_error,
    ),)

    async def build_generation(self, context: GenerationBuildContext) -> PluginGeneration:
        try:
            owner = AgentHomeEngineBuilder(context.settings.get(AgentHomeSettings)).build()
        except AgentHomeError as exc:
            raise RuntimeAgentHomeBridge().startup_failure(
                message="Home could not be initialized.",
                payload={"error_type": type(exc).__name__},
            ) from exc
        service = HomeService(owner)

        def extend(kind: ProfileKind, profile: ProfileBuildContext) -> PluginProfileExtension:
            extension = declare_home(owner, context.llm, actual=kind is not ProfileKind.USER)
            actions = extension.actions
            review = HomeReviewService(owner) if kind is ProfileKind.HOME_REFLECTION else None

            def register(builder):
                assert actions is not None
                actions(builder)
                if review is not None:
                    register_home_review_actions(builder, controller=HomeReviewExecutor(review))
                return builder

            return replace(
                extension, actions=register,
                services=(*extension.services, *((Service(HomeReviewService, review),) if review else ())),
                trap_handlers=(PluginTrapHandler(
                    HOME_RUNTIME_COPY_REQUIRED, AgentHomeRuntimeCopyTrapHandler(owner)
                ),),
            )

        return PluginGeneration(
            self.id, services=(Service(AgentHomeEngine, owner), Service(HomeService, service)),
            profile_extension_factory=extend,
            sdk_exports=(PluginServiceExport(HomeService, lambda scope: HomeService(owner, scope)),),
        )


def declare_home(
    home: AgentHomeEngine, llm: LLMRunner, *, actual: bool = False
) -> PluginProfileExtension:
    service = HomeService(home)
    return PluginProfileExtension(
        "home",
        services=(Service(HomeService, service),),
        segments=(home_segment_registration(service, actual=actual),),
        actions=partial(
            register_home_actions,
            home=service,
            runtime_bridge=RuntimeAgentHomeBridge(),
            search_reranker=LLMHomeSearchReranker(llm),
        ),
    )
