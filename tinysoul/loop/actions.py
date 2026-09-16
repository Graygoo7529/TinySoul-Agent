"""Shared action assembly for User and Reflection profiles."""

from __future__ import annotations

from pathlib import Path
from tinysoul.action.config import ActionSettings, LLMActionProfileResolver
from tinysoul.home import HomeActionSkillProvider
from tinysoul.infra import StagingError
from tinysoul.capabilities.supervised_process import SupervisedProcessWaitPolicy
from tinysoul.capabilities.supervised_process.runtime_bridge import RuntimeSupervisedProcessBridge
from tinysoul.workspace import WorkspaceMirrorService
from .failures import LoopFailureKind
from .runtime_bridge import RuntimeLoopBridge

from tinysoul.action import (
    ActionEngine,
    ActionEngineBuilder,
    ActionError,
    LoadedActionCatalog,
)
from tinysoul.action.backends.llm_action import LLMActionTaskRunner
from tinysoul.action.builtins.core import register_core_actions
from tinysoul.capabilities import CapabilitiesSettings
from tinysoul.capabilities.resource import register_resource_actions
from tinysoul.capabilities.shell import register_shell_actions
from tinysoul.capabilities.script import ScriptSourceResolver, register_script_actions
from tinysoul.capabilities.supervised_process import (
    SupervisedProcessAnswerGuard,
    SupervisedProcessManager,
    register_supervised_process_actions,
)
from tinysoul.capabilities.web import register_web_actions
from tinysoul.context import ContextEngine
from tinysoul.context.actions import register_context_actions
from tinysoul.home import AgentHomeEngine, LLMHomeSearchReranker, register_home_actions
from tinysoul.infra import StagingDirectoryManager
from tinysoul.infra.config import ConfigError
from tinysoul.memory import MemoryEngine, register_memory_actions
from tinysoul.runtime import ObservationEmitter, SignalBus
from tinysoul.action.runtime_bridge import RuntimeActionBridge
from tinysoul.home.runtime_bridge import RuntimeAgentHomeBridge
from tinysoul.context.runtime_bridge import RuntimeContextBridge
from tinysoul.memory.runtime_bridge import RuntimeMemoryBridge
from tinysoul.capabilities.script.runtime_bridge import RuntimeScriptBridge
from tinysoul.capabilities.shell.runtime_bridge import RuntimeShellBridge
from tinysoul.workspace.runtime_bridge import RuntimeWorkspaceBridge
from tinysoul.workspace import (
    WorkspaceEngine,
    WorkspacePromptReferenceResolver,
    register_workspace_actions,
)

from .phases import LLMRunner


def prepare_common_actions(
    *,
    bus: SignalBus,
    workspace: WorkspaceEngine,
    context: ContextEngine,
    home: AgentHomeEngine,
    memory: MemoryEngine,
    llm_action: LLMActionTaskRunner,
    llm: LLMRunner,
    observations: ObservationEmitter,
    capabilities_settings: CapabilitiesSettings,
    runtime_env: dict[str, str],
    staging: StagingDirectoryManager,
    process_jobs: SupervisedProcessManager,
    script_resolver: ScriptSourceResolver,
    action_catalog: LoadedActionCatalog,
) -> ActionEngineBuilder:
    """Register common domains; the profile may add its own contributions."""

    home_bridge = RuntimeAgentHomeBridge()
    memory_bridge = RuntimeMemoryBridge()
    context_bridge = RuntimeContextBridge()
    workspace_bridge = RuntimeWorkspaceBridge()
    action_bridge = RuntimeActionBridge()
    script_bridge = RuntimeScriptBridge()
    shell_bridge = RuntimeShellBridge()
    try:
        builder = ActionEngineBuilder(action_catalog)
        builder.with_observations(observations)
        register_context_actions(
            builder,
            context=context,
            runtime_bridge=context_bridge,
        )
        register_workspace_actions(
            builder,
            workspace=workspace,
            bus=bus,
            llm_action=llm_action,
            runtime_bridge=workspace_bridge,
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
                bus=bus,
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
        register_home_actions(
            builder,
            home=home,
            runtime_bridge=home_bridge,
            search_reranker=LLMHomeSearchReranker(llm),
        )
        register_memory_actions(
            builder,
            memory=memory,
            runtime_bridge=memory_bridge,
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
        self, *, root: Path, home: AgentHomeEngine, memory: MemoryEngine,
        workspace: WorkspaceEngine, bus: SignalBus, llm: LLMRunner,
        observations: ObservationEmitter, action_settings: ActionSettings,
        capabilities_settings: CapabilitiesSettings,
        supervised_process_wait: SupervisedProcessWaitPolicy,
        runtime_env: dict[str, str],
    ) -> None:
        self._root = root
        self._home = home
        self._memory = memory
        self._workspace = workspace
        self._bus = bus
        self._llm = llm
        self._observations = observations
        self._action_settings = action_settings
        self._capabilities_settings = capabilities_settings
        self._supervised_process_wait = supervised_process_wait
        self._runtime_env = dict(runtime_env)

    def prepare(
        self, context: ContextEngine, catalog: LoadedActionCatalog,
    ) -> tuple[ActionEngineBuilder, SupervisedProcessManager]:
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
            wait_policy=self._supervised_process_wait,
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
            runtime_bridge=RuntimeSupervisedProcessBridge(),
        )
        script_resolver = ScriptSourceResolver(
            workspace=self._workspace,
            home=self._home,
            max_source_chars=self._capabilities_settings.script.max_source_chars,
        )
        builder = prepare_common_actions(
            bus=self._bus,
            workspace=self._workspace,
            context=context,
            home=self._home,
            memory=self._memory,
            llm_action=LLMActionTaskRunner(
                llm_runner=self._llm,
                context=context,
                action_skills=HomeActionSkillProvider(
                    self._home,
                    runtime_bridge=RuntimeAgentHomeBridge(),
                ),
                profile_resolver=LLMActionProfileResolver(
                    self._action_settings.llm_action
                ),
            ),
            llm=self._llm,
            observations=self._observations,
            capabilities_settings=self._capabilities_settings,
            runtime_env=self._runtime_env,
            staging=staging,
            process_jobs=process_jobs,
            script_resolver=script_resolver,
            action_catalog=catalog,
        )
        return builder, process_jobs
