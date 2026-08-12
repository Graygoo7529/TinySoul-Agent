"""Build the complete User Turn mainline from typed module facades."""

from __future__ import annotations

from pathlib import Path

from tinysoul.action import ActionEngine
from tinysoul.action.backends.llm_action import LLMActionTaskRunner
from tinysoul.action.config import ActionSettings, LLMActionProfileResolver
from tinysoul.capabilities import CapabilitiesSettings
from tinysoul.capabilities.script import ScriptSourceResolver
from tinysoul.capabilities.supervised_process import SupervisedProcessManager
from tinysoul.context import ContextEngine, ContextSettings
from tinysoul.context.preparation import ContextTurnPreparationHandler
from tinysoul.home import (
    AgentHomeEngine,
    HomeActionSkillProvider,
    HomeDomainSkillProvider,
)
from tinysoul.home.errors import AgentHomeError
from tinysoul.infra import StagingDirectoryManager, StagingError
from tinysoul.loop.assembly import build_turn_kernel
from tinysoul.loop.completion import TurnCompletionHandler, TurnCompletionPipeline
from tinysoul.loop.config import LoopSettings
from tinysoul.loop.preparation import TurnPreparationPipeline
from tinysoul.loop.prompts import DomainSkillProvider
from tinysoul.memory import MemoryEngine
from tinysoul.runtime import ObservationEmitter, SignalBus
from tinysoul.runtime.bridge import (
    RuntimeAgentHomeBridge,
    RuntimeContextBridge,
    RuntimeInfraBridge,
    RuntimeSessionBridge,
    RuntimeSupervisedProcessBridge,
    RuntimeWorkspaceBridge,
)
from tinysoul.session import SessionEngine
from tinysoul.session.projection import (
    SessionTurnCompletionHandler,
    SessionTurnPreparationHandler,
)
from tinysoul.workspace import (
    WorkspaceEngine,
    WorkspaceMirrorService,
    WorkspaceTurnPreparationHandler,
)

from ..phases import LLMRunner
from .actions import build_user_action
from .completion import UserAnswerCompletionDetector, user_output_from_completion
from .context import build_user_context
from .entry import UserTurnEntry
from .prompts import USER_TURN_GUIDANCE
from .runtime import build_user_turn_trap


class UserTurnBuilder:
    """Own User Context, Action and Turn runtime composition."""

    def __init__(
        self,
        *,
        root: Path,
        context_settings: ContextSettings,
        loop_settings: LoopSettings,
        capabilities_settings: CapabilitiesSettings,
        runtime_env: dict[str, str],
        llm: LLMRunner,
        home: AgentHomeEngine,
        memory: MemoryEngine,
        session: SessionEngine,
        workspace: WorkspaceEngine,
        bus: SignalBus,
        observations: ObservationEmitter,
        action_settings: ActionSettings | None = None,
    ) -> None:
        self._root = root
        self._context_settings = context_settings
        self._loop_settings = loop_settings
        self._capabilities_settings = capabilities_settings
        self._runtime_env = dict(runtime_env)
        self._action_settings = action_settings or ActionSettings()
        self._llm = llm
        self._home = home
        self._memory = memory
        self._session = session
        self._workspace = workspace
        self._bus = bus
        self._observations = observations
        self._context: ContextEngine | None = None
        self._action: ActionEngine | None = None
        self._domain_skills: DomainSkillProvider | None = None
        self._completion_handlers: list[TurnCompletionHandler] = []

    def with_context(self, context: ContextEngine) -> "UserTurnBuilder":
        self._context = context
        return self

    def with_action(self, action: ActionEngine) -> "UserTurnBuilder":
        self._action = action
        return self

    def with_domain_skills(self, domain_skills: DomainSkillProvider) -> "UserTurnBuilder":
        self._domain_skills = domain_skills
        return self

    def add_completion_handler(
        self,
        handler: TurnCompletionHandler,
    ) -> "UserTurnBuilder":
        self._completion_handlers.append(handler)
        return self

    def build(self) -> UserTurnEntry:
        context = self._context or build_user_context(
            settings=self._context_settings,
            home=self._home,
            memory=self._memory,
            observations=self._observations,
        )
        domain_skills = self._domain_skills or HomeDomainSkillProvider(
            self._home,
            runtime_bridge=RuntimeAgentHomeBridge(),
        )
        process_jobs: SupervisedProcessManager | None = None
        action = self._action
        if action is None:
            staging = StagingDirectoryManager(self._root)
            try:
                staging.prepare()
            except StagingError as exc:
                raise RuntimeInfraBridge().startup_failure(
                    message=str(exc),
                    payload={"error_type": type(exc).__name__},
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
                runtime_bridge=RuntimeSupervisedProcessBridge(),
            )
            script_resolver = ScriptSourceResolver(
                workspace=self._workspace,
                home=self._home,
                max_source_chars=self._capabilities_settings.script.max_source_chars,
            )
            action = build_user_action(
                bus=self._bus,
                workspace=self._workspace,
                context=context,
                session=self._session,
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
                llm_action_timeout_seconds=(
                    self._action_settings.llm_action.timeout_seconds
                ),
            )
        try:
            self._home.reconcile_prompt_mounts(
                domains=action.domain_names(),
                actions=action.action_identifiers(),
            )
        except AgentHomeError as exc:
            raise RuntimeAgentHomeBridge().startup_failure(
                message=str(exc),
                payload={"error_type": type(exc).__name__},
            ) from exc

        context_bridge = RuntimeContextBridge()
        session_bridge = RuntimeSessionBridge()
        workspace_bridge = RuntimeWorkspaceBridge()
        trap = build_user_turn_trap(
            context=context,
            home=self._home,
            workspace=self._workspace,
        )
        runner = build_turn_kernel(
            context=context,
            action=action,
            llm=self._llm,
            bus=self._bus,
            trap=trap,
            settings=self._loop_settings.user,
            turn_guidance=USER_TURN_GUIDANCE,
            completion_detector=UserAnswerCompletionDetector(),
            completion_to_output=user_output_from_completion,
            domain_skills=domain_skills,
            preparation_pipeline=TurnPreparationPipeline(
                (
                    ContextTurnPreparationHandler(
                        context,
                        runtime_bridge=context_bridge,
                    ),
                    SessionTurnPreparationHandler(
                        self._session,
                        runtime_bridge=session_bridge,
                    ),
                    WorkspaceTurnPreparationHandler(
                        self._workspace,
                        runtime_bridge=workspace_bridge,
                    ),
                )
            ),
            completion_pipeline=TurnCompletionPipeline(
                (
                    SessionTurnCompletionHandler(
                        self._session,
                        runtime_bridge=session_bridge,
                    ),
                    *self._completion_handlers,
                )
            ),
            activity_controller=process_jobs,
            observations=self._observations,
        )
        return UserTurnEntry(runner, action=action)
