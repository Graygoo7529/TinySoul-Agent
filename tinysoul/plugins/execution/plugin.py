"""Generation and profile assembly of controlled execution."""

from dataclasses import dataclass
from functools import partial

from tinysoul.kernel.jobs import JobRegistry
from tinysoul.kernel.registration import (
    GenerationBuildContext,
    PluginConfig,
    PluginGeneration,
    PluginProfileExtension,
    ProfileBuildContext,
    ProfileKind,
)
from tinysoul.plugins.home.services import HomeService
from tinysoul.plugins.workspace.services import (
    WorkspaceExecutionService,
    WorkspaceService,
)

from .config import ExecutionSettings, parse_execution_settings
from .engine import ExecutionEngine
from .actions import register_execution_actions
from .runtime_bridge import RuntimeExecutionBridge


@dataclass(frozen=True)
class ExecutionPlugin:
    id = "execution"
    model_uses = ()
    search_capabilities = ()
    provides = ()
    requires = (JobRegistry, WorkspaceExecutionService, WorkspaceService, HomeService)
    configuration = (
        PluginConfig(
            "execution",
            ExecutionSettings,
            lambda tree, root: parse_execution_settings(tree),
            RuntimeExecutionBridge().from_config_error,
        ),
    )

    async def build_generation(
        self, context: GenerationBuildContext
    ) -> PluginGeneration:
        engine = ExecutionEngine(
            settings=context.settings.get(ExecutionSettings),
            jobs=context.services.get(JobRegistry),
            workspace=context.services.get(WorkspaceExecutionService),
        )
        home, workspace = (
            context.services.get(HomeService),
            context.services.get(WorkspaceService),
        )

        def extend(
            kind: ProfileKind, profile: ProfileBuildContext
        ) -> PluginProfileExtension:
            return PluginProfileExtension(
                self.id,
                requires=(HomeService, WorkspaceService),
                actions=partial(
                    register_execution_actions,
                    engine=engine,
                    home=home,
                    workspace=workspace,
                ),
            )

        return PluginGeneration(self.id, profile_extension_factory=extend)
