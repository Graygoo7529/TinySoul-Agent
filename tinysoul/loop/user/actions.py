"""User Turn ActionEngine assembly."""

from __future__ import annotations

from tinysoul.action import (
    ActionEngine,
    ActionEngineBuilder,
    ActionError,
    builtin_action_catalog_root,
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
from tinysoul.runtime.bridge import (
    RuntimeActionBridge,
    RuntimeAgentHomeBridge,
    RuntimeContextBridge,
    RuntimeMemoryBridge,
    RuntimeScriptBridge,
    RuntimeSessionBridge,
    RuntimeShellBridge,
    RuntimeWorkspaceBridge,
)
from tinysoul.session import SessionEngine
from tinysoul.session.actions import register_session_actions
from tinysoul.workspace import (
    WorkspaceEngine,
    WorkspacePromptReferenceResolver,
    register_workspace_actions,
)

from ..phases import LLMRunner


def build_user_action(
    *,
    bus: SignalBus,
    workspace: WorkspaceEngine,
    context: ContextEngine,
    session: SessionEngine,
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
    llm_action_timeout_seconds: float = 300.0,
) -> ActionEngine:
    """Build the complete User ActionEngine from the primary catalog."""

    home_bridge = RuntimeAgentHomeBridge()
    memory_bridge = RuntimeMemoryBridge()
    context_bridge = RuntimeContextBridge()
    session_bridge = RuntimeSessionBridge()
    workspace_bridge = RuntimeWorkspaceBridge()
    action_bridge = RuntimeActionBridge()
    script_bridge = RuntimeScriptBridge()
    shell_bridge = RuntimeShellBridge()
    try:
        with builtin_action_catalog_root() as catalog_root:
            builder = ActionEngineBuilder(catalog_root)
            builder.with_observations(observations)
            builder.with_llm_action_timeout_seconds(llm_action_timeout_seconds)
            register_context_actions(
                builder,
                context=context,
                runtime_bridge=context_bridge,
            )
            register_session_actions(
                builder,
                session=session,
                runtime_bridge=session_bridge,
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
            return builder.build()
    except ConfigError as exc:
        raise action_bridge.from_config_error(exc) from exc
    except ActionError as exc:
        raise action_bridge.startup_failure(
            message=str(exc),
            payload={"error_type": type(exc).__name__},
        ) from exc
