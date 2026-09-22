"""Resource capability contribution to the selected profiles."""

from dataclasses import dataclass
from functools import partial

from tinysoul.infra import StagingDirectoryManager
from tinysoul.kernel.action.runtime_bridge import RuntimeActionBridge
from tinysoul.kernel.registration import GenerationBuildContext, PluginConfig, PluginGeneration, PluginProfileExtension, ProfileBuildContext, ProfileKind
from tinysoul.plugins.workspace.services import WorkspaceService
from tinysoul.plugins.workspace.runtime_bridge import RuntimeWorkspaceBridge

from .config import ResourceSettings, parse_resource_settings
from .actions import register_resource_actions


@dataclass(frozen=True)
class ResourcePlugin:
    id = "resource"
    provides = ()
    requires = (WorkspaceService, StagingDirectoryManager)
    configuration = (PluginConfig(
        "capabilities.resource", ResourceSettings, lambda tree, root: parse_resource_settings(tree),
        RuntimeActionBridge().from_config_error,
    ),)

    async def build_generation(self, context: GenerationBuildContext) -> PluginGeneration:
        workspace = context.services.get(WorkspaceService)
        staging = context.services.get(StagingDirectoryManager)
        settings = context.settings.get(ResourceSettings)

        def extend(kind: ProfileKind, profile: ProfileBuildContext) -> PluginProfileExtension:
            return PluginProfileExtension(
                self.id, requires=(WorkspaceService,),
                actions=partial(
                    register_resource_actions, workspace=workspace, staging=staging,
                    settings=settings, runtime_bridge=RuntimeWorkspaceBridge(),
                ),
            )
        return PluginGeneration(self.id, profile_extension_factory=extend)
