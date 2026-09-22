"""Compose profile extensions from the generation's selected plugins."""

from dataclasses import dataclass

from tinysoul.infra import StagingDirectoryManager, StagingError
from tinysoul.infra.config import ConfigError
from tinysoul.kernel.action import ActionEngineBuilder, ActionError, LoadedActionCatalog
from tinysoul.kernel.action.backends.llm_action import LLMActionTaskRunner
from tinysoul.kernel.action.builtins.core import register_core_actions
from tinysoul.kernel.action.config import ActionSettings, LLMActionProfileResolver
from tinysoul.kernel.action.runtime_bridge import RuntimeActionBridge
from tinysoul.kernel.context import ContextEngine
from tinysoul.kernel.context.actions import register_context_actions
from tinysoul.kernel.context.errors import ContextError
from tinysoul.kernel.context.runtime_bridge import RuntimeContextBridge
from tinysoul.kernel.jobs import JobRegistry, jobs_segment_registration
from tinysoul.kernel.jobs.actions import register_job_actions
from tinysoul.kernel.jobs.config import JobSettings, parse_job_settings
from tinysoul.kernel.jobs.runtime_bridge import RuntimeJobsBridge
from tinysoul.kernel.loop.failures import LoopFailureKind
from tinysoul.kernel.loop.phases import LLMRunner
from tinysoul.kernel.loop.runtime_bridge import RuntimeLoopBridge
from tinysoul.kernel.registration import (
    GenerationBuildContext, PluginConfig, PluginGeneration, PluginProfileExtension,
    PluginRegistry, ProfileBuildContext, ProfileKind, RegistrationError,
    ResolvedProfileExtensions, Service, ServiceRegistry,
)
from tinysoul.plugins.home import HomeActionSkillProvider
from tinysoul.plugins.home.runtime_bridge import RuntimeAgentHomeBridge
from tinysoul.plugins.home.services import HomeService
from tinysoul.plugins.workspace import WorkspacePromptReferenceResolver
from tinysoul.plugins.workspace.runtime_bridge import RuntimeWorkspaceBridge
from tinysoul.plugins.workspace.services import WorkspaceService
from tinysoul.runtime import ObservationEmitter

from .activity import AgentTurnActivity


@dataclass(frozen=True)
class CorePlugin:
    """Kernel capabilities and the shared staging service in the standard recipe."""

    id = "core"
    provides = (JobRegistry, StagingDirectoryManager)
    requires = (WorkspaceService,)
    configuration = (PluginConfig(
        "jobs", JobSettings, lambda tree, root: parse_job_settings(tree),
        RuntimeJobsBridge().from_config_error,
    ),)

    async def build_generation(self, context: GenerationBuildContext) -> PluginGeneration:
        settings = context.settings.get(JobSettings)
        jobs = JobRegistry(capacity=settings.retained_capacity, per_turn_capacity=settings.per_turn_live_capacity)
        staging = StagingDirectoryManager(context.root)
        try:
            staging.prepare()
        except StagingError as exc:
            raise RuntimeLoopBridge().from_exception(LoopFailureKind.RESOURCE_PREPARATION_FAILED, exc) from exc
        workspace = context.services.get(WorkspaceService)

        def extend(kind: ProfileKind, profile: ProfileBuildContext) -> PluginProfileExtension:
            def register(builder: ActionEngineBuilder) -> ActionEngineBuilder:
                register_context_actions(builder, context=profile.context, runtime_bridge=RuntimeContextBridge())
                register_job_actions(builder, jobs)
                return register_core_actions(
                    builder, llm_action=profile.llm_action,
                    reference_resolvers=(WorkspacePromptReferenceResolver(workspace, runtime_bridge=RuntimeWorkspaceBridge()),),
                )
            return PluginProfileExtension(
                self.id, requires=(WorkspaceService,), actions=register,
                segments=(jobs_segment_registration(),),
            )

        return PluginGeneration(
            self.id, services=(Service(JobRegistry, jobs), Service(StagingDirectoryManager, staging)),
            profile_extension_factory=extend,
        )


class ProfileAssembly:
    """Apply the same contribution path to every execution scenario."""

    def __init__(
        self, *, plugins: tuple[PluginGeneration, ...], llm: LLMRunner,
        home: HomeService, jobs: JobRegistry, observations: ObservationEmitter,
        action_settings: ActionSettings,
    ) -> None:
        self._plugins, self._llm, self._home = plugins, llm, home
        self._jobs, self._observations, self._settings = jobs, observations, action_settings

    def prepare(
        self, context: ContextEngine, catalog: LoadedActionCatalog, *,
        kind: ProfileKind, bindings: ServiceRegistry | None = None,
    ) -> tuple[ActionEngineBuilder, AgentTurnActivity, ResolvedProfileExtensions]:
        llm_action = LLMActionTaskRunner(
            llm_runner=self._llm, context=context,
            action_skills=HomeActionSkillProvider(self._home, runtime_bridge=RuntimeAgentHomeBridge()),
            profile_resolver=LLMActionProfileResolver(self._settings.llm_action),
        )
        profile = ProfileBuildContext(context, llm_action, bindings or ServiceRegistry(()))
        try:
            declarations = tuple(
                extension for plugin in self._plugins
                if (extension := plugin.extend_profile(kind, profile)) is not None
            )
            resolved = PluginRegistry(declarations).resolve(context)
            builder = ActionEngineBuilder(
                catalog, scenarios=frozenset(kind.value for kind in ProfileKind)
            ).with_observations(self._observations)
            resolved.activate(builder)
        except (RegistrationError, ContextError) as exc:
            raise RuntimeLoopBridge().startup_failure(
                message="Profile contributions could not be resolved.", payload={"error_type": type(exc).__name__}
            ) from exc
        except ConfigError as exc:
            raise RuntimeActionBridge().from_config_error(exc) from exc
        except ActionError as exc:
            raise RuntimeActionBridge().startup_failure(
                message="Profile actions could not be initialized.", payload={"error_type": type(exc).__name__}
            ) from exc
        return builder, AgentTurnActivity(self._jobs, resolved.turn_resources), resolved
