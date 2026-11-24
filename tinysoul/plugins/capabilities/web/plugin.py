"""Web capability contribution to the selected profiles."""

from dataclasses import dataclass
from functools import partial

from tinysoul.infra import StagingDirectoryManager
from tinysoul.infra.network import ResolvedNetwork
from tinysoul.kernel.registration import (
    GenerationBuildContext,
    PluginConfig,
    PluginGeneration,
    PluginProfileExtension,
    ProfileBuildContext,
    ProfileKind,
)
from tinysoul.plugins.workspace.services import WorkspaceService

from .actions import register_web_actions
from .config import WebSettings, parse_web_settings
from .dependencies import kimi_search_api_key, require_web_dependencies
from .runtime_bridge import RuntimeWebBridge
from .service import WebCapabilityService


@dataclass(frozen=True)
class WebPlugin:
    id = "web"
    model_uses = ()
    search_capabilities = ()
    provides = ()
    requires = (ResolvedNetwork, WorkspaceService, StagingDirectoryManager)
    configuration = (
        PluginConfig(
            "capabilities.web",
            WebSettings,
            lambda tree, root: parse_web_settings(tree),
            RuntimeWebBridge().from_config_error,
        ),
    )

    async def build_generation(
        self, context: GenerationBuildContext
    ) -> PluginGeneration:
        workspace = context.services.get(WorkspaceService)
        staging = context.services.get(StagingDirectoryManager)
        settings = context.settings.get(WebSettings)
        service: WebCapabilityService | None = None
        if any(
            action.enabled
            for action in (
                settings.search_by_kimi,
                settings.discover_pages,
                settings.fetch_with_defuddle,
                settings.fetch_with_trafilatura,
            )
        ):
            require_web_dependencies(settings)
            service = WebCapabilityService(
                workspace=workspace,
                staging=staging,
                settings=settings,
                runtime_env=context.runtime_env,
                network=context.services.get(ResolvedNetwork),
                kimi_api_key=kimi_search_api_key(settings, context.runtime_env),
            )

        def extend(
            kind: ProfileKind, profile: ProfileBuildContext
        ) -> PluginProfileExtension:
            return PluginProfileExtension(
                self.id,
                requires=(WorkspaceService,),
                actions=partial(
                    register_web_actions,
                    settings=settings,
                    service=service,
                ),
            )

        return PluginGeneration(self.id, profile_extension_factory=extend)
