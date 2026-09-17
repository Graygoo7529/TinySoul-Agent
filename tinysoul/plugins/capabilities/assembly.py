"""Shared action assembly for User and Reflection profiles."""

from __future__ import annotations

from pathlib import Path
from collections.abc import Callable
from functools import partial
from tinysoul.kernel.registration import PluginDeclaration, PluginRegistry, RegistrationError, Service, ServiceRegistry
from tinysoul.plugins.workspace.plugin import declare_workspace
from tinysoul.plugins.workspace.services import WorkspaceService
from tinysoul.plugins.home.services import HomeService
from tinysoul.plugins.workspace.engine import WorkspaceArchiveView
from tinysoul.kernel.context.errors import ContextError
from tinysoul.kernel.action.config import ActionSettings, LLMActionProfileResolver
from tinysoul.plugins.home import HomeActionSkillProvider
from tinysoul.infra import StagingError
from tinysoul.plugins.workspace import WorkspaceMirrorService
from tinysoul.kernel.loop.failures import LoopFailureKind
from tinysoul.kernel.loop.runtime_bridge import RuntimeLoopBridge

from tinysoul.kernel.action import (
    ActionEngineBuilder,
    ActionError,
    LoadedActionCatalog,
)
from tinysoul.kernel.action.backends.llm_action import LLMActionTaskRunner
from tinysoul.kernel.action.builtins.core import register_core_actions
from tinysoul.plugins.capabilities import CapabilitiesSettings
from tinysoul.plugins.capabilities.resource import register_resource_actions
from tinysoul.plugins.capabilities.shell import register_shell_actions
from tinysoul.plugins.capabilities.script import ScriptSourceResolver, register_script_actions
from tinysoul.plugins.capabilities.supervised_process import (
    SupervisedProcessAnswerGuard,
    SupervisedProcessManager,
    register_supervised_process_actions,
)
from tinysoul.plugins.capabilities.web import register_web_actions
from tinysoul.kernel.context import ContextEngine
from tinysoul.kernel.jobs import jobs_segment_registration
from tinysoul.kernel.jobs.actions import register_job_actions
from tinysoul.kernel.context.actions import register_context_actions
from tinysoul.plugins.home import AgentHomeEngine
from tinysoul.infra import StagingDirectoryManager
from tinysoul.infra.config import ConfigError
from tinysoul.runtime import ObservationEmitter, SignalBus
from tinysoul.kernel.action.runtime_bridge import RuntimeActionBridge
from tinysoul.plugins.home.runtime_bridge import RuntimeAgentHomeBridge
from tinysoul.kernel.context.runtime_bridge import RuntimeContextBridge
from tinysoul.plugins.capabilities.script.runtime_bridge import RuntimeScriptBridge
from tinysoul.plugins.capabilities.shell.runtime_bridge import RuntimeShellBridge
from tinysoul.plugins.workspace.runtime_bridge import RuntimeWorkspaceBridge
from tinysoul.plugins.workspace import (
    WorkspaceEngine,
    WorkspacePromptReferenceResolver,
)

from tinysoul.kernel.loop.phases import LLMRunner


def prepare_common_actions(
    builder: ActionEngineBuilder,
    *,
    bus: SignalBus,
    workspace: WorkspaceService,
    context: ContextEngine,
    llm_action: LLMActionTaskRunner,
    capabilities_settings: CapabilitiesSettings,
    runtime_env: dict[str, str],
    staging: StagingDirectoryManager,
    process_jobs: SupervisedProcessManager,
    script_resolver: ScriptSourceResolver,
) -> ActionEngineBuilder:
    """Register common domains; the profile may add its own contributions."""

    home_bridge = RuntimeAgentHomeBridge()
    context_bridge = RuntimeContextBridge()
    workspace_bridge = RuntimeWorkspaceBridge()
    action_bridge = RuntimeActionBridge()
    script_bridge = RuntimeScriptBridge()
    shell_bridge = RuntimeShellBridge()
    try:
        register_context_actions(
            builder,
            context=context,
            runtime_bridge=context_bridge,
        )
        register_resource_actions(
            builder,
            settings=capabilities_settings.resource,
            workspace=workspace,
            bus=bus,
            runtime_bridge=workspace_bridge,
            staging=staging,
        )
        register_web_actions(
            builder,
            settings=capabilities_settings.web,
            runtime_env=runtime_env,
            workspace=workspace,
            bus=bus,
            runtime_bridge=workspace_bridge,
            staging=staging,
        )
        try:
            register_script_actions(
                builder,
                settings=capabilities_settings.script,
                resolver=script_resolver,
                jobs=process_jobs,
                workspace=workspace,
                bus=bus,
                llm_action=llm_action,
                home_bridge=home_bridge,
                workspace_bridge=workspace_bridge,
            )
        except ConfigError as exc:
            raise script_bridge.from_config_error(exc) from exc
        try:
            register_shell_actions(
                builder,
                settings=capabilities_settings.shell,
                jobs=process_jobs,
                workspace_bridge=workspace_bridge,
            )
        except ConfigError as exc:
            raise shell_bridge.from_config_error(exc) from exc
        script_process_enabled = capabilities_settings.script.enabled and (
            capabilities_settings.script.python.enabled
            or capabilities_settings.script.bash.enabled
        )
        shell_process_enabled = capabilities_settings.shell.enabled and (
            capabilities_settings.shell.powershell.enabled
            or capabilities_settings.shell.cmd.enabled
            or capabilities_settings.shell.bash.enabled
        )
        register_job_actions(builder, process_jobs.registry)
        register_supervised_process_actions(
            builder,
            enabled=script_process_enabled or shell_process_enabled,
            jobs=process_jobs,
            bus=bus,
            workspace_bridge=workspace_bridge,
        )
        builder.register_execution_hook(
            "supervised_process.answer_guard",
            SupervisedProcessAnswerGuard(process_jobs),
        )
        builder.use_action_execution_hooks(
            "core.answer",
            "supervised_process.answer_guard",
        )
        register_core_actions(
            builder,
            reference_resolvers=(
                WorkspacePromptReferenceResolver(
                    workspace,
                    runtime_bridge=workspace_bridge,
                ),
            ),
            llm_action=llm_action,
        )
        return builder
    except ConfigError as exc:
        raise action_bridge.from_config_error(exc) from exc
    except ActionError as exc:
        raise action_bridge.startup_failure(
            message="Common actions could not be initialized.",
            payload={"error_type": type(exc).__name__},
        ) from exc


