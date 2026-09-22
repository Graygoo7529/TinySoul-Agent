"""Web capability contribution to the selected profiles."""

from dataclasses import dataclass
from functools import partial

from tinysoul.infra import StagingDirectoryManager
from tinysoul.kernel.action.runtime_bridge import RuntimeActionBridge
from tinysoul.kernel.registration import GenerationBuildContext, PluginConfig, PluginGeneration, PluginProfileExtension, ProfileBuildContext, ProfileKind
from tinysoul.plugins.workspace.services import WorkspaceService
from tinysoul.plugins.workspace.runtime_bridge import RuntimeWorkspaceBridge

from .config import WebSettings, parse_web_settings
from .actions import register_web_actions


@dataclass(frozen=True)
class WebPlugin:
    id = "web"
    provides = ()
    requires = (WorkspaceService, StagingDirectoryManager)
    configuration = (PluginConfig(
        "capabilities.web", WebSettings, lambda tree, root: parse_web_settings(tree),
        RuntimeActionBridge().from_config_error,
    ),)

    async def build_generation(self, context: GenerationBuildContext) -> PluginGeneration:
        workspace = context.services.get(WorkspaceService)
        staging = context.services.get(StagingDirectoryManager)
        settings = context.settings.get(WebSettings)

        def extend(kind: ProfileKind, profile: ProfileBuildContext) -> PluginProfileExtension:
            return PluginProfileExtension(
                self.id, requires=(WorkspaceService,),
                actions=partial(
                    register_web_actions, workspace=workspace, staging=staging,
                    settings=settings, runtime_bridge=RuntimeWorkspaceBridge(), runtime_env=dict(context.runtime_env),
                ),
            )
        return PluginGeneration(self.id, profile_extension_factory=extend)
