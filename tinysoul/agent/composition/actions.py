"""Agent composition of owner contributions for each Turn profile."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from pathlib import Path

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
from tinysoul.kernel.jobs.config import JobSettings
from tinysoul.kernel.loop.failures import LoopFailureKind
from tinysoul.kernel.loop.phases import LLMRunner
from tinysoul.kernel.loop.runtime_bridge import RuntimeLoopBridge
from tinysoul.kernel.registration import (
    PluginDeclaration,
    PluginRegistry,
    RegistrationError,
    ServiceRegistry,
    ResolvedPlugins,
)
from tinysoul.plugins.capabilities import CapabilitiesSettings
from tinysoul.plugins.capabilities.resource import register_resource_actions
from tinysoul.plugins.capabilities.web import register_web_actions
from tinysoul.plugins.execution import ExecutionSettings, ProcessJobBackend
from tinysoul.plugins.execution.engine import ExecutionEngine
from tinysoul.plugins.execution.actions import register_execution_actions
from tinysoul.plugins.execution.runtime_bridge import RuntimeExecutionBridge
from tinysoul.plugins.home import HomeActionSkillProvider
from tinysoul.plugins.home.runtime_bridge import RuntimeAgentHomeBridge
from tinysoul.plugins.home.services import HomeService
from tinysoul.plugins.workspace import WorkspaceEngine, WorkspacePromptReferenceResolver
from tinysoul.plugins.workspace.engine import WorkspaceArchiveView
from tinysoul.plugins.workspace.plugin import declare_workspace
from tinysoul.plugins.workspace.runtime_bridge import RuntimeWorkspaceBridge
from tinysoul.plugins.workspace.services import WorkspaceService
from tinysoul.runtime import ObservationEmitter
from tinysoul.runtime.sources import RuntimeSource

from .activity import AgentTurnActivity
from tinysoul.kernel.jobs.models import JobControl

AGENT_SCENARIOS = frozenset({"user", "home_reflection", "memory_reflection"})


def prepare_common_actions(
    builder: ActionEngineBuilder,
    *,
    workspace: WorkspaceService,
    context: ContextEngine,
    llm_action: LLMActionTaskRunner,
    capabilities_settings: CapabilitiesSettings,
    runtime_env: dict[str, str],
    staging: StagingDirectoryManager,
) -> ActionEngineBuilder:
    workspace_bridge = RuntimeWorkspaceBridge()
    try:
        register_context_actions(
            builder, context=context, runtime_bridge=RuntimeContextBridge()
        )
        register_resource_actions(
            builder,
            settings=capabilities_settings.resource,
            workspace=workspace,
            runtime_bridge=workspace_bridge,
            staging=staging,
        )
        register_web_actions(
            builder,
            settings=capabilities_settings.web,
            runtime_env=runtime_env,
            workspace=workspace,
            runtime_bridge=workspace_bridge,
            staging=staging,
        )
        register_core_actions(
            builder,
            reference_resolvers=(
                WorkspacePromptReferenceResolver(
                    workspace, runtime_bridge=workspace_bridge
                ),
            ),
            llm_action=llm_action,
        )
        return builder
    except ConfigError as exc:
        raise RuntimeActionBridge().from_config_error(exc) from exc
    except ActionError as exc:
        raise RuntimeActionBridge().startup_failure(
            message="Common actions could not be initialized.",
            payload={"error_type": type(exc).__name__},
        ) from exc


class CommonActionAssembly:
    """One generation's shared services, with separately granted profile surfaces."""

    @property
    def jobs(self) -> JobControl:
        return self._jobs

    def __init__(
        self,
        *,
        root: Path,
        workspace: WorkspaceEngine,
        llm: LLMRunner,
        observations: ObservationEmitter,
        action_settings: ActionSettings,
        capabilities_settings: CapabilitiesSettings,
        runtime_env: dict[str, str],
        execution_settings: ExecutionSettings | None = None,
        job_settings: JobSettings | None = None,
        workspace_source: RuntimeSource | None = None,
        runtime_plugins: tuple[PluginDeclaration, ...] = (),
    ) -> None:
        self._root, self._workspace = root, workspace
        self._workspace_source = workspace_source
        self._runtime_plugins = runtime_plugins
        self._llm, self._observations = llm, observations
        self._action_settings, self._capabilities_settings = (
            action_settings,
            capabilities_settings,
        )
        self._runtime_env = dict(runtime_env)
        settings = job_settings or JobSettings()
        self._jobs = JobRegistry[ProcessJobBackend](
            capacity=settings.retained_capacity,
            per_turn_capacity=settings.per_turn_live_capacity,
        )
        self._activity = AgentTurnActivity(self._jobs, workspace)
        try:
            self._execution = ExecutionEngine(
                settings=execution_settings or ExecutionSettings(),
                jobs=self._jobs,
                workspace=workspace,
            )
        except ConfigError as exc:
            raise RuntimeExecutionBridge().from_config_error(exc) from exc

    def prepare(
        self,
        context: ContextEngine,
        catalog: LoadedActionCatalog,
        *,
        plugins: tuple[PluginDeclaration, ...],
        archive_source: Callable[[], WorkspaceArchiveView | None] | None = None,
    ) -> tuple[
        ActionEngineBuilder, AgentTurnActivity[ProcessJobBackend], ResolvedPlugins
    ]:
        staging = StagingDirectoryManager(self._root)
        try:
            staging.prepare()
        except StagingError as exc:
            raise RuntimeLoopBridge().from_exception(
                LoopFailureKind.RESOURCE_PREPARATION_FAILED, exc
            ) from exc
        workspace = WorkspaceService(self._workspace)
        home = ServiceRegistry(
            tuple(service for plugin in plugins for service in plugin.services)
        ).get(HomeService)
        llm_action = LLMActionTaskRunner(
            llm_runner=self._llm,
            context=context,
            action_skills=HomeActionSkillProvider(
                home, runtime_bridge=RuntimeAgentHomeBridge()
            ),
            profile_resolver=LLMActionProfileResolver(self._action_settings.llm_action),
        )
        declarations = (
            *plugins,
            *self._runtime_plugins,
            declare_workspace(
                workspace,
                owner=self._workspace,
                source=self._workspace_source,
                llm_action=llm_action,
                archive_source=archive_source,
            ),
            PluginDeclaration(
                "common_actions",
                requires=(WorkspaceService,),
                actions=partial(
                    prepare_common_actions,
                    workspace=workspace,
                    context=context,
                    llm_action=llm_action,
                    capabilities_settings=self._capabilities_settings,
                    runtime_env=self._runtime_env,
                    staging=staging,
                ),
            ),
            PluginDeclaration(
                "jobs",
                segments=(jobs_segment_registration(),),
                actions=lambda builder: register_job_actions(builder, self._jobs),
            ),
            PluginDeclaration(
                "execution",
                requires=(HomeService, WorkspaceService),
                actions=partial(
                    register_execution_actions,
                    engine=self._execution,
                    home=home,
                    workspace=workspace,
                ),
            ),
        )
        try:
            resolved = PluginRegistry(declarations).resolve(context)
            builder = ActionEngineBuilder(
                catalog, scenarios=AGENT_SCENARIOS
            ).with_observations(self._observations)
            resolved.activate(builder)
        except (RegistrationError, ContextError) as exc:
            raise RuntimeLoopBridge().startup_failure(
                message="Profile contributions could not be resolved.",
                payload={"error_type": type(exc).__name__},
            ) from exc
        except ConfigError as exc:
            raise RuntimeActionBridge().from_config_error(exc) from exc
        except ActionError as exc:
            raise RuntimeActionBridge().startup_failure(
                message="Profile actions could not be initialized.",
                payload={"error_type": type(exc).__name__},
            ) from exc
        return builder, self._activity, resolved