class CommonActionAssembly:
    """Generation services used to create one profile's action surface."""

    def __init__(
        self, *, root: Path, home: AgentHomeEngine,
        workspace: WorkspaceEngine, bus: SignalBus, llm: LLMRunner,
        observations: ObservationEmitter, action_settings: ActionSettings,
        capabilities_settings: CapabilitiesSettings,
        runtime_env: dict[str, str],
    ) -> None:
        self._root = root
        self._home = home
        self._workspace = workspace
        self._bus = bus
        self._llm = llm
        self._observations = observations
        self._action_settings = action_settings
        self._capabilities_settings = capabilities_settings
        self._runtime_env = dict(runtime_env)

    def prepare(
        self, context: ContextEngine, catalog: LoadedActionCatalog, *,
        plugins: tuple[PluginDeclaration, ...],
        archive_source: Callable[[], WorkspaceArchiveView | None] | None = None,
    ) -> tuple[ActionEngineBuilder, SupervisedProcessManager, ServiceRegistry]:
        staging = StagingDirectoryManager(self._root)
        try:
            staging.prepare()
        except StagingError as exc:
            raise RuntimeLoopBridge().from_exception(
                LoopFailureKind.RESOURCE_PREPARATION_FAILED,
                exc,
            ) from exc
        process_jobs = SupervisedProcessManager(
            settings=self._capabilities_settings.supervised_process,
            mirror_service=WorkspaceMirrorService(
                self._workspace,
                max_files=self._capabilities_settings.supervised_process.max_mirror_files,
                max_total_bytes=(
                    self._capabilities_settings.supervised_process.max_mirror_bytes
                ),
                max_file_bytes=(
                    self._capabilities_settings.supervised_process.max_mirror_file_bytes
                ),
            ),
            staging=staging,
        )
        workspace_service = WorkspaceService(self._workspace)
        home_service = ServiceRegistry(tuple(service for plugin in plugins for service in plugin.services)).get(HomeService)
        script_resolver = ScriptSourceResolver(
            workspace=workspace_service,
            home=home_service,
            max_source_chars=self._capabilities_settings.script.max_source_chars,
        )
        llm_action = LLMActionTaskRunner(
            llm_runner=self._llm,
            context=context,
            action_skills=HomeActionSkillProvider(home_service, runtime_bridge=RuntimeAgentHomeBridge()),
            profile_resolver=LLMActionProfileResolver(self._action_settings.llm_action),
        )
        declarations = (
            *plugins,
            declare_workspace(workspace_service, bus=self._bus, llm_action=llm_action, archive_source=archive_source),
            PluginDeclaration(
                "capabilities",
                requires=(HomeService, WorkspaceService),
                segments=(jobs_segment_registration(),),
                actions=partial(
                    prepare_common_actions, bus=self._bus, workspace=workspace_service,
                    context=context, llm_action=llm_action,
                    capabilities_settings=self._capabilities_settings,
                    runtime_env=self._runtime_env, staging=staging,
                    process_jobs=process_jobs, script_resolver=script_resolver,
                ),
            ),
        )
        try:
            resolved = PluginRegistry(declarations).resolve(context)
            builder = ActionEngineBuilder(catalog).with_observations(self._observations)
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
        return builder, process_jobs, resolved.services
